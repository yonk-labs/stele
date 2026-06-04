# stele Showcase Benchmark

## TL;DR

Real-world LLM-agent workload simulation for off-prompt tool response storage. Every number in this report is printed from a live run of `benchmarks.showcase`.

**Report schema**: `0.1.0`  
**Run at**: `2026-05-26T22:12:49.726675+00:00`  
**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`  
**Backends tested**: MemoryBackend, SQLiteBackend, PostgresBackend, ClickHouseBackend

## Summary

| Metric | Value |
|---|---|
| Total workload x backend runs | 20 |
| Mean prompt-payload reduction | **96.57%** |
| Median prompt-payload reduction | 97.02% |
| Min / max prompt-payload reduction | 93.12% / 98.53% |
| Mean intercept latency | 11.627 ms |
| Mean fetch latency | 2.636 ms |
| Mean search latency | 5.481 ms |
| Concurrent ingestion throughput | 23527.1 rows/sec |
| PII leakage count | 0 |

## Industry Workload Results

| Workload | Backend | Input | Replacement | Reduction | Intercept | Fetch | Search | Hits |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `legal_contract_qa` | MemoryBackend | 40,960 B | 1,220 B | **97.0%** | 14.70 ms | 0.05 ms | 0.65 ms | 1 |
| `sql_database_exploration` | MemoryBackend | 30,626 B | 451 B | **98.5%** | 4.76 ms | 0.03 ms | 0.46 ms | 1 |
| `log_triage_incident` | MemoryBackend | 64,087 B | 1,221 B | **98.1%** | 7.70 ms | 0.03 ms | 1.35 ms | 1 |
| `json_api_docs_lookup` | MemoryBackend | 30,463 B | 1,189 B | **96.1%** | 8.70 ms | 0.03 ms | 0.40 ms | 1 |
| `code_diff_review` | MemoryBackend | 17,599 B | 1,210 B | **93.1%** | 3.31 ms | 0.02 ms | 0.34 ms | 1 |
| `legal_contract_qa` | SQLiteBackend | 40,960 B | 1,220 B | **97.0%** | 7.94 ms | 0.10 ms | 0.27 ms | 1 |
| `sql_database_exploration` | SQLiteBackend | 30,626 B | 451 B | **98.5%** | 5.12 ms | 0.05 ms | 0.19 ms | 1 |
| `log_triage_incident` | SQLiteBackend | 64,087 B | 1,221 B | **98.1%** | 8.39 ms | 0.07 ms | 0.27 ms | 1 |
| `json_api_docs_lookup` | SQLiteBackend | 30,463 B | 1,189 B | **96.1%** | 8.93 ms | 0.05 ms | 0.16 ms | 1 |
| `code_diff_review` | SQLiteBackend | 17,599 B | 1,210 B | **93.1%** | 3.54 ms | 0.05 ms | 0.16 ms | 1 |
| `legal_contract_qa` | PostgresBackend | 40,960 B | 1,220 B | **97.0%** | 15.02 ms | 1.31 ms | 7.78 ms | 1 |
| `sql_database_exploration` | PostgresBackend | 30,626 B | 451 B | **98.5%** | 9.32 ms | 0.90 ms | 4.01 ms | 1 |
| `log_triage_incident` | PostgresBackend | 64,087 B | 1,221 B | **98.1%** | 14.92 ms | 1.16 ms | 13.43 ms | 1 |
| `json_api_docs_lookup` | PostgresBackend | 30,463 B | 1,189 B | **96.1%** | 13.01 ms | 0.68 ms | 4.64 ms | 1 |
| `code_diff_review` | PostgresBackend | 17,599 B | 1,210 B | **93.1%** | 6.41 ms | 0.31 ms | 4.11 ms | 1 |
| `legal_contract_qa` | ClickHouseBackend | 40,960 B | 1,220 B | **97.0%** | 59.01 ms | 15.72 ms | 20.84 ms | 0 |
| `sql_database_exploration` | ClickHouseBackend | 30,626 B | 451 B | **98.5%** | 10.64 ms | 9.83 ms | 17.67 ms | 0 |
| `log_triage_incident` | ClickHouseBackend | 64,087 B | 1,221 B | **98.1%** | 11.69 ms | 10.05 ms | 11.75 ms | 0 |
| `json_api_docs_lookup` | ClickHouseBackend | 30,463 B | 1,189 B | **96.1%** | 12.64 ms | 7.04 ms | 11.98 ms | 0 |
| `code_diff_review` | ClickHouseBackend | 17,599 B | 1,210 B | **93.1%** | 6.80 ms | 5.24 ms | 9.15 ms | 0 |

## Notes

- The no-container path reports MemoryBackend and SQLiteBackend. When `STELE_PG_DSN` is set, PostgresBackend is included. The JSON/Markdown shape is stable for adding MariaDB, ClickHouse, and pg-raggraph rows.
- This report measures prompt-payload reduction, exact fetch, keyword search hit count, latency, and PII leakage. It does not measure answer accuracy yet.
- Exact fetch is verified during each workload run.
- Search hit counts use the current keyword retriever.
- Broad quality claims require a separate direct-context baseline comparison with >=90% task accuracy, plus Chunkshop-backed chunk retrieval for detail-heavy workloads.
- PII leakage is checked against the model-visible replacement payload.

## Reproducing

```bash
.venv/bin/python -m benchmarks.showcase
```
