# RAGBench Benchmark — Stele Recipe

**Source:** [`galileo-ai/ragbench`](https://huggingface.co/datasets/galileo-ai/ragbench) ·
[paper arXiv 2407.11005](https://arxiv.org/abs/2407.11005) ·
12 subsets × 3 splits = 36 parquet files (~MBs each)

## What the benchmark is

RAGBench is a 100k-example **industry-grade RAG benchmark** spanning 5
domains. The paper introduces the **TRACe evaluation framework** —
explainable, actionable RAG metrics: faithfulness, relevance, utilization,
completeness.

## Data architecture

```yaml
id:        "5abe65e2..."
question:  "Which university did one of the key figures in..."
documents: [str, str, str, str]    # 1–N supporting documents
response:  "One of the key figures... played college basketball at Duke..."
generation_model_name: "gpt-4"     # who produced `response`
annotating_model_name: "gpt-4"     # who scored the TRACe annotations
dataset_name: "hotpotqa"
documents_sentences: [[[str, ...], ...], ...]   # sentence-level breakdown
response_sentences:   [[str, ...], ...]
sentence_support_information: [...]
adherence_score:           true
overall_supported_explanation: "..."
relevance_explanation:         "..."
all_relevant_sentence_keys:    [...]
all_utilized_sentence_keys:    [...]
trulens_groundedness:          0.92
trulens_context_relevance:     0.88
ragas_faithfulness:            0.95
ragas_context_relevance:       0.85
gpt3_adherence:                0.91
gpt3_context_relevance:        0.83
gpt35_utilization:             0.79
relevance_score:               0.87
utilization_score:             0.82
completeness_score:            0.91
```

- **Atoms:** the `documents` list — 1–4 documents per record.
- **`response`:** the gold answer (LLM-generated, TRACe-annotated).
- **Sentence-level annotations:** `*_sentences` arrays support
  sentence-precise scoring.
- **TRACe scores:** 8+ pre-computed faithfulness/relevance scores —
  intended for LLM-as-judge calibration, NOT consumed in retrieval-recall
  mode.

## 12 subsets, 5 domains

| Domain | Subsets |
|---|---|
| Biomedical | `covidqa`, `pubmedqa` |
| Technical / Manuals | `emanual`, `techqa` |
| Legal | `cuad` |
| Financial | `finqa`, `tatqa` |
| General / Web | `hotpotqa`, `msmarco`, `hagrid`, `expertqa`, `delucionqa` |

Stele runs 6 (`hotpotqa`, `msmarco`, `covidqa`, `pubmedqa`, `techqa`,
`hagrid`) — representative across the 5 domains.

## What it expects

| Aspect | Bench expects |
|---|---|
| **TRACe (headline)** | LLM-judged faithfulness / relevance / utilization / completeness |
| Retrieval recall | Hits@K over the 1–4 documents |
| Generation quality | groundedness, faithfulness (LLM-judged) |

Vendor positioning: no agent-memory vendor publishes RAGBench headlines
— it's positioned as a RAG-quality benchmark, not a memory benchmark.

## How Stele processes it

```python
for i, rec in enumerate(records):
    for j, doc in enumerate(rec["documents"]):
        s.memory.add(text=str(doc)[:2000], kind="fact",
                     source_refs=[f"stele://ragbench/{subset}/{i}/d{j}"],
                     scope=scope)
    rr = s.recall(query=str(rec["question"]), scope=scope, max_memory_hits=k)
    # score: gold `response` text appears in any recalled snippet
```

## Recipe — `profile: hybrid-best`

| Knob | Value | Why |
|---|---|---|
| `backend.type` | `sqlite` | tiny per-record scale; ~60 records per subset is trivial |
| `indexing.mode` | `sync` | inline |
| `indexing.provider` | `chunkshop` | enables hybrid |
| `indexing.chunker` | `fixed_overlap` (220w / 60w) | document-sized atoms — chunker handles longer ones |
| Embedder | fastembed `all-MiniLM-L6-v2` | works across all 5 RAGBench domains; specialized embedders (PubMedBERT for `pubmedqa`, FinBERT for `finqa`) would lift further |
| `retrieval.default_mode` | `hybrid` | RAGBench documents are short and dense — both keyword and vector contribute |
| `recall(max_memory_hits)` | **30** | only 1–4 docs per record; small k is fine but 30 leaves headroom |
| Metadata | scope=`ragbench-<subset>`; refs=`stele://ragbench/<subset>/<i>/d<j>` | per-subset scope; per-(record, doc) provenance |

### Why this works

- RAGBench documents are short and topically tight — the answer span is
  usually present verbatim or near-verbatim in 1 of the 4 docs.
- Keyword + vector RRF reliably surfaces all 4 docs.
- Default `all-MiniLM-L6-v2` is general-purpose; for the biomedical
  subsets a domain-specific embedder (PubMedBERT-base, 768-d) would
  reach lower-down on the long tail.

## Measured numbers

| Subset | Default (keyword, k=20) | hybrid-best (k=30) |
|---|---:|---:|
| `hotpotqa` | 83.3% | **100.0%** |
| `msmarco` | 91.7% | **100.0%** |
| `covidqa` | 95.0% | **100.0%** |
| `pubmedqa` | 95.0% | **100.0%** |
| `techqa` | 100.0% | 100.0% |
| `hagrid` | 90.0% | **98.0%** |

RAGBench is the cleanest "Stele clears the bench's retrieval bar" result:
**5 of 6 subsets at 100% recall@30**, last at 98%. The remaining gap is
the 1 hagrid record with a phrasing-mismatched answer where neither
keyword nor vector found the gold span.

## What it does NOT do (yet)

- **TRACe scoring.** RAGBench's *headline* metric is TRACe (faithfulness,
  relevance, utilization, completeness). Stele's lane reports retrieval
  recall — the necessary-but-not-sufficient precondition for high TRACe
  scores. Producing real TRACe numbers requires an answer LLM and a
  TRACe scorer. The §4 `answer_workflow` lane is the right surface;
  re-aiming it at RAGBench inputs is logged as next work.
- **Domain-specialized embedders.** PubMedBERT for `pubmedqa` /
  `covidqa`, FinBERT for `finqa` — would tighten the long tail on the
  domain-heavy subsets. Currently `all-MiniLM-L6-v2` everywhere via
  chunkshop default.
- **Sentence-level scoring.** RAGBench provides sentence-precise gold
  annotations. Stele's recall surface returns chunk-level citations;
  scoring at sentence granularity would need a post-hoc filter, not yet
  wired.

## How to reproduce

```bash
.venv/bin/python -m benchmarks.external \
    --ragbench-per-subset 50 \
    --profile hybrid-best
```

Output: `benchmarks/runs/<date>/External-hybrid-best.{md,json}`.
