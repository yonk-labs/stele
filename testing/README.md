# stele — cross-corpus retrieval study

A self-contained bundle for the big benchmarking run: stele's retrieval/packing
lanes measured against **Mem0** and **Letta** across three domains, plus the
write-up and the exact scripts and data behind it.

> **Scope honesty.** This study measures *retrieval quality* — accuracy (jscore),
> context size (tokens), retrieval rank (MRR), and latency — under a single fixed
> answerer + judge. It is **not** a payload-reduction or PII benchmark (that's the
> showcase). Cross-vendor numbers here are apples-to-apples *only because* the
> embedder, judge, answer model, corpora, and sample size are held constant. They
> are **not** comparable to any vendor's self-reported LoCoMo/LongMemEval figures.

## What's in here

```
testing/
  README.md          ← you are here
  blog.md            ← the write-up ("What Actually Moves RAG Accuracy")
  results/
    MEGA-GRID.md     ← every system × lane × corpus, human-readable
    MEGA-GRID.csv    ← same, load into Excel
    *.json           ← curated final run data (the runs that feed the grid)
  scripts/           ← frozen snapshot of the benchmark code that produced it
    consolidators/   ← extractive / enriching / llm packing helpers
```

The `scripts/` here are a **snapshot for browsing**. Their runnable home (where the
intra-package `benchmarks.external.*` imports resolve and the `benchmarks/runs/`
paths exist) is `benchmarks/external/` in the repo root. Run them from there.

## Setup measured

| Knob | Value |
|---|---|
| Backend | Postgres + pgvector, chunkshop chunk store, HNSW index |
| Embedder | `bge-base-en-v1.5` (same for stele and Mem0; Letta archival uses its own `text-embedding-3-small`) |
| Answerer | `Qwen3-Coder-Next` (local, 192.168.1.193) |
| Judge | `gemma-4-26B` (local, 192.168.1.133), Mem0 verbatim jscore, **abstention = WRONG** |
| Corpora | LoCoMo (conversational, n=250) · RAGBench-HotpotQA (multi-hop factoid, n=250) · RAGBench-CovidQA (biomedical, n=246) |
| Floor | no-context parametric baseline (same Qs, empty context) — subtract before believing any score |

`jscore` = fraction judged correct. `mrr` = reciprocal rank of the first chunk
containing the gold span (stele only — competitor memories are abstractive, so MRR
is N/A there). `~tokens` ≈ `ctx_chars / 4`.

## Headline results

**Conversational (LoCoMo, n=250) — stele dominates.**

| system | best lane | jscore | ~tokens |
|---|---|---|---|
| stele | raw_fetch (whole doc) | **0.84** | 19.8k |
| stele | hybrid raw chunks | 0.70 | 6.2k |
| Letta (archival) | (memory) | 0.56 | 1.8k |
| Mem0 (local) | (memory) | 0.11 | 462 |
| parametric floor | (no context) | 0.00 | 0 |

**Multi-hop factoid (HotpotQA, n=250) — neighbor-off matches Letta's token budget and beats its accuracy.**

| system | lane | jscore | ~tokens |
|---|---|---|---|
| stele | `nb0_k=10` (neighbor off) | **0.94** | **498** |
| stele | raw_fetch | 0.94 | 500 |
| Letta (archival) | (memory) | 0.92 | 500 |
| Mem0 (local) | (memory) | 0.44 | 139 |
| parametric floor | (no context) | 0.02 | 0 |

**Biomedical (CovidQA, n=246) — same shape.** stele raw 0.78 @ 1.4k, Letta 0.74 @ 580, Mem0 0.14 @ 26, floor 0.04.

See `results/MEGA-GRID.md` for the full ~150-row grid (every lane, every corpus,
jscore/MRR/tokens/retr_ms/ans_ms).

## What held up at n=250

- **Reduction loses to raw chunks.** On LoCoMo: raw 0.70 > facts 0.64 > digest 0.60 > enriching 0.54. Every compression — Mem0's LLM facts, our consolidation/enriching chunkers, query-time digests, the kitchen-sink `digest_mix` — tied or lost to feeding raw retrieved chunks. The three systems line up on a monotonic accuracy-vs-tokens curve.
- **Pure keyword retrieval is catastrophic** (0.05–0.35 vs 0.70–0.94 for hybrid). The single biggest, cheapest fix if you're still on it.
- **Document-size routing.** When the doc fits the budget (most factoid corpora), feed it whole — retrieval adds tokens and latency for no accuracy gain.
- **`neighbor_window=0` halves tokens on small docs at equal/better accuracy.** Neighbor expansion duplicates context in short docs; turning it off is what closes the "Letta is more efficient" gap (`nb0_k=10` = 0.94 @ 498 tok).
- **Presets, not one default:** `balanced` (hybrid + neighbor on + k≈10), `max_accuracy` (whole doc / more chunks), `token_min`/`fast` (neighbor off, fewer chunks).

## Measurement-integrity notes (the wrong turns are part of the record)

- **Small-N flips.** Facts-packing *beat* raw at n=40 (0.75 vs 0.68) and *lost* at n=250 (0.636 vs 0.704). Forty questions is a coin flip; every conclusion here is at n≈250.
- **Shared-table corruption.** The Postgres chunk store hardcodes `table="chunks"`, so two concurrent stele-postgres runs clobber each other. stele lanes were serialized; an exact-vs-HNSW comparison was retracted after it turned out to measure the same index twice. (`hybrid_raw_exact` vs `hybrid_raw_hnsw` here used isolated namespaces.)
- **Mem0 faiss path reuse** silently reset memories to 0 after the first unit until each unit got a unique store path; its LLM extraction is also intermittently flaky (non-JSON from the local model).
- **The floor is real.** No-context baselines are 0.00 / 0.02 / 0.04 — the scores are retrieval, not pretraining recall.
- **Letta agent-mode** (`letta-agent`, n=20) scored 0.00 and is **not** a fair number — the run was interrupted mid-flight; it's retained only as a record, not a result. Letta's real lane is `letta-archival`.

## Reproduce

Scripts run from the repo root as modules (Postgres + the local model endpoints must be up):

```bash
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.high_n_matrix --n 250
OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.topk_sweep --n 250
OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.mem0_lane
OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.letta_lane
# ... then consolidate every lane into the grid:
.venv/bin/python -m benchmarks.external.consolidate_grid
```

Run data lands in `benchmarks/runs/cross-corpus/` (gitignored); the curated subset
that feeds this grid is copied into `results/` here.
