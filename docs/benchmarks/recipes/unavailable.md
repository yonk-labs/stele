# Unavailable Benchmarks — Architecture, Expectations, Unblock

Two benchmarks the plan calls for are not runnable in this environment.
Loaders raise `DatasetUnavailable` with exact unblock instructions; the
harness records them as UNAVAILABLE rather than fabricating numbers.

---

## CRAG (Meta KDD Cup 2024)

**Source:** [`Meta-KDDCup-24/crag-task-1-and-2`](https://huggingface.co/datasets/Meta-KDDCup-24/crag-task-1-and-2)
([NeurIPS 2024 paper](https://papers.nips.cc/paper_files/paper/2024/hash/1435d2d0fca85a84d83ddcb754f58c29-Abstract-Datasets_and_Benchmarks_Track.html))

### What it is

A **factual QA benchmark with changing / open-world data and mock APIs**.
Tests:
- handling questions whose answers change over time
- abstaining when the answer would be stale
- using tool/API calls correctly when the corpus lacks the answer

### Data architecture (per the task spec)

```yaml
query:        "..."
query_time:   "2024-03-15T12:00:00Z"  # answer correctness depends on this
answer:       "..."
missing_info_handling: bool
api_calls_required: [...]
domain:       "movie | sports | open | encyclopedia | finance"
question_type:"simple_w_condition | comparison | aggregation | post-processing | ..."
```

- Multi-GB total size.
- License-gated on HuggingFace: requires authenticated download + license
  acceptance.

### What it expects

Exact-match / F1 on the answer, **plus** correct missing-info handling
behavior and (for task-2/3) correct mock-API call sequences. Headline
metric is overall accuracy across the eight question types.

### Why it's blocked here

```
HTTP 401 Invalid username or password
```

Anonymous HuggingFace fetches return 401 on this dataset. The data is
multi-GB; downloading via `huggingface_hub` requires:
1. A HuggingFace token (login)
2. Accepting the dataset license on the HF web UI
3. ~30 min download time

### Stele recipe (when unblocked)

| Knob | Value | Why |
|---|---|---|
| `backend.type` | `postgres` | CRAG has a fixed corpus + per-query mock APIs — postgres handles the persistent corpus + per-query namespace cleanly |
| `indexing.mode` | `async` | corpus is large; async indexing decouples ingest from query |
| `indexing.provider` | `chunkshop` | hybrid needed for paraphrased queries |
| `retrieval.default_mode` | `hybrid` | both lexical (named entities) and semantic |
| `recall(max_memory_hits)` | **40** | CRAG question types include aggregation/comparison — wider net |
| **`Memory.add(supersedes=...)`** | yes | CRAG explicitly tests temporal staleness — Stele's supersession primitive maps directly |
| `as_of` recall | yes | `query_time` field → pass through as `RecallRequest.as_of` |
| Metadata | per-fact `effective_from` / `effective_to` via custom kind/refs | enables the time-travel queries that drive CRAG's correctness |

### Unblock path

```bash
# 1. Login to HuggingFace
hf auth login

# 2. Accept the dataset license at:
#    https://huggingface.co/datasets/Meta-KDDCup-24/crag-task-1-and-2

# 3. Download
hf download Meta-KDDCup-24/crag-task-1-and-2 \
    --repo-type dataset \
    --local-dir benchmarks/.cache/crag

# 4. Symlink into the expected loader path
ln -s ../crag/crag_task_1_dev_v4_release.jsonl.bz2 \
    benchmarks/.cache/crag_task1.jsonl.bz2

# 5. Run
.venv/bin/python -m benchmarks.external --profile hybrid-best
```

The loader at `benchmarks/external/loaders.py::load_crag` is ready to
consume the file the moment it lands at the documented cache path.

---

## AgentLongMemEval

**Source:** referenced in agent-memory literature; no openly-resolvable
release locatable from this sandbox.

### What it is (per the literature)

An extension of LongMemEval focused on **agent** (multi-tool, multi-turn)
long-term memory rather than chat-assistant memory. Same five core
abilities (extraction / multi-session reasoning / temporal / knowledge
update / abstention) but with tool-use interleaved into the sessions.

### Data architecture (expected, by analogy with LongMemEval)

```yaml
question_id:        "..."
question:           "..."
answer:             "..."
question_type:      "..."
haystack_sessions: [...]   # but now sessions contain tool calls + results
answer_session_ids: [...]
```

### Why it's blocked here

The loader couldn't locate an openly-resolvable downloadable release from
this environment. There is no `Meta-KDDCup-24`-style HF dataset path
that resolves to AgentLongMemEval directly.

### Stele recipe (when unblocked)

Same shape as `longmemeval-best` (see [`longmemeval.md`](longmemeval.md))
with one addition:

| Extra knob | Value | Why |
|---|---|---|
| Tool-output ingest | route tool-call results through `Stele.stash_tool_result(...)` | agent memory should hold tool I/O at full fidelity; that's Stele's headline value |
| Per-turn metadata | `turn_kind: "tool_call" \| "tool_result" \| "agent_msg" \| "user_msg"` | enables filtered recall (e.g., "what did the search tool return last?") |
| `extraction.from_messages` | over assistant + user turns only | skip tool I/O at the extraction layer — keep it artifact-side |

### Unblock path

Drop the official JSON file (when located) at:

```
benchmarks/.cache/agentlongmemeval.json
```

Same record shape as LongMemEval (`question` / `answer` /
`haystack_sessions` / `answer_session_ids`). Once present, the loader's
`load_agentlongmemeval` will return the records and the harness lane will
run automatically.

---

## Integrity rule

The harness never fabricates numbers for these. Per
`benchmarks/external/loaders.py` docstring: "every dataset here is the
REAL published dataset, cached under benchmarks/.cache/ (gitignored). No
synthetic substitution." Both UNAVAILABLE entries surface in the report
with the exact reason string — auditable, never silently dropped.
