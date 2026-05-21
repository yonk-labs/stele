# LongMemEval-S Benchmark — Stele Recipe

**Source:** [`xiaowu0162/longmemeval`](https://github.com/xiaowu0162/LongMemEval) ·
[paper arXiv 2410.10813 (ICLR 2025)](https://arxiv.org/abs/2410.10813) ·
file `longmemeval_s` (~266 MB JSON)

## What the benchmark is

LongMemEval evaluates **five core long-term-memory abilities** of chat
assistants: information extraction, multi-session reasoning, temporal
reasoning, knowledge updates, and abstention. 500 questions across the
five categories. The "-S" variant uses small haystacks (~50k tokens per
question) — still large by retrieval standards.

## Data architecture

```yaml
question_id: "8b...3a_singlehop"  # _abs suffix = abstention question
question: "When did I last switch jobs?"
answer: "March 2023"
question_type: "single_hop" | "multi_hop" | "temporal" | "knowledge_update" | "implicit"
haystack_sessions:
  - [ {role: "user", content: "..."},
      {role: "assistant", content: "..."},
      ...  ]   # one session, many turns
  - [ ...session 2... ]
  - ...        # typically 30-50 sessions per question
answer_session_ids: ["sess_3", "sess_12"]
```

- **Atoms:** message turns within haystack sessions.
- **Volume per question:** thousands of turns across 30–50 sessions.
- **Q is independent per record** — no shared corpus. Each record gets
  its own Stele namespace.

## What it expects

| Aspect | Bench expects |
|---|---|
| Retrieval | recall@K over many short turns |
| QA accuracy | LLM-judged QA across the 5 categories |
| Temporal | does the recall surface the right session/date |
| Abstention | does NOT answer the `_abs`-suffixed questions |

Published vendor headline numbers (LLM-judged QA):
- Mastra Observational Memory (gpt-5-mini): **94.87%**
- Mem0 (Apr 2026): **94.4%** at 6,787 tokens/query
- Supermemory (production): ~85% (LLM-judged QA)
- MemPalace raw (no LLM): 96.6% **R@5 retrieval recall** (not QA)
- Hindsight: 91.4% (unverified metric)

## How Stele processes it

```python
for rec in iter_longmemeval_s(limit):
    s = _stele(config)
    scope = MemoryScope(namespace="lme")
    for sess in rec["haystack_sessions"]:
        for turn in sess:
            s.memory.add(text=f"[{turn['role']}] {turn['content']}"[:1500],
                         kind="fact", source_refs=["stele://lme/turn"],
                         scope=scope)
    rr = s.recall(query=rec["question"], scope=scope, max_memory_hits=k)
```

One Stele instance per question (each record is independent). Hundreds to
thousands of turns indexed per record; this is where keyword-only
collapses (20.0% answer-span at the 2026-05-18 sweep).

## Recipe — `profile: hybrid-best`

| Knob | Value | Why |
|---|---|---|
| `backend.type` | `sqlite` | per-question fresh instance — sqlite fits |
| `indexing.mode` | `sync` | inline; tractable at the per-question scale |
| `indexing.provider` | `chunkshop` | unlocks vector + hybrid |
| `indexing.chunker` | `fixed_overlap` (220w / 60w) | turns are very short; overlap matters less here but doesn't hurt |
| Embedder | fastembed `all-MiniLM-L6-v2` (384-d) | semantic match across paraphrased turns is the lever |
| `retrieval.default_mode` | `hybrid` | exact tokens for named entities; vector for paraphrased recall |
| `recall(max_memory_hits)` | **30** | sessions × turns is large but k=30 surfaces enough |
| Metadata | scope=`lme`; refs=`stele://lme/turn` | per-question isolation |

### Why this works on LME

LME's long-haystack shape is exactly what vector retrieval is for. Queries
ask about *facts mentioned in passing* across sessions — keyword search
typically misses paraphrased mentions ("changed jobs" vs "started at X").
Adding vector ranking and RRF fusion captures both.

## Measured numbers

| Run | n | Answer-span |
|---|---:|---:|
| Default (keyword, k=20) | 30 | 40.0% |
| Today (`hybrid-best`, k=30) | 25 | **88.0%** |
| 2026-05-18 (hybrid, k=30) | 10 | 90.0% |
| 2026-05-18 (graph, subset) | 3 | 100% |

The 88% number is the high-water mark from the published catalog. To
push toward 95%+ (Mastra / Mem0 territory) needs an answer-LLM lane —
the §4 `answer_workflow` mechanism, re-aimed at LME inputs. That's the
documented gap.

## What it does NOT do (yet)

- **Per-session metadata.** LME records session boundaries; we currently
  collapse all turns under one namespace with a single shared ref
  (`stele://lme/turn`). A richer metadata payload
  (`stele://lme/sess_<i>/turn_<j>`) would feed temporal/session-filtered
  recall (the `temporal` and `knowledge_update` categories).
- **Knowledge-update handling.** LME's `knowledge_update` category tests
  whether a *newer* fact supersedes an older one. Stele's `Memory.add(
  supersedes=[old_id])` is the right primitive but not wired into the LME
  ingest path. With supersession + `as_of`, the `knowledge_update`
  category should improve markedly.
- **Abstention scoring.** Current LME run has 0 `_abs` questions in the
  N=25–30 sample (they're rare in the head of the file). Full sweep
  would catch them; abstention metric is implemented and ready.

## How to reproduce

```bash
.venv/bin/python -m benchmarks.external \
    --lme-questions 25 \
    --profile hybrid-best
```

Output: `benchmarks/runs/<date>/External-hybrid-best.{md,json}`.
