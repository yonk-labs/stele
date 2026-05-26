# Stele — Full End-to-End Showcase

Generated: `2026-05-26T23:36:35.475545+00:00`  
Source run: `benchmarks/runs/full-20260526T221249Z` (raw artifacts committed alongside this file)  

**Package versions**: stele-core `0.2.1`  ·  lede `0.4.5`  ·  chunkshop `0.6.1`  ·  pg-raggraph `0.4.0a1`

Every number below is read from a JSON artifact in this run dir; re-run `scripts/run-full-showcase.sh` to reproduce. Deterministic lanes (showcase, recall, long-run) are byte-stable; the LLM-judged lane uses an independent judge model (no self-grading).

## Token reduction · performance · PII

Engines tested: MemoryBackend, SQLiteBackend, PostgresBackend, ClickHouseBackend  ·  workload×engine runs: 20

| Metric | Value |
| --- | ---: |
| Mean prompt-payload reduction | **96.57%** |
| Median / min / max reduction | 97.02% / 93.12% / 98.53% |
| Mean intercept latency | 11.627 ms |
| Mean fetch latency | 2.636 ms |
| Mean search latency | 5.481 ms |
| Concurrency throughput | 23527.144593618206 rows/s |
| **Total PII leakage** | **0** (must be 0) |

## Long-term recall

**Recall benchmark** (answer-bearing span retrieval):

| Metric | Value |
| --- | ---: |
| Retrieval answer accuracy | 1.0 |
| Recall@1 | 0.8 |
| MRR | 0.9 |
| Cases | 5 |

**Long-run matrix** (supersession / as_of / temporal / PII, all engines):

| Metric | Value |
| --- | ---: |
| Total runs | 2625 |
| Retrieval answer accuracy | 0.981 |
| Recall@1 | 0.981 |
| Exact-fetch accuracy | 1.0 |
| Raw-fetch block rate | 1.0 |
| Mean payload reduction | 95.7419% |
| **Total PII leaks** | **0** (must be 0) |

## LLM-judged answer accuracy vs raw context

Answerer: `Intel/Qwen3-Coder-Next-int4-AutoRound` @ `http://192.168.1.193:8000/v1`  
Judge: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` @ `http://192.168.1.133:8000/v1`  

Accuracy and mean tokens per strategy. `digest` = lede summary + facts + top-5 chunks; `raw_fetch` = full-context baseline.

### synthetic

| Strategy | Accuracy | Mean tokens |
| --- | ---: | ---: |
| search_first | 0.8286 | 154.2857 |
| summary_only | 0.7143 | 327.0857 |
| summary_then_search | 0.7714 | 382.9429 |
| adaptive | 0.7714 | 684.0286 |
| iterative | 0.6571 | 803.0286 |
| digest ⭐ | 0.7429 | 2000.4286 |
| raw_fetch | 0.7714 | 8973.6857 |

### longbench

| Strategy | Accuracy | Mean tokens |
| --- | ---: | ---: |
| search_first | 0.5312 | 151.0312 |
| summary_only | 0.4062 | 434.0938 |
| summary_then_search | 0.4375 | 559.5938 |
| adaptive | 0.5 | 4414.9688 |
| iterative | 0.3125 | 755.625 |
| digest ⭐ | 0.5312 | 1626.3438 |
| raw_fetch | 0.5625 | 12843.3125 |

### ragbench

| Strategy | Accuracy | Mean tokens |
| --- | ---: | ---: |
| search_first | 0.3333 | 132.4444 |
| summary_only | 0.7222 | 488.1667 |
| summary_then_search | 0.75 | 558.8889 |
| adaptive | 0.75 | 1235.1667 |
| iterative | 0.5556 | 443.4167 |
| digest ⭐ | 0.8333 | 1547.8889 |
| raw_fetch | 0.7778 | 1591.1944 |

### longmemeval

| Strategy | Accuracy | Mean tokens |
| --- | ---: | ---: |
| search_first | 0.6667 | 59.5833 |
| summary_only | 0.75 | 378.25 |
| summary_then_search | 0.75 | 412.5833 |
| adaptive | 0.75 | 11693.6667 |
| iterative | 0.6667 | 4255.4167 |
| digest ⭐ | 0.75 | 1460.5 |
| raw_fetch | 0.5 | 15404.8333 |

### locomo

| Strategy | Accuracy | Mean tokens |
| --- | ---: | ---: |
| search_first | 0.2778 | 120.5 |
| summary_only | 0.2778 | 450.6667 |
| summary_then_search | 0.2778 | 541.3333 |
| adaptive | 0.4444 | 4421.8889 |
| iterative | 0.2778 | 520.2222 |
| digest ⭐ | 0.5 | 1287.5 |
| raw_fetch | 0.5556 | 10488.0556 |
