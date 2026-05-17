# Phase 4 — "Make it Real" Evidence

Captured 2026-05-17 in worktree `stele-phase4`, branch
`phase4-chunkshop-indexing`, chunkshop 0.4.3 (PyPI), `STELE_PG_DSN` set,
fastembed `all-MiniLM-L6-v2` (dim 384) cached. Run artifacts live under
`benchmarks/runs/2026-05-17/` (gitignored — paths cited, not committed).

## chunkshop-backed contract tests RUN for real (no false skips)

| Suite | Result | Backends exercised for real |
|---|---|---|
| `tests/contract/test_vector_contract.py` | **6 passed** | memory, sqlite, **postgres** (real fastembed + pgvector) |
| `tests/contract/test_indexing_modes_contract.py` | **9 passed** | skip/sync/async × memory, sqlite, **postgres** |
| `tests/unit/storage/test_chunk_store_sqlite.py` | 7 passed / 1 skip | sqlite real (skip = OptionalDependencyError path only) |
| `tests/unit/storage/test_chunk_store_postgres.py` | 6 passed / 1 skip | postgres real (pgvector) |
| `tests/unit/retrieval/test_hybrid_quality.py` | 1 passed | sqlite real fastembed (DC-003 load-bearing) |

mariadb/clickhouse are DSN-gated skips (no live server here) — gated, not
false chunkshop skips.

## benchmarks.showcase  → `benchmarks/runs/2026-05-17/Showcase.{md,json}`

```
total_workloads: 15
mean_savings_pct: 96.57
median_savings_pct: 97.02
min_savings_pct: 93.12
max_savings_pct: 98.53
mean_intercept_ms: 7.301
mean_fetch_ms: 0.44
mean_search_ms: 2.741
total_pii_leakage_count: 0
```

## benchmarks.recall  → `benchmarks/runs/2026-05-17/Recall.{md,json}`

```
retrieval_answer_accuracy: 1.0
recall_at_1: 0.8
mrr: 0.9
meets_90pct_accuracy_target: True
```

## tests/integration/test_showcase_e2e.py

**2 passed** (full store → intercept → fetch → search e2e).

## benchmarks.answer_workflow — N/A

No OpenAI-compatible judge endpoint configured (`OPENAI_BASE_URL` unset).
Per plan ADDED-B this is documented as N/A; the deterministic benchmarks
above still prove payload reduction, fetch correctness, latency, and zero
PII leakage. Re-run with `scripts/run-answer-workflow-judge.sh` once a
judge endpoint is available.

## DC-003 hybrid quality (real fastembed, 24 held-out pairs)

```
keyword@5 = 0.958   vector@5 = 1.000   hybrid@5 = 1.000   floor = 0.05  → PASS
```
