# Stele Recall Benchmark

This report measures whether retrieval returns the answer-bearing span. It does not claim model answer quality beyond this deterministic fixture.

**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`

| Metric | Value |
| --- | ---: |
| case_count | 5 |
| direct_context_answer_accuracy | 1.0 |
| retrieval_answer_accuracy | 1.0 |
| recall_at_1 | 0.8 |
| mrr | 0.9 |
| meets_90pct_accuracy_target | True |

| Case | Recall@1 | Answer accuracy | MRR | Top hit chars |
| --- | ---: | ---: | ---: | ---: |
| `ops_root_cause` | 0.0 | 1.0 | 0.5 | 503 |
| `customer_commitment` | 1.0 | 1.0 | 1.0 | 503 |
| `pii_policy` | 1.0 | 1.0 | 1.0 | 503 |
| `backend_choice` | 1.0 | 1.0 | 1.0 | 503 |
| `clickhouse_semantics` | 1.0 | 1.0 | 1.0 | 503 |
