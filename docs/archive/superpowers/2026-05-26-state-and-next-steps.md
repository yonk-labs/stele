# State & Next Steps — digest_search + grounding benchmark (waiting on upstream)

Date: 2026-05-26 (updated later same day — deps landed, see Migration status)
Branch: `feat/full-benchmark-showcase`
Status: **Deps now installable; lede+chunkshop bump verified.** Upstream
(lede/chunkshop/pg-raggraph) are feature-complete on this server and being
pushed to PyPI. The hard gate is cleared for lede+chunkshop. One architectural
decision (digest_search build-vs-buy) now blocks the rest — see below.

## Migration status (2026-05-26 update)

Pins bumped in `pyproject.toml`: `lede>=0.4.5,<0.5`, `chunkshop>=0.6.1,<0.7`,
`pg-raggraph==0.4.0a1`, plus `lede-spacy>=0.4.5`.

- **lede 0.3.0 → 0.4.5 + chunkshop 0.4.3 → 0.6.1: VERIFIED byte-safe.** Installed
  from PyPI. `ruff check .` clean, `mypy src` clean (126 files), `pytest`
  771 passed / 22 skipped. (The 44 `mypy src tests benchmarks` errors are
  pre-existing mypy-2.x debt in untyped test/benchmark fixtures — zero in
  `src/`, not caused by the bump. Separate cleanup if desired.)
- **pg-raggraph 0.4.0a1: pin bumped, NOT yet installed/verified.** Not on PyPI
  (release in flight); the local repo is the RC. The harness blocked installing
  it from the local clone as untrusted external code. To verify the graph path,
  install it manually (`uv pip install --python .venv/bin/python
  /home/yonk/yonk-tools/pg-raggraph`) then run the DSN-gated graph tests.
- **pg-raggraph audit corrected.** Reading the real 0.4.0a1 source invalidated
  the old migration plan: `profile=` only shapes `result.context` (all rungs
  `top_k=25`), which stele's revisor discards (it consumes `res.chunks`). The
  decision-independent win is `retrieval_strategy="vector_first"` (chunk-substrate
  speedup), not `profile=`. See `2026-05-24-pg-raggraph-profile-audit.md` (revised).

## ⛔ Decision now gating the rest: digest_search build-vs-buy

The `digest_search` design (stele does its own retrieval, then lede-summarizes
the hits, no LLM) is now shipped natively **twice** upstream:
- **chunkshop 0.5.0** — `search(return="summary"|"summary+chunks")` +
  `summarize_hits` (hint-biased lede summary over top-K hits).
- **pg-raggraph 0.4.0a1** — `mode="summary"` + `summary_base_mode` (no-LLM lede
  hint-biased summary in `result.summary`), and the `profile` context-packing
  ladder (`doc_and_chunk_summary_toc_facts_plus_top5`, etc.).

So the open question is **build vs buy**: keep building `digest_search` on
stele's own retrieval (full control, re-implements upstream), or delegate to
chunkshop/pg-raggraph summary surfaces (less code, pierces the `recall/`
no-lede/chunkshop import invariant unless kept behind `_RecallDeps`). The
grounding benchmark should decide this — **add upstream `mode="summary"` /
`summarize_hits` as benchmark lanes** alongside the `digest_regex`/`digest_spacy`
lanes and let the numbers pick.

Supersedes the stale parts of `2026-05-23-digest-search-handover.md`. This is
the single source of truth for current state.

## One-paragraph summary

We designed a new recall strategy, **`digest_search`** — query-driven fast-mode
recall that searches, expands query terms, soft-ranks, summarizes the retrieved
chunks into one compact query-biased summary (lede `readable_report`), sends the
summary as `context`, and keeps full chunks cited for escalation. A **sibling
grounding-benchmark spec runs first** to set its defaults via honest baselines on
larger docs with a graded answer-equivalence judge. Separately, we audited
**pg-raggraph** and decided not to migrate to its new retrieval-profile ladder
yet (API not in the pinned version). Everything is committed locally; nothing is
pushed.

## Committed (local, unpushed — 8 commits on top of `8704b5f`)

| Commit | What |
|---|---|
| `dee68fc` | digest_search v1 spec |
| `8b0d2cd` | (older) session handover — partly superseded by this file |
| `199647b` | digest_search → lede 0.4.4 `readable_report` (winner composition + dedup fix) |
| `2a92fa0` | benchmark extracted to a sibling spec |
| `8e361fe` | recall grounding benchmark spec (runs first) |
| `3160139` | notes on lede 0.4.5 features |
| `dadf9da` | applied lede 0.4.5 action items to both specs |
| `4b15124` | pg-raggraph retrieval-profile migration audit |

Key documents:
- Spec A (depends on B): `docs/superpowers/specs/2026-05-22-digest-search-recall-design.md`
- Spec B (runs first): `docs/superpowers/specs/2026-05-23-recall-grounding-benchmark-design.md`
- lede notes: `docs/superpowers/2026-05-23-lede-0.4.5-features.md`
- pg-raggraph audit: `docs/superpowers/2026-05-24-pg-raggraph-profile-audit.md`

Untracked, NOT ours (leave alone): `.stele/`, `benchmarks/external/preserved/`.

## Locked design decisions

- **`digest_search`** = a new dedicated recall strategy (not an `adaptive`
  extension), built on stele's EXISTING retrieval. chunkshop 0.5.0 native-search
  migration is a deferred **slice 2**.
- **Summarizer** = `lede.readable_report` (the bake-off winner: hint-biased
  summary + hint-biased `key_facts`). chunkshop `summarize_hits` **dropped**
  (lede underneath). Slice 1 uses only the compact `.to_markdown()` human
  surface.
- **Invariant**: `recall/` must not import lede/chunkshop
  (`tests/unit/recall/test_architecture.py`). Summarizer + expander live under
  `summary/`, injected via `_RecallDeps`, constructed in `core/stash.py`.
- **Config**: size-gate (skip summarization below N tokens) + adaptive budget
  (floor/ceiling scaling with returned size) replace any fixed char cap;
  `report_backend="regex"` default (spaCy opt-in — it adds `correlate_facts`,
  the worst bake-off lane); expansion opt-in (`expansion_kinds=()`).
- **Grounding benchmark first**: it sets digest defaults + ship/no-ship.
  Lanes = {cold_llm, full_doc, chunks_10/20/30, digest_regex, digest_spacy,
  scenarios d–f}. Corpora = SCOTUS (+~40 authored gold, incl. a deterministic-
  attribute subset) + LongBench-long + MHR (medical-hrt). Judge = graded
  0/0.5/1 answer-equivalence via `rejudge.py` replay. Prereq: raise the
  ~2000-char ingest truncation cap. n≈60/dataset.
- **pg-raggraph**: no change now; staged migration documented (swap
  `mode/rerank → profile` in the revisor on release + pin bump).

## Upstream status (mostly resolved 2026-05-26)

1. **pg-raggraph profile API** — RESOLVED: landed in `0.4.0a1` (`profile=` +
   `retrieval_strategy` + `mode="summary"`). Pin bumped. Still needs a manual
   install (not on PyPI) to run the graph tests; the latency fix + index/
   namespace-profile migrations come with it. NOTE the audit's old plan is
   corrected (profile≠chunk results) — see Migration status above.
2. **Local dependency installs** — RESOLVED for lede/chunkshop: PyPI reachable;
   lede 0.4.5 + lede-spacy 0.4.5 + chunkshop 0.6.1 installed and the bump
   verified byte-safe. spaCy model still needed for the `expand_hints` expansion
   path if/when that lane runs.
3. **chunkshop PR #40** — superseded: chunkshop is now 0.6.1 (well past 0.5.0).
   Confirm the relevant search/benchmark path on 0.6.1 if slice 2 uses it.

## Open items requiring the user (review gate)

- **Grounding-benchmark spec review** — still awaiting sign-off before
  `writing-plans`. Specific spots flagged: SCOTUS gold size (~40) and who authors
  it (manual, on the critical path); `n≈60/dataset`; the d–f scenario set.
- After approval, the brainstorming flow transitions to **`writing-plans`**, and
  the grounding benchmark is planned FIRST (it gates digest defaults).

## Next steps (ordered, resume here)

1. ✅ DONE — pins bumped; lede 0.4.5 + chunkshop 0.6.1 bump verified byte-safe
   (ruff clean, mypy src clean, pytest 771 passed).
2. **(User)** Install pg-raggraph 0.4.0a1 locally (harness blocked the agent):
   `uv pip install --python .venv/bin/python /home/yonk/yonk-tools/pg-raggraph`,
   then run the DSN-gated graph tests to confirm the bump is safe on the graph
   path. (Or grant the agent a Bash permission rule for it.)
3. **(User)** Approve / adjust the grounding-benchmark spec — and add upstream
   `pg-raggraph mode="summary"` + `chunkshop search(return="summary")` /
   `summarize_hits` as benchmark lanes so the build-vs-buy decision is settled by
   data (see the ⛔ Decision section).
4. Invoke `writing-plans` for the grounding benchmark spec; execute it; record
   the winning digest defaults + ship/no-ship AND the build-vs-buy verdict.
5. Per the verdict: either implement `digest_search` on stele's own retrieval, OR
   route to the upstream summary surfaces behind `_RecallDeps`.
6. pg-raggraph perf (decision-independent): thread `retrieval_strategy` through
   `GraphConfig` + the revisor to expose `vector_first` for broad single-namespace
   graph queries (NOT `profile=` — see corrected audit). Benchmark the recall
   caveat before changing the default.

## What to remember (durable)

- postgres is the default backend for tests/benchmarks; ASK before adding
  sqlite/memory/other backends.
- Don't write to branches another agent is working; pg-raggraph is under active
  upstream dev — wait for the release.
- Accuracy claims require the answer-workflow benchmark, not the showcase.
- The bake-off winner is `summary + hint-biased key_facts` (50% acc / 67% tok
  reduction); per-chunk summarization and structured S-R-V (`correlate_facts`)
  both lose; over-focusing hints (0.95) hurts.
- lede has two output surfaces: compact human (markdown/text) for LLM context,
  full JSON (attributes/fact_records/promotion_candidates/search_text) for
  ingest/FTS/metadata-promotion — the JSON path is slice-2 territory.
