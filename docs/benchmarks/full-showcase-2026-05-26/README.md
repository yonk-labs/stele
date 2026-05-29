# Full End-to-End Showcase — 2026-05-26

Committed snapshot of a complete `scripts/run-full-showcase.sh` run, kept here
(tracked) because `benchmarks/runs/` is gitignored. Every number in
[`FULL-SHOWCASE-REPORT.md`](FULL-SHOWCASE-REPORT.md) traces to a raw artifact in
this directory.

## Provenance

- **Versions**: stele-core `0.2.1` · lede `0.4.5` · chunkshop `0.6.1` · pg-raggraph `0.4.0a1`
- **Git SHA**: see [`git-sha.txt`](git-sha.txt)
- **Engines**: memory, sqlite, postgres, clickhouse (showcase); memory, sqlite, postgres (longrun)
- **LLM-judged lane**: answerer `Intel/Qwen3-Coder-Next-int4-AutoRound`; judge
  `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` — separate models (no self-grading)
- **Full run log**: [`run.log`](run.log)

## Reproduce

```bash
scripts/run-full-showcase.sh
# knobs: YMS_DATASETS, YMS_ENGINES, YMS_LONGRUN_BACKENDS, YMS_LONGRUN_REPEAT,
#        YMS_SCENARIO_LIMIT, YMS_ANSWER_MODEL/_BASE_URL, YMS_JUDGE_MODEL/_BASE_URL
```

Deterministic lanes (showcase, recall, longrun) are byte-stable. The LLM-judged
lane depends on the two model endpoints; re-running reproduces the pattern, not
bit-identical verdicts.

## Headline results

| Lane | Result |
|---|---|
| Token reduction (4 engines) | **96.57%** mean (93.1–98.5%), **0** PII leaks |
| Performance | intercept 11.6 ms · fetch 2.6 ms · search 5.5 ms · 23.5k rows/s |
| Long-term recall (longrun, 2,625 runs) | 0.981 accuracy, 100% exact-fetch, **0** PII leaks, 95.7% reduction |
| LLM-judged accuracy | `digest` beats full-context on RAGBench (0.83 vs 0.78) and LongMemEval (0.75 vs 0.50), ties within ~3pts at 8–10× fewer tokens on LongBench/LoCoMo |

See the report for the full per-strategy × per-dataset accuracy/token tables.

## Files

- `FULL-SHOWCASE-REPORT.md` — consolidated headline report
- `Showcase.{json,md}` — token reduction / performance / PII, all engines
- `Recall.{json,md}` — answer-bearing-span retrieval (micro; 5 cases)
- `longrun/` — long-term recall matrix: `LongRun.json` (summary + by_kind +
  by_backend + every result) and `results.jsonl` (raw per-scenario)
- `answer-workflow-<dataset>/` — per dataset: `AnswerWorkflow.json`
  (per-strategy aggregates + config), `AnswerWorkflow.md`, and `results.jsonl`
  (raw per-case answers + judge verdicts)
- `Answer-Workflow-CrossBenchmark.{json,md}` — strategy-vs-raw_fetch cross table
- `run.log`, `git-sha.txt` — provenance

## Scope notes

- **ClickHouse** is in the showcase lane but not longrun: the ClickHouse server
  used here had `allow_experimental_vector_similarity_index` disabled, which
  stele's vector indexing requires. Enable it (or use stele's own
  `docker-compose.backends.yml` image) and set
  `YMS_LONGRUN_BACKENDS=memory,sqlite,postgres,clickhouse` to include it.
- **MariaDB** was excluded from this run.
- The Recall micro-benchmark is 5 cases; the **longrun matrix (2,625 runs)** is
  the substantive long-term-recall evidence.
