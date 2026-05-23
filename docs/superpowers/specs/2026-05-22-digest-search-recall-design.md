# Design — `digest_search` recall strategy (query-driven fast-mode recall)

Date: 2026-05-22
Status: Draft for review
Topic: Token-cheap, query-biased recall that summarizes many retrieved
chunks into one summary, stores the chunks, and surfaces the full sources for
escalation.

## Purpose

Give agents a recall path that is cheap on input tokens without leaning on the
LLM to read 20–30 raw chunks. Take a query, run it through stele's existing
search, optionally widen the query terms (the "city/borough crossover" fix),
re-rank the hits softly toward the query terms, then collapse the top chunks
into a single query-biased summary. Send the summary to the LLM; keep the full
chunks as cited sources so the consumer can offer "ask and we'll give more."

This is **slice 1** of a two-slice effort. Slice 2 (separate spec) evaluates
migrating the *search* step to chunkshop 0.5.0's native search surface
(semantic/keyword/hybrid + DB-side FTS + `where` filter). This slice keeps
stele's existing retrieval and adds the strategy + summarizer + expansion on
top.

## Settled decisions (from brainstorming)

- **Placement:** a new dedicated strategy `digest_search`, not an extension of
  `adaptive`. One file, one purpose; `adaptive` may add it as a tier later.
- **Search engine:** stele's existing retrieval (unchanged in this slice).
- **Summarizer:** implement *both* lede-direct and chunkshop `summarize_hits`;
  a benchmark picks the default that `"auto"` resolves to.
- **Expansion + soft-filter:** in scope for this slice, but **opt-in**
  (`expansion_kinds=()` by default — no spaCy models load unless asked).
- **Invariant:** `recall/` must not import `lede` or `chunkshop`
  (`tests/unit/recall/test_architecture.py`). The summarizer and expander live
  under `summary/` and are injected into the strategy via `_RecallDeps`.
- **LLM-free:** lede and chunkshop's summarize step are deterministic and make
  no model calls. Recall stays oracle-free and LLM-free. The only LLM is the
  downstream consumer reading the summary — outside stele.

## Architecture & data flow

```
query
  │  ① expand        (deps.expander — summary/, uses lede.top_terms + optional lede-spacy)
  ▼  → [original terms + lemma/synonym/similar variants]
  │  ② search        (deps.stele.query / .search — EXISTING retrieval, unchanged)
  ▼  → list[SearchHit]  (up to max_chunks, already PII-scrubbed at write)
  │  ③ soft-rank     (pure, in recall/: boost hits by expanded-term overlap; NEVER exclude)
  ▼  → re-ordered hits
  │  ④ summarize     (deps.summarizer — summary/, lede-direct OR chunkshop.summarize_hits)
  ▼  → one query-biased summary (hints=terms, keep_headings=True)
  │  ⑤ emit
  ▼
RecallResult(
   strategy_used = "digest_search",
   context       = summary,                     # the cheap thing the LLM reads
   citations     = [full chunk refs + snippets] # the "other full sources" for escalation
   escalations   = [Escalation(reason="digest_partial", hit_count=N, ...)],
   source_refs   = [...],
   pii_flags     = [...],                        # propagated from hits
   stats         = RecallStats(...),
)
```

The escalation hatch is **data, not prose**: the strategy puts the summary in
`context` and the *full* chunk references in `citations`. The sentence "if this
doesn't answer, ask and we'll give more" is added by the consumer layer (the
MCP `recall` tool / skill template), driven by `citations` being non-empty.
This keeps the strategy deterministic and LLM-free while giving the consumer
everything it needs to offer more.

### Invariant compliance

`recall/digest_search.py` imports neither lede nor chunkshop — it calls
`deps.expander` and `deps.summarizer`, both implemented under `summary/`. The
architecture test stays green. Summary text inherits PII-scrubbing from the
already-scrubbed chunks (no re-scrub), per the existing recall rule.

## Components

### New, under `summary/` (lede/chunkshop allowed here)

1. **`summary/expansion.py` — `QueryExpander`.**
   `expand(query, *, kinds) -> list[str]`. Pulls salient terms via
   `lede.extract.top_terms(query, with_scores=True)`, then optionally widens
   each via `lede_spacy.expand_hints(kinds=("lemma"|"synonyms"|"similar"))`.
   Graceful degradation: lede-spacy missing → return raw top_terms; vector
   model missing for `"similar"` → fall back to `"lemma"` with a logged
   warning. Pure given a fixed model.

2. **`summary/hit_summarizer.py` — `HitSummarizer` Protocol + two impls.**
   - `LedeHitSummarizer` — concatenates hit texts (heading-prefixed), calls
     `lede.summarize(text, hints=terms, keep_headings=True, max_length=…)` via
     the existing `lede_adapter`.
   - `ChunkshopHitSummarizer` — adapts `SearchHit → chunkshop.Hit`, calls
     `chunkshop.search_common.summarize_hits(hits, summarize, hints=…,
     prepend_headings=True)`.
   - Selected by config (`"lede" | "chunkshop"`); `"auto"` resolves to the
     benchmark-chosen default constant `_DEFAULT_SUMMARIZER`.

### New, under `recall/` (pure orchestration, NO lede/chunkshop import)

3. **`recall/digest_search.py` — `DigestSearchStrategy`** (`name="digest_search"`).
   Calls `deps.expander`, `deps.stele.query/search`, a pure local `_soft_rank`,
   then `deps.summarizer`. Emits the `RecallResult` above.

### Changed

4. **`recall/base.py::_RecallDeps`** — add two injected fields: `expander` and
   `summarizer`, typed via `Protocol` under `TYPE_CHECKING` so `recall/` never
   imports the concrete (lede/chunkshop-touching) classes.

5. **Construction boundary.** The `Stele` core (`core/stash.py`, which already
   imports lede via `summary/`) constructs the expander + summarizer and passes
   them into `Recall(...)`. `recall/facade.py` receives them as opaque injected
   deps. This is what keeps the import-layer test green — `facade.py` is itself
   under `recall/`.

6. **`recall/models.py`** — add `"digest_search"` to `StrategyName`; add
   `"digest_partial"` to `EscalationReason`. Both additive.

7. **`core/config.py`** — new `DigestConfig` nested under `RecallConfig`.

8. **`recall/facade.py`** — register `DigestSearchStrategy()`; thread the
   `digest_search` request params.

Two separate files (`expansion.py`, `hit_summarizer.py`) keep each unit
single-purpose and independently testable.

## Config

```python
class DigestConfig(BaseModel):
    summarizer: Literal["lede", "chunkshop", "auto"] = "auto"
    max_chunks: int = 30           # cap on chunks fed to the summarizer
    max_summary_chars: int = 1500  # lede max_length; "extra rows if lots of data"
    expansion_kinds: tuple[Literal["lemma", "synonyms", "similar"], ...] = ()  # () = no expansion
    soft_filter_weight: float = 0.25  # boost magnitude for expanded-term overlap; 0 = pure search order
    keep_headings: bool = True
```

`"auto"` resolves to a module-level `_DEFAULT_SUMMARIZER` constant the benchmark
sets. `expansion_kinds=()` by default means no spaCy models load unless asked.
All defaults preserve current behavior because the strategy is opt-in.

## Dependencies (`pyproject.toml`)

| Change | From → To | Notes |
|---|---|---|
| `lede` (core dep) | `>=0.3,<0.4` → `>=0.4.2,<0.5` | needed for `hints`, `keep_headings`, `top_terms` |
| `chunkshop` extra | `>=0.4.3,<0.5` → `>=0.5.0,<0.6` | needed for `summarize_hits` |
| new `expansion` extra | — | `lede-spacy>=0.4.2` (+ `[synonyms]` for synonym/similar; vector model installed separately) |
| mypy overrides | add `lede_spacy.*` | matches existing `lede`/`chunkshop` ignores |

The `lede` bump is the one non-additive risk: it is a **core** dependency, so
every install moves to 0.4.x. lede promises byte-identical output when the new
kwargs are omitted, so existing `summary/` + `extraction/` call sites are
unaffected — verified by the existing test suite, not assumed.

`similar`/`synonyms` expansion needs a spaCy model the user downloads
(`en_core_web_md`/`lg`); we can't vendor it. The expander degrades to
`lemma`/raw terms when absent. A one-time setup script (mirroring
`scripts/chunkshop-setup.sh`) documents the model install.

## Error handling & degradation (degrade-with-flag, as in `hybrid.py`)

- **Expansion unavailable** (lede-spacy or model missing): expander returns raw
  `top_terms`; if even `top_terms` is empty, the strategy uses the raw query.
  Logged WARNING, never raises. The requested-kind → available-kind fallback is
  recorded in `RecallStats` so a run is self-documenting.
- **Summarizer fails / both paths raise**: fall back to legacy behavior —
  concatenated chunk snippets in `context` (what `artifact_search` does today),
  tagged so it's visible the digest degraded. The LLM still gets usable context.
- **Zero search hits**: empty-context `RecallResult` with
  `escalations=[reason="zero_hits"]`, identical to `artifact_search`'s contract.
- **PII**: no new surface. Chunks were scrubbed at write; the summary is derived
  from scrubbed text, so no re-scrub. `pii_flags` still propagated from hits.
- **Determinism**: same query + same corpus + same model ⇒ same summary. The
  spaCy model identity (when expansion is on) is a fingerprint input.

## Testing & benchmark

- **Unit (pure tier):** `_soft_rank` (boost-not-exclude, ordering);
  `QueryExpander` degradation ladder (mock lede-spacy present/absent);
  `DigestSearchStrategy` orchestration with fake `expander`/`summarizer` deps —
  no lede/chunkshop needed.
- **Architecture test:** existing `tests/unit/recall/test_architecture.py` must
  stay green — fails loudly if `digest_search.py` imports lede/chunkshop. This
  is the guardrail proving the injection boundary holds.
- **Contract:** add `digest_search` cases to
  `tests/contract/test_recall_contract.py`, parametrized across backends
  (postgres default).
- **Benchmark (the default-picker):** extend the LLM-judged `answer_workflow`
  benchmark with a `digest_search` lane × {lede, chunkshop} summarizer,
  compared against the `artifact_search` (raw-chunks) baseline on the same judge
  + corpus. Metrics: judged answer accuracy, input-token count, latency. The
  winning summarizer sets `_DEFAULT_SUMMARIZER`. Per the repo rule, accuracy
  claims require the answer-workflow benchmark, not the showcase.

## Out of scope (this slice)

- Migrating the *search* step to chunkshop 0.5.0 native search / DB-side FTS /
  `where` filter — separate slice 2 spec.
- pg-raggraph version bump — that dependency is under active development
  upstream; revisit the `==0.3.0a3` pin when a new release lands.
- Any change to the existing seven strategies, including `adaptive`.
- Re-scrubbing PII on the summary (explicitly not done; chunks are pre-scrubbed).

## Open follow-ups (noted, not in this slice)

- Once slice 2 lands chunkshop native FTS, the soft-filter and expansion could
  move from query-rewrite into the search leg itself.
- `top_terms` is Python-only in lede 0.4.x; if Python↔Rust parity of the
  expansion step ever matters, it waits for lede 0.5.
