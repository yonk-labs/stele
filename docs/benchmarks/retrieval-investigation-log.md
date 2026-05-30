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

## Open items / next

- bge re-run results → append to ledger + Findings.
- Decide: ship sentence_aware as the default chunker? (it's the biggest win).
- digest_enriched done right (additive, inline coref/date annotation of digest's
  own chunks) — the version that should win.
- Promote feature docs (filtered-retrieval.md exists; add chunker/embedding doc).
- Larger N + more conversations (current runs are 5 convs — answer-dense slice).
