# Benchmark Recipes — index

One doc per third-party benchmark Stele runs. Each doc covers:

1. **Architecture** — how the dataset is shaped (records, atoms,
   metadata, gold linkage).
2. **What the benchmark expects** — its native metrics and what counts
   as a passing score.
3. **How it works** — how Stele ingests and queries the data.
4. **Matched recipe** — the specific chunking / embedding / retrieval /
   metadata combination that does well on this shape, and why.

The point: Stele doesn't need a single one-size-fits-all default that's
best for every benchmark — it needs a small set of named recipes you can
pick by data shape.

## Index

| Benchmark | Recipe | Best measured | Doc |
|---|---|---:|---|
| LoCoMo | `locomo-best` (extract+hybrid+k=80) | 67.6% answer-span | [`locomo.md`](locomo.md) |
| MultiHop-RAG | `hybrid-best` (hybrid+k=30) | 73.8% answer / 90.8% evidence | [`multihop-rag.md`](multihop-rag.md) |
| LongMemEval-S | `hybrid-best` (hybrid+k=30) | **88.0%** | [`longmemeval.md`](longmemeval.md) |
| LongBench QA-family | `hybrid-best` *(except `multifieldqa_en`)* | 80.0–96.7% per task | [`longbench.md`](longbench.md) |
| RAGBench | `hybrid-best` | **100% on 5 of 6 subsets** | [`ragbench.md`](ragbench.md) |
| CRAG | (unblocked, see doc) | UNAVAILABLE | [`unavailable.md`](unavailable.md) |
| AgentLongMemEval | (unblocked, see doc) | UNAVAILABLE | [`unavailable.md`](unavailable.md) |

## Profile catalogue

Profiles are defined in
`benchmarks/external/harness.py::PROFILES` and selected via
`--profile <name>`. Today there are three:

| Profile | Purpose |
|---|---|
| `default-keyword` | Floor: memory backend, keyword only, k=20 |
| `hybrid-best` | General-purpose: sqlite + chunkshop hybrid + k=30 |
| `locomo-best` | Conversational memory: + Stele.extract pre-step + k=80 + retain_message_text |

## The orthogonal axes

Every recipe combines values along five orthogonal axes:

| Axis | Knob(s) | Values used |
|---|---|---|
| **Backend** | `backend.type` | `memory` / `sqlite` / `postgres` |
| **Chunking** | `indexing.chunker`, `chunk_words`, `chunk_overlap_words` | `fixed_overlap` (220w / 60w) — single shape today; chunkshop SP-A `ConsolidationChunker` is the next step |
| **Embedding** | chunkshop default (today) | fastembed `all-MiniLM-L6-v2`, 384-d — domain-specialized embedders not yet wired |
| **Retrieval** | `retrieval.default_mode`, `hybrid_method`, `hybrid_weights`, `recall(max_memory_hits)` | `keyword` / `hybrid` / `vector`; RRF default; `k` from 20 to 80 per shape |
| **Metadata** | `MemoryScope.namespace`, `source_refs` | per-benchmark namespace, per-record/passage/turn ref |

## What "matched to the shape" means

| Data shape | Pick |
|---|---|
| Short conversational turns with weeks of history | `locomo-best`: extract → atoms, hybrid recall at high k |
| Multi-doc news / Wikipedia with paraphrased queries | `hybrid-best`: vector dominates, RRF fuses with keyword |
| Long single-doc with exact-token answer spans | keyword-heavy (`hybrid_weights={"keyword":0.7,"vector":0.3}`) or pure-keyword — *not* default hybrid |
| Industrial RAG / technical manuals | `hybrid-best`: short focused docs, both signals work |
| Temporal-staleness benchmarks (CRAG) | postgres + `Memory.add(supersedes=)` + `as_of` recall (recipe in unavailable doc) |
| Multi-tool agent traces | route tool I/O through `Stele.stash_tool_result`; extract only assistant/user turns |

## Open levers (not in any profile yet)

- **chunkshop SP-A `ConsolidationChunker`** — emits episodes + atomic SPO
  facts via an LLM (or extractive) consolidator; pairs with the
  pg-raggraph memory-bridge for typed-relationship graph search. Spec at
  `/home/yonk/yonk-tools/chunkshop/docs/superpowers/specs/2026-05-19-chunkshop-memory-primitives-sp-a-design.md`.
  Expected lift on LoCoMo: 67.6% → 75–80% range.
- **Reranker over top-k** — cross-encoder lift; standard next step on
  every multi-doc retrieval benchmark.
- **Domain-specialized embedders** — PubMedBERT for biomedical, FinBERT
  for financial. Chunkshop config supports it; not yet selected per
  recipe.
- **Multi-hop decomposition** — retrieve → expand entities → re-recall.
  Helps the residual hard MHR / musique cases.
- **Sentence-level recall scoring** — RAGBench provides
  sentence-precision gold; current scoring is chunk-level.
