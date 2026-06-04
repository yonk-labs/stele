---
title: Real Third-Party Benchmarks — Results & Methodology
created: 2026-05-18
status: evidence — REAL datasets, REAL runs, no fabricated numbers
branch: phase6-7-runtime-working-memory — NOT merged (PR #1)
harness: benchmarks/external/  ·  cli: `stele-external-bench` / `python -m benchmarks.external`
---

# Real Third-Party Benchmarks

## Integrity statement

Every number here comes from running Stele over the **real published
dataset**, cached under `benchmarks/.cache/` (gitignored). No synthetic
substitution. Datasets that cannot be fetched in this sandbox are reported
**UNAVAILABLE with the reason** — never with invented numbers.

## What is measured (and what is NOT)

**Measured — retrieval-grade, deterministic, no LLM:** does Stele's memory +
`recall` surface the evidence containing the gold answer? `answer-span
recall@k`, `evidence recall@k`, abstention-not-misled, PII leakage,
determinism (memory backend, fixed inputs).

**NOT measured — leaderboard QA accuracy.** That requires an answer LLM
scoring generated answers; Stele is a memory/retrieval layer and this
sandbox has no answer model. Producing QA-accuracy numbers without one would
be fabrication, so it is explicitly out of scope and not reported.

`k` is the recall depth, **disclosed** (default 20). Stele's default
`recall` cap is 5; over hundreds/thousands of evidence atoms that is an
unfairly shallow test, so the benchmark sets and reports `k`. This is
**keyword-grade memory recall (Phases 1–3)** — Stele's vector/hybrid
indexing (Phase 4) and the pg-raggraph living-knowledge graph (Phase 5)
would raise these numbers but are a separate config, not exercised here.

## Results — headline run (real data, k=20)

| Benchmark | Real dataset | Scale | answer-span recall@20 | evidence recall@20 | abstention-not-misled | PII leak |
|---|---|---|---|---|---|---|
| **LoCoMo** | snap-research/locomo `locomo10.json` | 10 samples, **1540 answerable Q** | **44.5%** | 35.7% | 43.9% (71→ adversarial) | 0 |
| **MultiHop-RAG** | yixuantt/MultiHop-RAG (GitHub LFS) | 609-doc corpus, 200 queries (172 answerable) | **47.7%** | 18.6% | **92.9%** (null_query) | 0 |
| **LongMemEval-S** | xiaowu0162/longmemeval `longmemeval_s` (266MB) | 25 questions | **40.0%** | — | — | 0 |
| **CRAG** | Meta-KDDCup-24/crag-task-1-and-2 | — | **UNAVAILABLE** — HF-license-gated (401) + multi-GB | | | |
| **AgentLongMemEval** | — | — | **UNAVAILABLE** — no openly-resolvable release locatable from sandbox | | | |

Reproduce: `python -m benchmarks.external --mhr-queries 200 --lme-questions 25`
→ `benchmarks/runs/<date>/External.{json,md}`.

## Honest reading of these numbers

- They are **modest and real**. ~40–48% answer-span recall@20 with *keyword*
  memory recall over real long-context benchmarks is a credible floor, not a
  headline. The MHR gap (47.7% answer-span vs 18.6% exact-gold-doc evidence)
  honestly shows answer text recurs across docs while precise gold-document
  retrieval is hard without vector ranking.
- Abstention: MHR null-query "not misled" 92.9% is genuinely strong;
  LoCoMo adversarial 43.9% is weak (keyword recall surfaces the misleading
  span). Reported, not hidden.
- PII leakage is **0** across every real run — the one hard invariant.
- LongMemEval-S ran on 25 of ~500 questions (the 266MB haystack ingest is
  heavy); disclosed as a subset, not extrapolated.

## Enabling the unavailable ones (no fakes)

- **CRAG**: accept the HF license, provide HF auth, download
  `crag_task_1_dev_v4_release.jsonl.bz2` → `benchmarks/.cache/crag_task1.jsonl.bz2`.
- **AgentLongMemEval**: drop the official JSON at
  `benchmarks/.cache/agentlongmemeval.json` (LongMemEval record shape).
  The loaders fail loud until then; no numbers are produced without data.

## Gate

`tests/integration/test_external_benchmarks.py` runs each harness on a tiny
real slice (skips cleanly if the gitignored cache is absent) and asserts
well-formed, PII-safe (==0) output + that CRAG/AgentLongMemEval raise
`DatasetUnavailable` (honesty, not fabrication).
