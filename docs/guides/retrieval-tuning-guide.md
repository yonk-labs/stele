# Improving Your Graph / Hybrid Setup — Tuning Guide

Concrete, ranked knobs that **actually moved real third-party benchmark
numbers** in this repo's bake-off (LoCoMo, MultiHop-RAG, LongMemEval-S).
Every delta below is from a measured run, not theory.

## 0. Pick the right engine (biggest single decision)

| Engine | Config | Best for | Real result |
|---|---|---|---|
| keyword (Phases 1-3) | `backend: memory/sqlite`, default recall | floor / no deps | LME-S 20%, LoCoMo 55% — weak on long context |
| **hybrid (Phase 4)** | `indexing.mode: sync`, `retrieval.default_mode: hybrid`, `[chunkshop]` | **default choice** | MHR 100% evidence, LME-S 90%, LoCoMo 87% |
| graph (Phase 5) | `backend: postgres`, `graph.enabled: true`, `[postgres-graph]` | temporal / living-knowledge / best abstention | LoCoMo abstention best; slow |

**Default to hybrid.** It cleared 80% on all three benchmarks. Keyword is a
fallback; graph is for temporal/evolving knowledge and superior abstention.

## 1. Distil to memories — but extraction QUALITY is the real lever

LoCoMo, k=40, honest measurements:

- raw dialogue turns → **62.9%** (hybrid)
- **Stele's own `extract.from_messages` → recall → 65.5%** (real e2e, +3pts)
- ideal/benchmark-distilled observations → **86.8%** (ceiling, NOT Stele)

The lesson is nuanced: recalling over distilled memories is the right
architecture (`stele.extract.from_messages/from_text` then recall over the
memories, not the raw transcript) — but Stele's *current deterministic
extractor only buys +3 pts* on LoCoMo. The 21-pt gap to the
ideal-distillation ceiling is the prize: **investing in extraction quality
(better candidate selection, coreference, temporal normalization) is the
highest-leverage roadmap item**, not a config knob you can flip today. Do
not present the ceiling number as an achieved result.

## 2. Never truncate ingested evidence (+~50 pts)

The original harness truncated bodies to 1500 chars → MHR answer-span 47% →
**95%** with full text. Store the full source; let chunking (hybrid) or the
atom (keyword/graph) keep the answer-bearing text. Truncate at *display*,
never at *ingest*.

## 3. Recall depth `k` (recall vs context tradeoff)

Default `max_memory_hits` is 5 — far too shallow over hundreds/thousands of
atoms. Raise per workload and **report recall@k**:

- short/scoped corpora: k=10–20
- long multi-session / multi-doc: k=30–40
- pass it explicitly: `stele.recall(..., max_memory_hits=k)` or
  `stele.query(..., limit=k)`

k monotonically helps recall but grows prompt cost — pair with reranking
(below) instead of unbounded k.

## 4. Hybrid knobs (`IndexingConfig` / `RetrievalConfig`)

- `retrieval.default_mode: hybrid` (or `vector`) — keyword-only is the floor.
- `indexing.chunk_words` (default 220) / `chunk_overlap_words` (60):
  - prose / news / docs: keep ~220–320, overlap ~60 (don't fragment the
    answer sentence)
  - short dialogue turns: chunking is mostly a no-op; prefer distilled atoms
    (see §1)
- `indexing.hybrid_method`: `rrf` (robust default) vs `weighted_sum`
- `indexing.hybrid_weights`: `{keyword, vector}` — raise `vector` for
  paraphrase-heavy / semantic queries; raise `keyword` for entity/ID lookups
- `indexing.vector_dim` / embedder: defaults are fine; keep consistent across
  ingest+query.

## 5. Graph knobs (`GraphConfig`, Phase 5)

- `graph.evolution_tier`: `structural` (default, fast) → `fact_aware` →
  `full` (more temporal/contradiction signal, heavier).
- `graph.retracted_behavior`: `surface_both` (cite-everything, default) /
  `flag` (mark) / `hide` (erase) — `hide` raises abstention precision,
  lowers recall.
- For temporal questions pass `as_of=<datetime>` /
  `recall(strategy="graph_search", as_of=...)` — this is the LoCoMo
  temporal-category lever and graph's reason to exist.
- **Performance:** graph is slow because every `memory.add` →
  `Revisor.ingest_evidence` embeds the atom (FastEmbed, CPU) AND opens a
  fresh pg-raggraph async pool per call. To speed up: batch evidence and
  ingest once; reuse one `GraphRAG`/pool (a future Revisor optimization —
  per-call pool is a Phase-5 simplicity tradeoff); pre-embed; or use graph
  only for the temporal lane and hybrid for bulk recall.

## 6. Abstention is a tradeoff — tune it deliberately

Richer recall ↑ answer recall but ↓ "not-misled" on adversarial questions
(LoCoMo: 20% → 12% when we added rich context). Counter with: graph
`retracted_behavior=hide`/`flag`, a `confidence_floor` on recall, or the
`abstain` strategy / `sufficient` callback so the agent declines when
top-evidence is weak or self-contradictory.

## 7. Reranking (next lever, not yet built here)

Retrieve a large candidate pool, rerank to a tight k. Lifts gold-doc
precision (the residual MHR/LoCoMo evidence gap) without paying unbounded-k
context cost. Deterministic fusion or a cross-encoder; keep it out of
`retrieval/`/`recall/` per the arch rule (a ranking stage in the indexing
layer).

## TL;DR recommended starting config

```yaml
backend: { type: postgres, dsn: <your dsn> }   # or sqlite for hybrid-only
indexing: { mode: sync, hybrid_method: rrf }
retrieval: { default_mode: hybrid }
graph: { enabled: true, evolution_tier: structural,
         retracted_behavior: surface_both }     # Phase 5, temporal lane
```
…then **distil with `stele.extract`**, **don't truncate**, **recall at
k≈30**, and use `as_of` for temporal questions. That config is what produced
≥80% on all three real benchmarks.

> Metric note: all numbers here are deterministic *retrieval recall*, not
> LLM-judged QA accuracy. For leaderboard-comparable accuracy add an answer
> model as a separate, opt-in lane — never the default.
