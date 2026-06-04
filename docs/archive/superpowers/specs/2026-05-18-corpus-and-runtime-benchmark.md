---
title: 100-Doc Corpus + Runtime Benchmark (Task E)
created: 2026-05-18
status: evidence — corpus, living-knowledge/tool-call/PII tests, T-RAM-011 benchmark
branch: phase6-7-runtime-working-memory (off main @ 01cb971) — NOT merged
---

# Corpus + Runtime Benchmark

## Deterministic corpus

`benchmarks/corpus.py::sample_corpus(n=100)` — 100 docs, no randomness
(same output every run), spanning 7 lanes: versioned_docs, retracted_claim,
policy_update, account_state, pii_heavy, tool_output, plain. Each doc carries
a known answer-bearing `fact` (PII-free), optional raw `pii` that MUST be
scrubbed, version/supersedes/retract flags.

## Tests (run on memory backend — real CI gates, not skipped)

`tests/integration/test_corpus.py`:
- `test_corpus_shape` — 100 unique docs, all 7 lanes.
- `test_pii_never_survives_store_or_recall` — every PII doc: raw PII absent
  from scrubbed `fetch` content AND absent from `recall().context`
  (leakage == 0).
- `test_tool_call_capture_loop_over_corpus` — tool_output docs through
  `SteleAgentSession`: artifacts + WorkGraph nodes created, packed context
  ref-backed, PII absent from pack + resume.
- `test_living_knowledge_memory_layer_over_corpus` — supersede → current
  hides old / `as_of` recovers it; `memory.retract` flips status (backend-
  agnostic; no pg-raggraph needed).
- `test_corpus_is_deterministic` — corpus stable across runs.

`tests/integration/test_runtime_benchmark.py` — benchmark invariants:
`pii_leakage_count == 0`, `context_pack_deterministic`, `resume_success`,
reduction > 0; numeric metrics identical across runs.

## Benchmark (T-RAM-011 / Spec-9)

`benchmarks/runtime.py` (`stele-runtime-bench`) runs the loop over the 100-doc
corpus and emits `benchmarks/runs/<date>/Runtime.{json,md}`. Reference run
(100 docs, memory backend, deterministic):

| Metric | Value |
| --- | --- |
| input_token_reduction_pct | 94.1 |
| avg_packed_context_tokens | 289.4 (raw transcript 4916) |
| answer_bearing_ref_recall_pct | 89.0 |
| false_recall_count | 11 |
| pii_leakage_count | **0** |
| resume_success | true |
| context_pack_deterministic | true |
| capture_latency_ms / pack_latency_ms | 161.5 / 35.3 |

Benchmark-evidence rule: any public context-compression claim must cite this
generated report (T-RAM-011 gate). The existing `stele-showcase` /
`stele-recall` benchmarks are unchanged and remain green via
`tests/benchmarks_smoke/`.

## Note

Living-knowledge over the corpus is proven at the **memory layer**
(backend-agnostic). The pg-raggraph `graph_search` lane is proven separately
by the Phase 5 e2e bar (`make -C deploy e2e-graph`, on `main`).
