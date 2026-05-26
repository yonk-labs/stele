# Changelog

All notable changes to stele are recorded here. Versions follow semver;
pre-1.0 minor bumps carry new features, patch bumps carry fixes.

## [0.2.0] — 2026-05-26

Integrates the now-feature-complete upstream dependencies and hardens the
benchmark surface. All changes are additive — the `Stele` public contract
(`store`/`fetch`/`search`/`query`/`list`/`delete`/`cleanup_expired`/
`export_jsonl`/`import_jsonl`/`capabilities` + the `memory`/`extract`/`recall`
facades) is unchanged.

### Changed

- **Upstream dependency bump.** `lede` 0.3 → **0.4.5**, `chunkshop`
  0.4.3 → **0.6.1**, `pg-raggraph` 0.3.0a3 → **0.4.0a1** (plus `lede-spacy`
  0.4.5). Upstream defaults are byte-identical; the new search/memory/code and
  retrieval-ladder surfaces are opt-in. Verified byte-safe: `ruff` clean,
  `mypy src` clean (126 files), `pytest` 771 passed; the pg-raggraph graph path
  verified against 0.4.0a1 (4 integration tests pass on a Postgres with
  `vector` + `pg_trgm`).

### Added

- **Benchmark version stamping.** Every benchmark report (showcase, recall,
  runtime, longrun, answer-workflow) now records the package set that produced
  it — `stele-core` + `lede`/`chunkshop`/`pg-raggraph` — in a `versions` block
  (JSON) and a "Package versions" line (Markdown), via `benchmarks/_versions.py`.
- **Separate judge endpoint for the answer-workflow benchmark.**
  `--judge-base-url` / `--judge-api-key` (env `YMS_JUDGE_BASE_URL` /
  `YMS_JUDGE_API_KEY`) let the judge model run on a different OpenAI-compatible
  server than the answerer, avoiding self-grading bias. The report records the
  answer/judge model + endpoint in a `config` block. Defaults to the answer
  endpoint, so single-server runs are unchanged.

### Fixed

- **Stale graph integration tests.** The DSN-gated pg-raggraph revisor tests
  called `search_current`/`search_as_of` without the `supersession_behavior`
  kwarg that became required earlier; updated all four call sites.

### Docs

- Corrected the pg-raggraph retrieval-profile audit against the real 0.4.0a1
  API (`profile=` shapes `result.context` only — orthogonal to `mode`; the
  decision-independent perf lever is `retrieval_strategy="vector_first"`).
  Recorded the `digest_search` build-vs-buy collision (chunkshop
  `summarize_hits` / pg-raggraph `mode="summary"` now ship the same idea).

## [0.1.0] — prior baseline

Sovereign-memory rebuild, phases 1–5 plus the E2E harness: artifact storage,
memory with supersession + `as_of`, deterministic extraction, policy-driven
recall, Chunkshop vector/hybrid indexing across five backends, and the
pg-raggraph-backed living-knowledge `Revisor`. See `docs/current-status.md`
and the per-phase tags (`phase1-memory-supersession` … `phase5-pg-raggraph-living-knowledge`).
