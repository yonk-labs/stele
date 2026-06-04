# Memory-modes benchmark: usage guide

A pluggable, multi-mode benchmark that tests stele memory **where it diverges
from RAG**, one mode per memory use case. Design rationale and the per-mode
specs live in
[`docs/archive/superpowers/specs/2026-06-02-memory-benchmark-and-blog-workflow-design.md`](../../../docs/archive/superpowers/specs/2026-06-02-memory-benchmark-and-blog-workflow-design.md).
This file is how you run it.

## The one idea

"Memory" is not one job. It is six, across three access patterns, and a single
strategy serves none of them well:

| access pattern | modes | the question |
|---|---|---|
| **similarity-recall** | `fact_recall`, `precedent_recall` | "do I already know this? have I done this before?" |
| **structured-state-lookup** | `resume_task_state` | "where did we leave off? is X done? did we ever build Y?" |
| **enforcement** | `guardrail_adherence`, `skill_adherence`, `best_practice` | "never do X / always do X / consider X" |

Every mode reports its metric **plus token cost** under three conditions:
`no_memory` (floor), `prompt_stuffed` (put everything in the prompt), and
`memory_driven` (recall or look up only what is relevant). The headline is
deterministic for every mode (regex, set-intersection, closed-vocab state, an
id-join), so no result rides on the flaky LLM judge.

## Prerequisites

- **Postgres**: `export STELE_PG_DSN=postgresql://.../db`. Use a throwaway db,
  not your live store (the run writes/purges its own namespaces).
- **LLM endpoints** for modes whose agent-under-test or answerer calls a model
  (everything except `best_practice` and `resume_task_state`'s headline):
  answerer Qwen at `http://192.168.1.193:8000/v1`, judge Gemma at
  `http://192.168.1.133:8000/v1`. Pass `--no-judge` to skip the (optional) judge.
- **`--memory-vector`** additionally needs `chunkshop` + the fastembed model
  (`scripts/chunkshop-setup.sh` prefetches it). Without it, recall is keyword-only.

## Run it

```bash
# one mode, deterministic, fast (no judge):
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele_bench \
  .venv/bin/python -m benchmarks.external.memory_modes.run \
    --modes resume_task_state --per-corpus 12 --no-judge

# all six modes, both corpora, with the vector recall leg on:
STELE_PG_DSN=... .venv/bin/python -m benchmarks.external.memory_modes.run \
  --per-corpus 40 --sources synthetic real_trace --memory-vector --no-judge
```

### Flags

| flag | default | meaning |
|---|---|---|
| `--modes` | all | subset by `name` (e.g. `fact_recall precedent_recall`) |
| `--sources` | `synthetic` | `synthetic` (seeded, CI-safe) and/or `real_trace` (mined from real stele data) |
| `--per-corpus` | 40 | cap on cases per mode per source |
| `--memory-vector` | off | turn on the pgvector recall leg (Postgres); needed for free-text recall |
| `--no-judge` | off | skip the optional LLM judge (every headline is judge-free anyway) |
| `--dsn` | `$STELE_PG_DSN` | Postgres DSN |
| `--out` | `benchmarks/runs/cq-additive` | output dir (additive; never touches MEGA-GRID) |

## The six modes

| mode | source(s) | headline metric (deterministic) | conditions |
|---|---|---|---|
| `fact_recall` | synthetic + real_trace (LoCoMo) | `recall@K` (dia_id join); `exact_match` secondary | no_memory / prompt_stuffed / memory_driven |
| `precedent_recall` | synthetic | `precedent_hit@1/@5`; `triple_recall` | no_memory / prompt_stuffed / memory_driven |
| `resume_task_state` | synthetic | `state_accuracy` (closed 4-way), `false_state` | no_memory / prompt_stuffed / memory_driven |
| `guardrail_adherence` | synthetic + real_trace | `violation_rate` (regex) | no_memory / prompt_stuffed / memory_driven |
| `skill_adherence` | synthetic | `application_rate` (regex) | no_memory / prompt_stuffed / memory_driven |
| `best_practice` | synthetic | `surfaced_recall` (no LLM at all) | no_memory / memory_driven |

`real_trace` is supplied where an honest gold can be mined (LoCoMo for facts, the
real standing rules for guardrails); the other modes return no cases for
`real_trace` until a trace miner lands, and the run logs that it skipped them.

## Read the output

One JSON per run at `benchmarks/runs/cq-additive/multimode-<UTCstamp>.json`:

```jsonc
{
  "modes": ["fact_recall", ...], "memory_vector": true,
  "agg": { "<mode>": { "<source>": { "<condition>": {
      "<headline_metric>": 0.83, "tokens_in": 92, "n": 40 } } } },
  "rows": [ /* one per case x condition, for drill-down */ ]
}
```

What to look at: per mode/source, compare `memory_driven` against
`prompt_stuffed` on the headline metric **and** `tokens_in`. The thesis lands
when memory_driven matches or beats stuffing at a fraction of the tokens.

## Add a mode (no runner change)

Implement the `Mode` protocol in `base.py` (a dataclass-free class with five
attrs plus `corpus` / `populate` / `run_case` / `score`), then append one line
to `registry.py`:

```python
# benchmarks/external/memory_modes/registry.py
MODES = [..., MyNewMode()]
```

The runner iterates `MODES`, the writer stamps `mode.name`, the schema keys on
`mode`. A mode may declare a 2-condition subset (e.g. `best_practice` skips
`prompt_stuffed`); the runner tolerates it. Keep the headline deterministic.

## Honesty rules baked in

- Every cell carries an `n`. Small corpora (the enforcement modes ship 3-5 tasks)
  are directional, not verdicts; scale the corpus before quoting them.
- The LLM judge is never a headline. It is an optional diagnostic column.
- Synthetic guarantees reproducibility; `real_trace` blunts the "authored to
  pass" critique. Results label every number with its source.
- Known caveat: on real LoCoMo, `exact_match` is confounded by date/phrasing
  ("May 7th" vs "7 May 2023"), so `recall@K` is the honest headline for facts.

## See also

- Memory features these modes exercise: [`docs/getting-started/tutorial-sovereign-memory.md`](../../../docs/getting-started/tutorial-sovereign-memory.md), runnable [`scripts/demo-cq-memory.sh`](../../../scripts/demo-cq-memory.sh).
- Why memory is six problems: the pillar post `~/blogs/06-02-2026-six-memories-why-memory-is-hard.md`.
- Design + per-mode rationale: the spec linked at the top.
