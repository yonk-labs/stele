# MultiHop-RAG Benchmark — Stele Recipe

**Source:** [`yixuantt/MultiHop-RAG`](https://github.com/yixuantt/MultiHop-RAG) ·
[paper arXiv 2401.15391](https://arxiv.org/abs/2401.15391) ·
files `MultiHopRAG.json` (~5 MB) + `corpus.json` (~7 MB)

## What the benchmark is

MultiHop-RAG measures retrieval for **multi-hop questions** over a fixed
corpus of news articles. Each query requires the system to find 2–4
supporting facts spread across different documents and synthesize them
into a single answer.

## Data architecture

```yaml
corpus:  # 609 news articles
  - {title, body, url, source, ...}
queries:
  - question: "Which company that acquired X also reported Y?"
    answer: "..."
    question_type: "inference_query" | "comparison_query" |
                   "temporal_query" | "null_query"   # null = abstention
    evidence_list:
      - {title: "<doc title>", fact: "<span>", source, ...}
      - ...   # 2-4 evidence docs per question
```

- **Atoms:** full news articles (avg ~1500 words). Multi-paragraph.
- **Volume:** 609 docs / 2255 queries (28 are `null_query` for abstention).
- **Evidence:** linked by `title` — gold doc identity is exact.
- **Vocabulary mismatch:** queries often paraphrase article wording —
  keyword alone is weak; semantic similarity is required.

## What it expects

| Aspect | Bench expects |
|---|---|
| Retrieval | Hits@K, Recall@K, MAP, MRR over the 609-doc corpus |
| Answer correctness | exact-match / F1 (when run with an LLM) |
| Multi-hop reasoning | how often ALL evidence docs surface in top-K |
| Abstention (null_query) | does NOT produce a confident answer |

The paper's own headline finding: even GPT-4 with ground-truth evidence
reaches only **0.89** answer accuracy — multi-hop is genuinely hard.

## How Stele processes it

```python
for i, doc in enumerate(corpus):
    body = (doc["title"] + ". " + doc["body"])[:doc_body_chars]
    s.memory.add(text=body, kind="fact",
                 source_refs=[f"stele://mhr/doc-{i}"], scope=scope)
# title-to-ref mapping captured so evidence recall is checkable
for q in queries:
    rr = s.recall(query=q["query"], scope=scope, max_memory_hits=k)
    # score answer-span hit on text + evidence-doc hit on citations.reference
```

For MHR the meaningful chunking happens at **ingest time** — long articles
get chunked by chunkshop internally before vector indexing. Stele just
hands the body in; chunkshop produces the chunks.

## Recipe — `profile: hybrid-best`

| Knob | Value | Why |
|---|---|---|
| `backend.type` | `sqlite` | adequate for 609 docs; postgres works equivalently at scale |
| `indexing.mode` | `sync` | inline; corpus is tiny by RAG standards |
| `indexing.provider` | `chunkshop` | enables vector + RRF hybrid |
| `indexing.chunker` | `fixed_overlap` (220w / 60w) | balances paragraph cohesion with retrieval granularity |
| Embedder | fastembed `all-MiniLM-L6-v2` (384-d) | strong baseline for news / wikipedia-style text |
| `retrieval.default_mode` | `hybrid` | vocabulary mismatch needs vector; named-entity matching needs keyword |
| `hybrid_method` | `rrf` (default k=60) | RRF dominates weighted-sum on this shape |
| `recall(max_memory_hits)` | **30** | 4-evidence-doc questions × ~3 distractors ≈ k=30 is the right band |
| `doc_body_chars` | **4000+** | the 1500-char default truncates answer-bearing text; bench-rigged-against-Stele unless raised |
| Metadata | scope=`mhr`; refs=`stele://mhr/doc-<i>` keyed to corpus index | enables evidence-doc recall scoring |

### Why this beats keyword

- **Keyword** finds answer text via exact tokens — works when the question
  shares vocabulary with the article (95.1% answer-span at full k=30).
- **Hybrid** wins on **evidence recall**: 17.1% → 100%. Keyword surfaces
  *an* answer-bearing doc but not always the labelled gold doc; vector
  ranking fixes that.

## Measured numbers

| Run | Engine | n | Answer-span | Evidence |
|---|---|---:|---:|---:|
| 2026-05-18 (full 609-doc, k=30) | keyword | 41 ans | **95.1%** | 17.1% |
| 2026-05-18 (full 609-doc, k=30) | hybrid | 41 ans | 78.0% | **100%** |
| Today (`default-keyword`, 200q, k=20, 1500c trunc) | keyword | 172 ans | 47.7% | 18.6% |
| Today mini-bakeoff (200 docs, 30q, k=20, 4000c) | keyword | 25 ans | 84.0% | 28.0% |
| Today mini-bakeoff (200 docs, 30q, k=20, 4000c) | hybrid | 25 ans | 80.0% | **72.0%** |
| Today (`hybrid-best`, 150q, k=30, 4000c) | hybrid | (see external report) | (see) | (see) |

The 47.7% number in the all-keyword default sweep is held back by the
1500-char truncation (a guardrail from earlier work that's now harmful for
MHR specifically). The mini-bakeoff at 4000 chars shows the real ceiling.

## What it does NOT do (yet)

- **Multi-hop decomposition** (retrieve → expand entities → re-recall).
  This is the standard next lift for the residual hard MHR cases. Not
  wired in Stele today.
- **Reranker over top-k.** Cross-encoder reranking lifts gold-doc precision
  meaningfully on this benchmark; not in the Stele path today.
- **Doc-level metadata signals** (source, date, entity overlap). MHR
  evidence has these fields; Stele's `source_refs` carries only the
  per-doc identifier today. A richer metadata payload (date / entities /
  source) would feed a metadata-filtered recall pass.

## How to reproduce

```bash
.venv/bin/python -m benchmarks.external \
    --mhr-queries 200 \
    --profile hybrid-best
```

Output: `benchmarks/runs/<date>/External-hybrid-best.{md,json}`.
