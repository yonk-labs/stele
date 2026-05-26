# Stele Long-Run Benchmark

This is the broad deterministic scenario lane. It is still local and deterministic; external datasets such as LongMemEval and RAGBench remain separate adapters.

**Supersession mode:** ENABLED (set `STELE_SUPERSESSION_ENABLED=0` to run the no-supersession baseline)

**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`

| Metric | Value |
| --- | ---: |
| run_id | 20260526T221250Z-9552d868 |
| scenario_count | 35 |
| backend_count | 3 |
| repeat | 25 |
| content_multiplier | 8 |
| supersession_enabled | True |
| total_runs | 2625 |
| mean_payload_reduction_pct | 95.7419 |
| retrieval_answer_accuracy | 0.981 |
| direct_context_answer_accuracy | 1.0 |
| recall_at_1 | 0.981 |
| mrr | 0.981 |
| total_pii_leaks | 0 |
| exact_fetch_accuracy | 1.0 |
| raw_fetch_block_rate | 1.0 |
| mean_intercept_ms | 91.2898 |
| mean_fetch_ms | 2.2328 |
| mean_search_ms | 3.6536 |
| mean_query_ms | 9.4086 |

## By Backend

| Backend | Runs | Accuracy | R@1 | MRR | PII leaks |
| --- | ---: | ---: | ---: | ---: | ---: |
| MemoryBackend | 875 | 1.0 | 1.0 | 1.0 | 0 |
| PostgresBackend | 875 | 0.9714 | 0.9714 | 0.9714 | 0 |
| SqliteBackend | 875 | 0.9714 | 0.9714 | 0.9714 | 0 |

## By Scenario Kind

| Kind | Runs | Accuracy | R@1 | MRR | PII leaks |
| --- | ---: | ---: | ---: | ---: | ---: |
| long_memory | 375 | 1.0 | 1.0 | 1.0 | 0 |
| pii | 375 | 1.0 | 1.0 | 1.0 | 0 |
| retrieval | 450 | 1.0 | 1.0 | 1.0 | 0 |
| temporal | 300 | 1.0 | 1.0 | 1.0 | 0 |
| tool_output | 1125 | 0.9556 | 0.9556 | 0.9556 | 0 |
