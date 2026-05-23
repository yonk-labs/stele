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
- **Summarizer:** `lede.readable_report` (0.4.4) — summary + hint-biased
  `key_facts` in one call (the bake-off winner). chunkshop `summarize_hits`
  dropped (it is plain lede summary underneath, no facts). The benchmark sweeps
  *composition/budget/backend*, not summarizer wrappers.
- **Expansion + soft-filter:** in scope for this slice, but **opt-in**
  (`expansion_kinds=()` by default — no spaCy models load unless asked).
- **Invariant:** `recall/` must not import `lede` or `chunkshop`
  (`tests/unit/recall/test_architecture.py`). The summarizer and expander live
  under `summary/` and are injected into the strategy via `_RecallDeps`.
- **LLM-free:** `lede.readable_report` is deterministic and makes no model
  calls. Recall stays oracle-free and LLM-free. The only LLM is the downstream
  consumer reading the summary — outside stele.

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

2. **`summary/hit_summarizer.py` — `HitSummarizer` Protocol + `LedeHitSummarizer`.**
   `LedeHitSummarizer` concatenates hit texts (heading-prefixed) and calls
   **`lede.readable_report(text, max_length=budget, max_facts=N,
   hints=terms, hint_focus=0.7, keep_headings=True, backend="regex")`**, then
   emits `report.to_markdown()` as `context`. `readable_report` (lede 0.4.4) is
   the first-class form of the bake-off winner — a hint-biased summary PLUS
   hint-biased `key_facts` in one deterministic call — so we do NOT hand-roll
   summarize+key_facts+dedup. The 0.4.4 spaCy dedup fix lands on this `key_facts`
   path.
   - `backend` default **`"regex"`** = the 50% winner (summary + hint-biased
     key_facts). `backend="spacy"` additionally injects `correlate_facts`, which
     was the *worst* lane in the bake-off (22%) — so spaCy is an opt-in benchmark
     lane, never the default.
   - **No chunkshop summarizer.** chunkshop's `summarize_hits` is plain lede
     summary underneath (no facts), strictly weaker than `readable_report`;
     dropped. (chunkshop 0.5.0 still arrives in slice 2 for native *search*.)
   - The same `lede --mode report` CLI enables offline corpus pre-staging
     (precompute summaries/facts and store) — noted as a follow-up.

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
    report_backend: Literal["regex", "spacy"] = "regex"  # regex = bake-off winner; spacy adds correlate_facts (worst lane)
    max_chunks: int = 30           # cap on chunks fed to the summarizer
    max_facts: int = 40            # readable_report max_facts
    # Adaptive budget (replaces fixed max_summary_chars): floor for small
    # corpora, scaling up with returned size; ceiling caps a huge corpus.
    summary_floor_chars: int = 2000
    summary_ceiling_chars: int = 20000
    summary_chars_per_returned_char: float = 0.1  # body budget as a fraction of returned text size
    # Size gate: below this many returned tokens, skip summarization and pass raw chunks.
    min_corpus_tokens_to_summarize: int = 4000
    expansion_kinds: tuple[Literal["lemma", "synonyms", "similar"], ...] = ()  # () = no expansion
    soft_filter_weight: float = 0.25  # boost for expanded-term overlap; benchmark sweeps 0.25–0.75
    hint_focus: float = 0.7           # moderate; 0.95 over-focused and hurt accuracy
    keep_headings: bool = True
```

`expansion_kinds=()` by default means no spaCy models load unless asked. The
size gate + adaptive budget are the empirical asks: skip summarization when the
returned set is small (raw is cheap and has no fluff to remove), and scale the
summary budget with returned size (a 5K doc and a 200K doc must not share a
fixed ceiling). All defaults preserve current behavior because the strategy is
opt-in.

## Dependencies (`pyproject.toml`)

| Change | From → To | Notes |
|---|---|---|
| `lede` (core dep) | `>=0.3,<0.4` → `>=0.4.4,<0.5` | needed for `readable_report`, `hints`, `keep_headings`, `top_terms`; 0.4.4 also fixes spaCy fact-extraction duplication |
| `chunkshop` extra | unchanged this slice | NOT bumped for the summarizer (dropped); chunkshop 0.5.0 bump moves to slice 2 (native search) |
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
- **Benchmark:** owned by a **sibling spec that runs FIRST** — the recall
  grounding benchmark (honest baselines, larger docs, answer-equivalence judge,
  scenarios d–g, weight/budget sweeps). `digest_search`'s defaults
  (`report_backend`, budget floor/ceiling, `min_corpus_tokens_to_summarize`,
  `soft_filter_weight`, `hint_focus`) are **set by that study's findings**, so
  the digest_search implementation plan depends on it. Per the repo rule,
  accuracy claims require the answer-workflow benchmark, not the showcase.

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
- **Pre-staging:** the `lede --mode report` CLI / `readable_report` can
  precompute summaries + facts offline and store them (as artifacts/memory) so
  recall is faster and more accurate at query time. Likely its own slice.

## In-slice fix — summary truncation

`summary/lede_adapter.py::_trim` hard-chops with `"..."`. `readable_report`
respects `max_length` for the extractive body, but `keep_headings`/TOC/`pin` are
**additive** (intentionally exceed `max_length`). A post-hoc chop would sever
headings/facts and silently hurt accuracy. Fix: let `readable_report`'s budget
govern selection; never chop the report's structural/pinned content. The
adaptive budget (config) sets `max_length` per request.

## Update log

- **2026-05-23:** lede bumped 0.4.2 → **0.4.4**; summarizer switched to
  `readable_report` (first-class winner composition + spaCy dedup fix);
  chunkshop summarizer **dropped** (lede underneath); fixed `max_summary_chars`
  replaced by size-gate + adaptive budget; `soft_filter_weight` sweep 0.25–0.75;
  benchmark redesigned (honest baselines, larger docs, answer-equivalence judge,
  scenarios d–g) and flagged as a possible sibling spec; truncation fix added.
  Driven by the 10-strategy bake-off (`summary+facts` = 50% acc / 67% tok
  reduction winner) and lede 0.4.4. Two open forks remain (chunkshop summarizer
  → resolved to *drop*; benchmark scope → still open).
