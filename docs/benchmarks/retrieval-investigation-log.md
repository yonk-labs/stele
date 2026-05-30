# Retrieval investigation log (2026-05-29 → 30)

Master narrative + decision record for the chunker / embedding / packing / filter
work. Source-of-truth for the deliverables to come: **changelog**, **final
benchmark report**, **blog(s)**, and **user docs**. Raw per-lane numbers +
configs live in [`lane-metrics-ledger.md`](lane-metrics-ledger.md); this file is
the *story and the decisions*.

Harness (constant unless noted): answerer **qwen3-coder @192.168.1.193** (local,
committal), judge **gemma-4-26B @192.168.1.133** (local) with Mem0's verbatim
**jscore** prompt (abstention = wrong). LoCoMo, adversarial cat-5 skipped.

---

## TL;DR (so far)

The biggest accuracy levers were **upstream of the strategies we'd been tuning**:
the chunker substrate and the embedding model. In impact order:

1. **sentence_aware chunker** (full-sentence boundaries + neighbor window):
   digest 0.35 → **0.51** jscore at equal tokens. The single biggest win.
2. **bge-base-en-v1.5 (768d) embeddings + bigger chunks** — replaced the
   hardcoded all-MiniLM-L6-v2 (384d). (Quantifying in the bge re-run.)
3. Correctness plumbing that doesn't move accuracy but makes retrieval correct:
   select-distinct dedup, metadata/time filters, temporal routing, similarity
   wiring.

Useful **negatives** (saved complexity): expanded hints (WordNet synonyms) were
marginal; cosine vs ip vs l2 made **no difference** (bge vectors are normalized).
raw_fetch (full context) remains the accuracy ceiling (~0.82) everywhere.

---

## Code changes shipped (changelog-ready)

Features:
- **Consolidation chunker** as a first-class indexing option (`chunker="consolidation"`)
  + benchmark strategy lane. Mem0/Letta-shaped distill-to-facts baseline.
- **sentence_aware chunker** (`chunker="sentence_aware"`): full-sentence
  boundaries via chunkshop SentenceAwareChunker + optional
  NeighborExpandChunker(window=N) for ±N-sentence context. Fixes mid-sentence
  shredding.
- **Embedding model is now configurable + upgraded**: `IndexingConfig.embed_model`
  defaults to `Xenova/bge-base-en-v1.5-int8` (768d), was a hardcoded
  all-MiniLM-L6-v2 (384d) the config couldn't override. dim auto-derived.
- **Chunk sizes tuned to bge's 512-tok window**: chunk_words 220→350, overlap
  60→80, sentence_max_chars 1000→1600, min 200→300.
- **Filtered retrieval**: `query(filters=...)` honors `created_after/before` +
  `metadata.<key>` (eq/`__in`/`__gte`/`__lte`) across all backends + vector path.
  Exposed on MCP `stele_query` + CLI `stele query`.
- **Temporal routing** (`retrieval.temporal_routing`, opt-in): `parse_temporal`
  turns "last week" into a date filter, with empty-window fallback.
- **Temporal fact metadata**: consolidator emits resolved `[date: ISO]`; chunk
  store lifts it into a filterable `fact_date` field.
- **select-distinct**: `_prepare_hits` dedups returned chunks by text (query +
  search, all modes); enriching consolidator dedups spans.
- **similarity wiring**: `config.similarity` now reaches the sink
  (`TargetConfig.vector_metric`) — was silently ignored.

Fixes:
- chunk store surfaced `original_content`; now `embedded_content` (post-distill).
- artifact metadata + created_at propagated to chunks (filterable).

Tests: full suite 875 passing; new contract tests for consolidation,
sentence_aware, filtered retrieval, temporal.

---

## Findings (benchmark-report-ready)

See the ledger for the tables. Headlines:

- **Cross-benchmark (LoCoMo n=200 / LongMemEval / RAGBench):** consolidation
  generalizes but never beats digest; raw_fetch is the ceiling everywhere.
- **Chunker shootout (MiniLM era):** raw_fetch 0.82 ≫ consolidation 0.39 ≈
  digest 0.36. Enriching-as-replacement-substrate cratered (0.15) — a design
  bug + recall shortfall, NOT a verdict on enrichment.
- **Entity filtering:** neutral-to-negative on LoCoMo — entity is rankable and
  2-party convos give nothing to narrow. The coref win (subject=speaker, name in
  span) is a *ranking* win (0.18→0.30), not a filter win.
- **Digest variants (MiniLM):** **digest_sentence 0.51 vs digest_fixed 0.35** —
  sentence-aware substrate is the big lever. Expanded hints marginal (+0.03 fixed,
  0 on sentence). [bge re-run pending.]
- **Similarity:** cosine = ip = l2 (identical retrieval; bge vectors normalized).

---

## Methodology corrections (blog-worthy: the honest wrong-turns)

This investigation's real story is a sequence of *measuring bugs as verdicts*,
each caught by pushing past the first conclusion:

1. **Judge over-credits abstention** — the original gpt-4o judge marked "I don't
   know" CORRECT, inflating 2–10×. Fixed with jscore (Mem0's prompt).
2. **"Enriching loses" ×3** — each crater was a different bug: a silent max_facts
   cap (dropped 380 turns), per-sentence granularity (top-k starvation), and the
   vector recall shortfall (floor-capped candidate set). Lesson: don't report a
   retrieval bug as a substrate verdict.
3. **Replace vs augment** — built enriching as a *replacement* substrate; the
   user's model was *additive* (keep the text, append resolved facts). The
   additive version helped (digest_plus_facts 2/10 > digest 1/10); replacement
   cratered.
4. **The hardcoded embedder** — all the murk above ran on a weak 2021 MiniLM that
   the config couldn't even override. Topical noise > specific answer is classic
   MiniLM. bge-base + bigger chunks is the upstream fix.
5. **Stored vs generated summary** — consolidation's `[SUMMARY]` was a stored,
   query-blind episode summary; digest's is generated query-time with lede hints.
   Generate, don't store.
6. **Judge instruction** — reverted to gpt-4o judge after being told to use local
   models; corrected to gemma@133 (verified ranking matches gpt-4o).

---

## Session 2026-05-30 (cont.): hybrid architecture (blog + guide source)

Triggered by a single failing question — q07 "When did Caroline meet up with her
friends, family, and mentors?" — which exposed how little we understood our own
hybrid path. Three theories died in order, each killed by measuring instead of
arguing (this is the blog's spine):

1. **"Chunk dilution by size."** Overstated. The answer chunk's *exact* cosine to
   the query is a healthy 0.60 at 1000-char — it's findable, just not top-ranked.
   Shrinking to 500-char concentrates the embedding and it jumps to #0, but that's
   a precision/coverage *tradeoff*, not a bug. Size was a red herring.
2. **"The vector ranking is broken."** Overstated. The chunkshop sink is
   approximate (answer at sink-rank 22 vs exact-cosine-rank 39, scores don't match
   cosine) but even *perfect* brute-force cosine puts the answer at 39/66. The
   query is semantically diffuse — friends/family/mentors/meeting recur all over a
   life-chat — so no vector metric surfaces it. Confirmed by sweeping pgvector
   operators (see below).
3. **"FTS punctuation is the cause."** Real bug, wrong path. `_fts_query` glued
   punctuation to terms (`"friends," OR "mentors?"`) AND carried stopwords — but
   that's the *artifact* keyword path; the *hybrid* keyword side uses Python
   `keyword_score`, which already tokenizes cleanly. Fixing punctuation changed
   the q07 hybrid result by zero.

What actually was wrong / worth shipping:

- **Stopwords in the keyword query** (`rank.py`): new shared `STOPWORDS` +
  `content_terms()` strips function words + punctuation before scoring and before
  the FTS expression. `keyword_score` and `_fts_query` now share it (also closes
  the sqlite-OR / postgres-AND tokenization divergence on the sqlite side).
  q07 query → `caroline meet friends family mentors`. Effect alone: nudged q07
  hybrid from absent → rank 9. Necessary, not sufficient.
- **Hybrid returned snippets, not full chunks** (`hybrid.py`): the
  representative-hit merge iterated `[*kw, *vec]` so the keyword path's 500-char
  *snippet* won over the vector path's full chunk text — the exact opposite of the
  code's own comment. Every keyword-matched chunk in hybrid mode was silently
  truncated to ~500 chars. One-line fix (`[*vec, *kw]`); ranking unchanged, text
  now full. **This also tainted the first cascade shootout** (cascades packed 3×
  the context), which is why the 9-lane matrix was re-run on a level field.

- **pgvector metric sweep (for the guide).** On L2-normalized bge vectors,
  cosine `<=>` ≡ L2 `<->` ≡ inner-product `<#>` give *provably identical*
  rankings (all monotone transforms of vᵀq; verified: same answer-rank 39, same
  top-5). L1 `<+>` is the only operator that reorders, and it barely moves it
  (39→37). Takeaway for the guide: **don't tune the distance metric on normalized
  embeddings — it cannot help.** Hamming/Jaccard are bit-vector only.

- **Cascade vs RRF — the win evaporated (9-lane matrix, n=50, postgres).** The
  mechanic is real (cascade_b = semantic-net → keyword-rerank; the rerank stage
  carries the strong signal, the net only needs to contain the answer; FTS pool 30
  → top 10). But on a FAIR field (after the snippet fix), retrieval barely moves
  the needle: **cascade_b 0.700 ≈ rrf 0.693**, cascade_a 0.660. The entire 6-vs-4
  from the first shootout was the snippet-truncation confound. **Lesson for the
  blog: a correctness bug dwarfed the architecture choice.** Keep RRF as default
  (simpler, already shipped); the snippet fix is the actual win.
- **Packing is the real lever, and it's query-type-specific (n=50).** By packing:
  facts 0.727 > raw 0.680 > digest 0.647. Split by question type:
  - **Temporal ("when/how-long"), n=20:** digest+**facts** 0.80–0.85 vs raw/digest
    0.65–0.70. The extractive `[date: ISO]` spans answer what prose buries. +0.15–0.20.
  - **Non-temporal, n=30:** **raw chunks** best (0.67–0.73); facts neutral-to-slightly
    negative. Don't pay the packing tax when the answer isn't a date/fact.
  - **Plain lede digest is the worst packing everywhere** — strips signal; only
    wins once facts are appended. (Confirms the earlier raw_chunks > digest result.)
  - Top overall (tied): `rrf+facts` = `cascade_b+facts` = 0.74.
  - Caveat: margins (37 vs 35 / 50) are within noise; only the temporal-facts
    effect is pronounced. Single dataset, answer-dense, regex temporal heuristic.
    Directly motivates the adaptive bake-off (no universal best).

- **Methodology, again:** ran the entire q07 dig on sqlite before catching that
  postgres/pgvector is the default — ranks/cosines don't transfer between
  backends. Re-ran everything on postgres.

## Open items / next

- 9-lane matrix (3 retrieval × 3 packing, postgres, n≈50) → fills the cascade
  aggregate verdict + the digest/digest+facts packing lift. **Blog + guide
  deliverables are queued on this.**
- **Adaptive strategy bake-off (future feature).** No universal best strategy: the
  winner depends on the user's query mix (exact/factoid/temporal favour
  keyword/FTS/metadata-predicate ranking; paraphrase/conceptual favour semantic).
  Ship a user-runnable, periodic (e.g. weekly) bake-off that scores
  retrieval×packing on the user's OWN corpus + query log and rewrites the
  configured default (cascade_b ↔ cascade_a ↔ rrf; raw/digest/facts). Reuse the
  `cascade_packing_matrix` harness as the engine; expose as `stele tune` CLI/MCP.
  Note: cascade_b already encodes "exact ranks, semantic recalls" (keyword is its
  rerank stage) — a different corpus could still favour FTS-first.
- bge re-run results → append to ledger + Findings.
- Decide: ship sentence_aware as the default chunker? (it's the biggest win).
- digest_enriched done right (additive, inline coref/date annotation of digest's
  own chunks) — the version that should win.
- Promote feature docs (filtered-retrieval.md exists; add chunker/embedding doc).
- Larger N + more conversations (current runs are 5 convs — answer-dense slice).
