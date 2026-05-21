# LoCoMo Benchmark — Stele Recipe

**Source:** [`snap-research/locomo`](https://github.com/snap-research/locomo) ·
[paper arXiv 2402.17753](https://arxiv.org/abs/2402.17753) ·
file `locomo10.json` (2.7 MB)

## What the benchmark is

LoCoMo measures very-long-term **conversational memory**. Each sample is a
multi-session dialogue between two personas, accumulated over weeks; the
benchmark asks ~150–250 questions per sample about facts, events, temporal
relations, and consistency across sessions.

## Data architecture

Per sample (10 in `locomo10.json`):

```yaml
sample_id: "conv-XX"
conversation:
  session_1: [{dia_id, speaker, text, ...}, ...]
  session_2: [...]
  ...   # often 20+ sessions, weeks of dialogue
  session_summary: {session_N: "prose summary"}   # benchmark-provided
  observation: {session_N: {speaker: [[fact, dia_id], ...]}}  # CEILING — do not use as Stele input
qa:
  - {question, answer, category, evidence: [dia_id, ...]}
  - ...
```

- **Atoms:** dialogue turns (`dia_id`-keyed), typically 8–25 words each.
- **Volume:** ~300–1000 turns per sample.
- **`observation`/`session_summary`:** the *benchmark authors'* distilled
  facts; using them as input measures a CEILING, not Stele's work. Stele
  must produce its own distillation via `Stele.extract`.
- **`category`:** 1=single-hop, 2=multi-hop, 3=temporal, 4=open-domain,
  5=adversarial (abstention).

## What it expects

| Aspect | Bench expects |
|---|---|
| Retrieval | recall@K over turns / extracted facts |
| QA accuracy | LLM-judged QA (J score in Zep's eval; question accuracy in others) |
| Temporal reasoning | dates / sequences / "before/after" correctness |
| Abstention (category 5) | does NOT surface the adversarial answer |

Published vendor headline numbers (LLM-judged QA):
- Mem0 (Apr 2026) **92.5** at 6,956 tokens/query
- Zep (corrected 2025) **75.14%** on gpt-4o
- Letta (gpt-4o-mini, filesystem) **74.0%**
- MemPalace hybrid v5 (no rerank) **88.9%** Top-10 R@10 *(retrieval recall, not QA)*

## How Stele processes it

Two-stage pipeline:

1. **Ingest** — for each session, route `messages = [{role, content}, ...]`
   through `Stele.extract.from_messages(messages, scope)`. Setting
   `extraction.retain_message_text=True` emits BOTH (a) distilled fact
   atoms and (b) verbatim turn atoms — both retrievable. Each carries
   `source_refs=["stele://locomo/<sid>/<dia_id>"]`.
2. **Recall** — for each question, call
   `s.recall(question, scope, max_memory_hits=80)`. The hybrid retrieval
   mode runs keyword + vector + RRF fusion; the answer-span scorer checks
   whether the recalled context contains the gold answer.

## Recipe — `profile: locomo-best`

| Knob | Value | Why |
|---|---|---|
| `backend.type` | `sqlite` | chunkshop integration; postgres works equivalently |
| `indexing.mode` | `sync` | inline indexing — small dataset, sync is fine |
| `indexing.provider` | `chunkshop` | enables vector + hybrid |
| `indexing.chunker` | `fixed_overlap` (220w / 60w overlap) | turns are short — overlap dominates |
| Embedder | fastembed `all-MiniLM-L6-v2` (384-d) | chunkshop default — semantic match for distilled facts |
| `retrieval.default_mode` | `hybrid` | keyword catches exact tokens; vector catches semantic; RRF fuses |
| `recall(max_memory_hits)` | **80** | LoCoMo has 300–1000 atoms / sample — k=20 starves it |
| `extraction.retain_message_text` | `True` | keep verbatim turns alongside distilled atoms |
| Metadata strategy | scope=`locomo_<sample_id>`; refs=`stele://locomo/<sid>/<dia_id>` | per-sample isolation + per-turn provenance |

### What it does NOT do (yet)

- **No graph engine.** The 2026-05-18 analysis showed graph at 42.5%
  answer-span on raw turns — worse than hybrid. The graph engine helps
  *evidence ranking* once chunkshop SP-A's `ConsolidationChunker` emits
  typed SPO triples; without that, the graph adds latency without lifting
  retrieval recall on LoCoMo.
- **No chunkshop SP-A `ConsolidationChunker`.** This is the next jump.
  The episode-framer would group turns by time-gap + role boundary, the
  consolidator would emit `{summary, facts: [...]}` per episode, and
  pg-raggraph's memory-bridge would write typed relationships. Expected
  lift to LoCoMo answer-span: 67.6% → 75–80% range (un-measured;
  requires wiring described in
  `/home/yonk/yonk-tools/chunkshop/docs/superpowers/specs/2026-05-19-chunkshop-memory-primitives-sp-a-design.md`).
- **No reranker over the top-k.** Cross-encoder reranking is the standard
  next lift in retrieval-recall benchmarks.

## Measured numbers

| Run | Answer-span | Evidence | Abstention not-misled | Notes |
|---|---:|---:|---:|---|
| Default (keyword, k=20, raw turns) | 44.0% | 34.3% | 44.3% | 5 samples / 762 q |
| `locomo-best` (today, k=80, extract+hybrid) | **67.6%** | **74.8%** | 12.7% | 5 samples / 762 q |
| 2026-05-18 (hybrid, raw turns, k=40) | 62.9% | 77.9% | — | 5 samples / 385 ans |
| 2026-05-18 (Stele.extract → hybrid, k=40) | 65.5% | n/a | — | 5 samples / 385 ans |
| Ceiling (benchmark `observation` field, hybrid) | 86.8% | 82.3% | — | NOT Stele's work; reference only |

## Abstention regression at deeper k (honest)

`locomo-best` lowered abstention-not-misled from 44.3% to 12.7%. Deeper k
surfaces more candidate turns; some adversarial questions trigger keyword
matches against legitimate (but unrelated) turns. To recover abstention
without losing answer-span recall, the right lever is a confidence floor
on the recall result (`AdaptiveStrategy.confidence_floor`, already in
`stele.recall`) — not currently exposed in the external harness path.

## How to reproduce

```bash
.venv/bin/python -m benchmarks.external \
    --locomo-samples 5 \
    --profile locomo-best
```

Output: `benchmarks/runs/<date>/External-locomo-best.{md,json}`.
