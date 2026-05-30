# Lane metrics ledger — chunker / packing / filter experiments

Durable record of the retrieval-lane experiments so we can review later and
**repeat** them. Raw run dirs live under `benchmarks/runs/` (gitignored) and use
ephemeral `/tmp/*.db` indexes — only the numbers + configs here are durable.

## Common harness

- **Answerer:** qwen (`Intel/Qwen3-Coder-Next-int4-AutoRound`) @ local
  `192.168.1.193:8000` — free, committal (best jscore answerer; see
  consolidation-chunker-deep doc).
- **Judge:** `gpt-4o` with Mem0's verbatim **jscore** prompt
  (`rejudge_aw.py:_jscore_correct`). Default judge over-credits abstention —
  always read the jscore column.
- **Dataset:** LoCoMo (snap-research, `locomo10.json`), adversarial cat-5 skipped.
  LongMemEval-S + RAGBench for cross-benchmark.
- **Reproduce:** `OPENAI_API_KEY=<work_key>` then the scripts below. Each writes
  rows (question/expected/answer/context) to `benchmarks/runs/<name>/` for
  re-judging without re-answering.

Scripts (all committed under `benchmarks/external/`):
- `locomo_chunker_shootout.py` — N-lane chunker/packing shootout.
- `lane_gap_capture.py` — dumps per-lane chunks for raw-wins/digest-loses Qs.
- `locomo_entity_filter.py` / `locomo_entity_blend.py` — entity-filter probes.
- `consolidators/{extractive,llm,enriching}.py` — the consolidator callables.

---

## 1. Cross-benchmark generalization (consolidation vs digest vs raw_fetch)

qwen, jscore. LoCoMo n=200 (10×20); LongMemEval n=12; RAGBench n=36.
Run: `benchmarks.answer_workflow` (see `multibench.sh` recipe in commit history).

| benchmark | raw_fetch | digest | consolidation | note |
|---|---:|---:|---:|---|
| LoCoMo (n=200) | 0.67 | 0.40 | 0.34 | raw_fetch >> rest |
| LongMemEval (n=12 ⚠) | 0.00 | 0.25 | 0.00 | too small / format mismatch |
| RAGBench (n=36) | 0.92 | 0.86 | 0.86 | jscore > default here |

Takeaway: consolidation generalizes (even RAGBench passages) but never beats
digest; raw_fetch is the ceiling everywhere. Default-judge inflation huge on
LoCoMo/LongMemEval (up to +0.75).

## 2. Entity filtering on consolidation facts

LoCoMo, qwen, jscore. 5 convs × 20 QA.

| experiment | arm | jscore | abstain | note |
|---|---|---:|---:|---|
| `locomo_entity_filter` (LLM consolidator) | baseline | 0.18 | 77% | LLM subjects unreliable |
| | entity filter (hard) | 0.04 | 87% | dropped answer-bearing facts |
| `locomo_entity_blend` (extractive consolidator) | base (no filter) | 0.30 | 65% | coref spans lift base 0.18→0.30 |
| | hard filter | 0.29 | 69% | filter barely narrows (13.7/15) |
| | blend (boost+fallback) | 0.29 | 70% | ≈ base |

Takeaways: (a) the LLM consolidator was the problem — extractive (subject=speaker,
`[Speaker]`-prefixed spans) lifts base 0.18→0.30. (b) The entity *filter* itself
is neutral on 2-party LoCoMo — it barely narrows and names are already rankable.
The coref win is a RANKING win (name in span text), not a filter win.

## 3. Chunker / packing shootout

LoCoMo, qwen, jscore. 5 convs × 20 QA (n=100). `locomo_chunker_shootout.py`.
Lanes: raw_fetch (full text); digest (fixed_overlap + lede + top-5);
consolidation (consolidation chunker + extractive consolidator, distilled);
enriching (consolidation chunker + enriching consolidator, verbatim).

| run | lane | jscore | abstain | ~tokens | notes |
|---|---|---:|---:|---:|---|
| v1 (BUG: enriching capped first-60 turns) | raw_fetch | 0.84 | 0.10 | 18,929 | |
| | consolidation | 0.40 | 0.55 | 455 | |
| | digest | 0.36 | 0.58 | 1,325 | |
| | enriching | 0.14 | 0.84 | 254 | INVALID — doc-order cap dropped ~380 turns |
| v2 (enriching keep-all per-sentence, top-15) | raw_fetch | 0.86 | 0.13 | 18,929 | |
| | consolidation | 0.39 | 0.56 | 455 | |
| | digest | 0.35 | 0.59 | 1,325 | |
| | enriching | 0.26 | 0.70 | 312 | per-sentence too granular; top-15 starves model |
| v3 (enriching TURN-level top-30 + digest_enriched) | _pending_ | | | | added digest_enriched lane |

Predictions for v3 (stated before the run): enriching ~0.40, digest_enriched
~0.48, raw_fetch ~0.86, digest ~0.35, consolidation ~0.39.

## 4. Lane-gap diagnostic (why raw beats digest)

`lane_gap_capture.py` → `benchmarks/runs/lane-gaps/` — 10 conv-26 questions where
raw_fetch correct / digest wrong, one folder each (question.md + per-lane JSON
with chunks). Headline example **q01 "When did Melanie paint a sunrise?"
(gold 2022)**: digest's fixed_overlap chunks were painting-themed noise that
NEVER contained "I painted that lake sunrise last year"; enriching chunk[1] was
exactly `(around 2023-05-08) [Melanie] Yeah, I painted that lake sunrise last
year! [date: 2022]`. Proves the gap is the **chunker substrate** (fixed_overlap
shreds the answer-bearing turn), not the packing strategy.

---

## Open hypotheses to test next

- **digest_enriched > digest** — digest packing over the enriched substrate
  (turn-aware, speaker/date-tagged) should beat digest over fixed_overlap. (v3)
- **Enriching as the default substrate**, digest/consolidation/raw as packing
  strategies on top.
- **Temporal per-fact filtering** now wired (`metadata.fact_date`) but untested
  on the LoCoMo temporal subset (anchored to conversation timeline).
- Larger N / more conversations (current runs are 5 convs — answer-dense slice
  where raw_fetch dominates by ~0.45).
