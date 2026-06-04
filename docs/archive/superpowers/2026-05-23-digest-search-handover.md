# Handover — `digest_search` recall strategy (session switch)

Date: 2026-05-23
Author: prior session (brainstorming phase, mid-flight)
Purpose: complete state + next steps so a fresh session can continue without
re-deriving anything.

---

## TL;DR / where we are

We are **brainstorming** a new recall strategy, `digest_search`: query-driven
fast-mode recall that searches, optionally expands query terms, soft-ranks,
**summarizes many chunks into one query-biased summary**, sends the summary as
`context`, and keeps the full chunks **cited** so the consumer can offer "ask
and we'll give more."

- A v1 design spec is **committed**: `dee68fc`
  `docs/superpowers/specs/2026-05-22-digest-search-recall-design.md`.
- **That spec is now partly stale.** New empirical findings (below, from two
  parallel sessions) materially change the summarizer content, the budget
  model, and the benchmark. The spec must be revised before writing the plan.
- We have **NOT** written an implementation plan and have **NOT** written any
  code. Hard gate: no code until the revised design is approved.

## Decisions already locked (still valid)

1. **Placement:** new dedicated strategy `digest_search` (its own file), NOT an
   extension of `adaptive`. `adaptive` may add it as a tier later.
2. **Search engine:** stele's EXISTING retrieval this slice. chunkshop 0.5.0
   *native search* migration is **slice 2** (separate spec, deferred).
3. **Expansion + soft-filter:** in scope but **opt-in** (`expansion_kinds=()`
   default — no spaCy models load unless asked). lemma/synonyms/similar via
   `lede-spacy`; the "similar"/"synonyms" kinds need a downloaded spaCy vector
   model and degrade gracefully when absent.
4. **Hard invariant:** `recall/` must not import `lede` or `chunkshop`
   (`tests/unit/recall/test_architecture.py`). Summarizer + expander live under
   `summary/` and are **injected into the strategy via `_RecallDeps`**,
   constructed by `core/stash.py` (which already imports lede via `summary/`)
   and passed into `Recall(...)`. `recall/facade.py` receives them as opaque
   Protocol-typed deps.
5. **LLM-free recall stays intact:** lede + chunkshop summarize steps are
   deterministic, no model calls. Only the downstream consumer (outside stele)
   uses an LLM.
6. **Escalation hatch is DATA not prose:** strategy emits `context`=summary +
   `citations`=full chunk refs. The "ask for more" sentence is added by the
   consumer layer (MCP `recall` tool / skill template), driven by non-empty
   citations.

## NEW empirical findings (NOT yet in the spec — must fold in)

### Bake-off (90 questions: MHR + MuSiQue + 2Wiki, gpt-5-mini, n=30/dataset, ±~9pp noise)

| strategy | accuracy | tok reduction | verdict |
|---|---|---|---|
| chunks (control) | 53% | 0% | baseline |
| **summary_facts** | **50%** | **67%** | ✅ winner |
| summary (current) | 46% | 80% | solid |
| summary_long | 46% | 62% | length alone doesn't help |
| summary_plus_top2 | 44% | 61% | meh |
| hint_focus_high (0.95) | 44% | 80% | over-focusing hurts |
| per_chunk_facts | 37% | 79% | option-B: worse |
| facts_only | 32% | 84% | prose matters |
| per_chunk_summary | 30% | 83% | option-B: worst-ish |
| correlate_facts | 22% | 41% | ❌ verbose AND inaccurate |

Conclusions:
- **Winner = `summary + hint-biased key_facts`** (lede summary + appended
  hint-biased `lede.extract.key_facts`). ~ties raw chunks within noise, 67%
  fewer tokens. On MHR it ties raw chunks (67%=67%) at 82% reduction; on 2Wiki
  it beats chunks (53% vs 50%).
- **It's the extracted FACTS that recover accuracy, not length** (summary_long
  stayed 46%).
- **Concatenate-then-summarize-once beats per-chunk** — settled. Our design
  already concats. Do NOT do per-chunk.
- **Structured S-R-V (`correlate_facts`) is the WORST** — avoid.
- **Prose matters** — `facts_only` (no prose) dropped to 32%.
- **Over-focusing hurts** — `hint_focus=0.95` hurt; keep hint_focus moderate.
- **chunkshop's summarizer is lede underneath** → benchmarking lede-vs-chunkshop
  summarizers is lede-vs-itself. The real axis to sweep is summary *composition*
  + *budget*, not the wrapper.
- **Gap today:** stele only uses `top_terms` for hint seeds; we do NOT wire
  `lede.key_facts` into the summary. Closing that gap IS the winner. Contained
  change to the chunk-summarize function.
- **Extractive summaries can't abstain** — summary_only scores 0 on every
  "insufficient information" gold (much of MHR). `summary → LLM` is the right
  floor (LLM can abstain on the summary).
- **MuSiQue (multi-hop) stays stubborn** (chunks 43% best; facts didn't help).
  Keep the escalation path.

### Raggraph-session notes (apply the generally-applicable ones here)

- **Multi-hop is real for graph** — keep escalation; don't assume single-pass.
- **Budget ceiling is too low.** Each chunk < ~500 tokens usually; returning
  10/100/1000 chunks → wildly different totals. Summary ceiling must vary with
  returned size. Fixed 1500 chars is wrong.
- **Add a SIZE GATE:** when the total returned dataset ≤ X tokens, **skip
  summarization** (raw 2.5K tokens is cheap at scale AND has no fluff for the
  summary to remove). Above X → summarize, with a floor size; as corpus grows,
  raise ceiling/floor. Current 2.5K-total tests are too small to be meaningful.
- **Truncation question (INVESTIGATE):** what happens when the summary hits
  max_length — truncate? `summary/lede_adapter.py::_trim` hard-chops with "...".
  `keep_headings`/`pin` are ADDITIVE (can exceed max_length), so a post-hoc chop
  could be silently severing headings/facts → accuracy loss. Fix: let the budget
  govern lede's extractive selection, never post-hoc chop pinned content.
- **Baselines must be honest** (we need to know if the LLM is just bad, or the
  size is right — avoid "chasing white whales"):
  - a) ask the LLM cold (no context)
  - b) supply the full doc, ask
  - c) relevant chunks — try 10 / 20 / 30
  - d) summarize-with-facts the entire doc → add as chunk 1 + return other chunks
  - e) summarize entire doc w/ facts + hints → put on top of 10 chunks
  - f) summarize full doc w/ facts + TOC + hints, THEN summarize chunks w/ hints → return that
  - g) finish the suite following this logic
  - **Use LARGER docs**, not smaller.
- **Judge change:** current judge asks for "all the same facts." User wants
  **"does it answer the same question"** (answer-equivalence), not fact-set
  equality.
- **Weights:** user has been tuning; **sweep soft_filter / hint weights between
  0.25 and 0.75**.
- **Latency budget:** must NOT add seconds of latency.
- **Pre-staging idea (future):** background-process summaries + fact extraction
  and STORE them (precompute), so recall is fast and more accurate. Likely its
  own slice; note as a follow-up direction (precompute + store summaries/facts
  as artifacts/memory).

## Pending changes to the spec (apply these on revision)

1. **Summarizer = summary + hint-biased `key_facts`** (replaces "plain
   summary"). `LedeHitSummarizer`: call `lede.summarize(hints, keep_headings)`
   AND `lede.extract.key_facts(text, hints=...)`, append facts as prose. Keep
   prose (facts_only loses). Keep hint_focus moderate (~0.7, not 0.95).
2. **Size gate**: `min_corpus_tokens_to_summarize` — below ⇒ pass raw chunks
   through unchanged; above ⇒ summarize.
3. **Adaptive budget**: remove fixed `max_summary_chars=1500`. Replace with a
   floor + scaling-with-returned-size model (small floor for ~5K doc; 10–20K
   ceiling for ~200K doc). Make floor + scaling configurable.
4. **Truncation fix** in `lede_adapter`: budget governs extractive selection;
   never hard-chop headings/pinned facts.
5. **`soft_filter_weight`** stays a config field, benchmark **sweeps 0.25–0.75**.
6. **Benchmark/judge redesign**: baselines {cold, full-doc, N-chunks 10/20/30} +
   scenarios d–g; larger docs; judge → answer-equivalence ("answers the same
   question").
7. **Keep escalation path** (multi-hop / abstain floor).

## OPEN FORKS — answer these first in the next session

1. **chunkshop summarizer path: keep or drop?** Finding says it's lede
   underneath (redundant). Recommendation: **drop** as a summarizer (sweep
   composition + budget instead); chunkshop 0.5.0 still arrives in slice 2 for
   native SEARCH. (Alternative: keep one chunkshop lane as a one-off control to
   confirm equality, then drop.) — *user asked to clarify before answering;
   re-ask.*
2. **Benchmark scope: sibling spec (runs first) vs folded into this spec?** The
   grounding benchmark (baselines + scenarios d–g + larger docs + judge change)
   is large. Recommendation: **sibling "recall grounding benchmark" spec that
   runs first** and establishes the answer-equivalence judge + baselines BEFORE
   locking digest_search defaults; digest_search depends on its findings. —
   *user asked to clarify before answering; re-ask.*

## Architecture recap (where code will land)

New under `summary/` (lede/chunkshop allowed):
- `summary/expansion.py` — `QueryExpander.expand(query, *, kinds)` via
  `lede.extract.top_terms` + optional `lede_spacy.expand_hints`. Graceful
  degradation ladder; pure given a fixed model.
- `summary/hit_summarizer.py` — `HitSummarizer` Protocol. `LedeHitSummarizer`
  (summary + hint-biased key_facts). chunkshop impl TBD per fork #1.

New under `recall/` (pure orchestration, NO lede/chunkshop import):
- `recall/digest_search.py` — `DigestSearchStrategy` (`name="digest_search"`).
  Pipeline: expand → search (existing) → `_soft_rank` (boost-not-exclude) →
  size-gate → summarize-or-passthrough → emit `RecallResult`.

Changed:
- `recall/base.py::_RecallDeps` — add injected `expander` + `summarizer`
  (Protocol-typed under TYPE_CHECKING).
- `core/stash.py` — construct expander + summarizer, pass into `Recall(...)`.
- `recall/models.py` — add `"digest_search"` to `StrategyName`,
  `"digest_partial"` to `EscalationReason` (additive).
- `core/config.py` — new `DigestConfig` (summarizer, size gate, budget floor +
  scaling, expansion_kinds, soft_filter_weight, keep_headings).
- `recall/facade.py` — register strategy, thread params.

## Dependencies (pyproject.toml)

- `lede` core dep: `>=0.3,<0.4` → `>=0.4.2,<0.5` (hints, keep_headings,
  top_terms, key_facts-with-hints). Non-additive risk: core dep moves to 0.4.x;
  lede claims byte-identical when new kwargs omitted — VERIFY via existing suite.
- `chunkshop` extra: `>=0.4.3,<0.5` → `>=0.5.0,<0.6` (only if chunkshop
  summarizer kept — see fork #1; chunkshop 0.5.0 search lands in slice 2 anyway).
- new `expansion` extra: `lede-spacy>=0.4.2` (+ `[synonyms]`); spaCy vector
  model installed separately (one-time setup script, mirror
  `scripts/chunkshop-setup.sh`).
- mypy overrides: add `lede_spacy.*`.

Currently installed in `.venv`: lede 0.3.0, chunkshop present (no `__version__`,
likely 0.4.x), pg-raggraph NOT installed. **The new versions (lede 0.4.2,
chunkshop 0.5.0) are NOT installed locally yet** and PyPI was unreachable from
the sandbox — install + verify before any code change.

## pg-raggraph

Pinned `==0.3.0a3`; **under active upstream development** — do not touch this
slice. Revisit the pin when a new release lands.

## Key files / commands

- Spec (committed `dee68fc`):
  `docs/superpowers/specs/2026-05-22-digest-search-recall-design.md`
- Recall facade: `src/stele/recall/facade.py`; models:
  `src/stele/recall/models.py`; closest existing analog:
  `src/stele/recall/artifact_search.py` (concat snippets → context).
- Architecture guard: `tests/unit/recall/test_architecture.py` (forbids lede +
  chunkshop in `recall/`).
- lede wrapper: `src/stele/summary/lede_adapter.py` (`_trim` truncation lives
  here — investigate).
- extraction lede passes: `src/stele/extraction/candidates.py` (already uses
  summarize/key_facts/stats/phrases — reference for the key_facts call shape).
- chunk store base (slice-2 search migration target):
  `src/stele/storage/chunk_store/_chunkshop_base.py` (docstring rationale is
  obsolete under chunkshop 0.5.0).
- Benchmarks: `.venv/bin/python -m benchmarks.answer_workflow` (LLM-judged — the
  default-picker / grounding); `scripts/run-answer-workflow-judge.sh`.
- Before-commit trio: `.venv/bin/ruff check .` · `.venv/bin/mypy src tests
  benchmarks` · `.venv/bin/pytest`.

## Next steps (ordered)

1. Re-ask the two OPEN FORKS (chunkshop summarizer keep/drop; benchmark scope).
2. Revise the spec with pending changes 1–7; re-run brainstorming spec
   self-review; get user approval.
3. If benchmark split into a sibling spec: brainstorm that spec first (baselines
   + answer-equivalence judge + larger docs), since it grounds the defaults.
4. Install lede 0.4.2 / chunkshop 0.5.0 / lede-spacy in `.venv`; run the
   before-commit trio to confirm the lede core bump is byte-safe.
5. Only then: invoke `writing-plans` for the implementation plan.

## What to remember (durable)

- postgres is the default backend for tests/benchmarks; ASK before adding
  sqlite/memory/other backends.
- Don't write to branches another agent is working; current branch
  `feat/full-benchmark-showcase`.
- Accuracy claims require the answer-workflow benchmark, not the showcase.
- LLM graph is NOT the LoCoMo answer-span lever; retrieval-ranking is.
- Untracked at session start (NOT ours, leave alone): `.stele/`,
  `benchmarks/external/preserved/`.
