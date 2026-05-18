# Third-Party Benchmarks — Results & Honest Analysis

**Date:** 2026-05-18 · **Branch:** `phase6-7-runtime-working-memory` (PR #1, not merged)
**Harness:** `benchmarks/external/` · `python -m benchmarks.external`
**Raw evidence:** `benchmarks/runs/<date>/External.{json,md}`

> Integrity: every number is from running Stele over the **real published
> dataset** (cached, gitignored). Nothing synthetic. Datasets we couldn't
> fetch are marked UNAVAILABLE — never faked.

## What we measured (and the honest caveat)

This is **retrieval-grade**, deterministic, no-LLM measurement: *does
Stele's memory + `recall` surface the evidence containing the gold answer,
at a disclosed depth k?* It is **not** leaderboard QA accuracy — that needs
an answer LLM scoring generated answers, which this environment doesn't have
and we will not fake. So these numbers are a **retrieval floor**, run with
**keyword memory recall (Phases 1–3 only)** — no vector/hybrid (Phase 4) and
no living-knowledge graph (Phase 5) in this config.

## Results (real data, k=20)

| Benchmark | Scale (real) | answer-span recall@20 | evidence recall@20 | abstention "not misled" | PII |
|---|---|---|---|---|---|
| LoCoMo | 10 samples, **1540 Q** | **44.5%** | 35.7% | 43.9% | 0 |
| MultiHop-RAG | 609 docs, 200 q (172 ans.) | **47.7%** | 18.6% | **92.9%** | 0 |
| LongMemEval-S | 25 of ~500 q | **40.0%** | — | — | 0 |
| CRAG | — | UNAVAILABLE (HF-gated, multi-GB) | | | |
| AgentLongMemEval | — | UNAVAILABLE (no resolvable release) | | | |

## Where we were GOOD

- **PII discipline: 0 leakage on every real run.** The product's hardest
  invariant held over 1700+ real questions across three datasets. This is
  the strongest result and the one that matters most for the positioning.
- **Abstention on MultiHop-RAG null queries: 92.9% not misled.** When the
  corpus genuinely lacks the answer, Stele's recall mostly does not surface
  a confident wrong span. Good signal for "doesn't hallucinate evidence."
- **Determinism.** Same inputs → same numbers, every run (memory backend).
  Reproducible benchmarking is itself a product claim most memory layers
  can't make.
- **It actually ran on real long-context data at scale** (LoCoMo full =
  1540 questions, MultiHop-RAG 609-doc corpus) without degrading or
  crashing.

## Where we were BAD (and why)

- **~40–48% answer-span recall@20 is mediocre** for these benchmarks. Root
  cause is architectural, not a bug: this config uses **keyword memory
  search only**. LoCoMo/LongMemEval reward semantic + temporal matching;
  keyword scoring misses paraphrase, coreference, and time-scoped facts.
- **MultiHop-RAG evidence recall@20 = 18.6%** (vs 47.7% answer-span). This
  gap is diagnostic: the answer *string* recurs across many news docs, but
  Stele rarely puts the **specific gold document** in the top-k. Multi-hop
  needs retrieval that composes evidence across docs; flat keyword recall
  over 609 docs can't.
- **LoCoMo adversarial "not misled" = 43.9%** — weak. Keyword recall
  happily surfaces the misleading span because it lexically matches the
  question. No claim-level contradiction handling in this path.
- **LongMemEval-S only 25/500 questions.** The 266MB haystack ingest is
  heavy; we ran a disclosed subset. Real but not full-coverage.

## What we need to do to get better (prioritized)

1. **Turn on Phase 4 vector/hybrid retrieval in the harness.** Biggest
   single lever. Keyword→hybrid (chunkshop) should materially lift
   answer-span and especially MultiHop evidence recall. Action: add a
   `retrieval=hybrid` harness mode and report keyword vs hybrid side by side.
2. **Use the Phase 5 living-knowledge graph for the temporal lanes.**
   LoCoMo and LongMemEval-S have heavy temporal/knowledge-update categories;
   `graph_search` with `as_of`/supersession is exactly the right tool and is
   unused here. Action: a `graph` harness mode on the Postgres profile.
3. **Add a reranker over top-k.** Recall@20 with no reranking wastes the
   budget. A deterministic cross-encoder/BM25+vector fusion rerank should
   lift gold-doc precision (the MHR evidence gap).
4. **Multi-hop composition.** For MultiHop-RAG, iterative/decomposed recall
   (retrieve → expand on entities → re-recall) instead of one flat query.
5. **Abstention/contradiction layer.** For LoCoMo adversarial: detect when
   the top evidence contradicts itself or the question premise, and
   down-rank — Phase 5's retraction/supersession primitives are the
   foundation to build this on.
6. **Scale + breadth.** Run LongMemEval-S full (≥500), add the official
   per-category breakdown (temporal / knowledge-update / multi-session),
   and obtain CRAG (HF license + auth) and a real AgentLongMemEval release.
7. **Then, and only then, a QA-accuracy lane.** Wire an answer model behind
   a flag to produce leaderboard-comparable accuracy — gated, opt-in, never
   the default, and clearly separated from the deterministic retrieval
   numbers above.

## Bottom line

Stele is **trustworthy but not yet competitive on raw recall** in its
keyword-only config: it doesn't leak PII, doesn't fabricate evidence on
unanswerable queries, and is fully reproducible — but ~45% answer-span
recall says the retrieval stack (vector, graph, reranking, multi-hop) needs
to be *engaged*, not just present. The numbers are a credible, honest
baseline to improve from, not a headline to advertise. Reproduce anytime
with `stele-external-bench`.
