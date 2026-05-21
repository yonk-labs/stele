# LongBench Benchmark — Stele Recipe

**Source:** [`THUDM/LongBench`](https://huggingface.co/datasets/THUDM/LongBench) ·
[paper, ACL 2024](https://aclanthology.org/2024.acl-long.172/) ·
`data.zip` (~110 MB, 21 tasks across 6 families)

## What the benchmark is

LongBench is a **bilingual long-context benchmark** with 21 tasks across 6
families: single-doc QA, multi-doc QA, summarization, few-shot learning,
synthetic tasks, code completion. Each record packs the question's
context into a single long input (8k–32k tokens).

## Data architecture

```yaml
input:    "Which case was brought to court first Miller v. California or Gates v. Collier ?"
context:  "Passage 1:\nTrusty system (prison)\nThe \"trusty system\"...\n\nPassage 2:\n..."
answers:  ["Miller v. California"]
length:   8616
dataset:  "hotpotqa"
all_classes: null
_id:      "..."
```

- **Atoms:** passages within `context`, delimited by `Passage N:\n` markers.
- **Volume per record:** 4–10 passages, ~50–200 words each, totalling
  8k–32k characters of context.
- **`dataset` field:** identifies which of the 21 tasks the record belongs
  to.
- **`answers` is a list** of acceptable golds (often multi-token spans
  with paraphrase tolerance).

## Subsets the Stele harness runs

Only the **QA-family** subset is scoreable as retrieval recall:

| Task | Family | Why |
|---|---|---|
| `hotpotqa` | multi-doc QA | 4-doc multi-hop, classic retrieval shape |
| `2wikimqa` | multi-doc QA | 4-doc Wikipedia multi-hop |
| `musique` | multi-doc QA | 2–4-hop, hardest LongBench QA task |
| `multifieldqa_en` | single-doc QA | 1-doc, mixed domains (Wikipedia, news, papers) |

Summarization, code completion, synthetic, and few-shot tasks are
**intentionally skipped** — answer-span recall isn't the right metric for
them; they need an answer-LLM.

## What it expects

| Aspect | Bench expects |
|---|---|
| QA tasks | F1 / exact-match on the answer span |
| Summarization | ROUGE |
| Code | edit distance |
| Synthetic | task-specific accuracy |

Stele's lane scores **answer-span recall@k over the split passages** —
deterministic, no LLM, comparable across the four QA tasks.

## How Stele processes it

```python
for rec in iter_longbench(task, limit):
    passages = _split_passages(rec["context"])   # split on "Passage N:"
    for j, p in enumerate(passages):
        s.memory.add(text=p[:2000], kind="fact",
                     source_refs=[f"stele://longbench/{task}/{i}/p{j}"],
                     scope=scope)
    rr = s.recall(query=rec["input"], scope=scope, max_memory_hits=k)
    # any(gold answer in any recalled context)
```

## Recipe — `profile: hybrid-best`

| Knob | Value | Why |
|---|---|---|
| `backend.type` | `sqlite` | fits the per-record + per-task scale |
| `indexing.mode` | `sync` | inline indexing |
| `indexing.provider` | `chunkshop` | enables vector + hybrid |
| Passage segmentation | `Passage N:\n` regex split | preserves the dataset's own chunking |
| `indexing.chunker` | `fixed_overlap` (220w / 60w) | passages are already ~paragraph-sized; sub-chunking handles the longer ones |
| Embedder | fastembed `all-MiniLM-L6-v2` | works across Wikipedia/news/papers |
| `retrieval.default_mode` | `hybrid` | named-entity lookups + paraphrase-tolerant ranking |
| `recall(max_memory_hits)` | **30** | 4-passage docs × ~3 distractor passages per record |
| Metadata | scope=`longbench-<task>`; refs=`stele://longbench/<task>/<i>/p<j>` | per-task scope keeps cross-record leakage out |

## Measured numbers

| Task | Default (keyword, k=20) | hybrid-best (k=30) | Delta |
|---|---:|---:|---:|
| `hotpotqa` | 70.0% | **93.3%** | +23.3 |
| `2wikimqa` | 52.5% | **96.7%** | +44.2 |
| `musique` | 47.5% | **80.0%** | +32.5 |
| `multifieldqa_en` | 77.5% | 70.0% | **−7.5** |

### The `multifieldqa_en` anomaly

Single-doc QA actually got worse under hybrid. Reason: this task has ONE
long single-doc context where the answer span and the question often
share exact tokens. Vector ranking dilutes the keyword signal by mixing
in semantically-related-but-wrong passages. For single-doc QA the right
recipe is **keyword-heavy hybrid** (`hybrid_weights={"keyword":0.7,
"vector":0.3}` or pure keyword at higher k) — or simply use the keyword
profile for this task.

This is the "for this shape, do x,y,z" point: there isn't one universal
recipe. `hybrid-best` is the right *default*; `multifieldqa_en`
specifically wants `keyword-heavy` or pure-keyword.

## What it does NOT do

- **Summarization / code / synthetic tasks** are intentionally skipped.
  Stele isn't an answer-LLM; the answer-workflow lane (§4 of the
  showcase report) is the right surface for those, against a model
  endpoint — not wired against LongBench inputs today.
- **Per-passage metadata** like passage type / source could improve
  filtering on the multi-doc QA tasks (`hotpotqa`, `2wikimqa`); current
  refs carry only positional identifiers.

## How to reproduce

```bash
.venv/bin/python -m benchmarks.external \
    --longbench-per-task 30 \
    --profile hybrid-best
```

Output: `benchmarks/runs/<date>/External-hybrid-best.{md,json}`.
