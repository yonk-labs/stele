# ConsolidationChunker bake — n=30 LoCoMo (2026-05-28)

First end-to-end test of chunkshop's `ConsolidationChunker` driven through the
real `chunkshop.chunkers.load_chunker(...).chunk(doc)` pipeline, with two
user-wired consolidator callables. Goal was the "is the lever worth pulling"
question — not a production rollout. Same 3 LoCoMo conversations × 10 QA as
the prior 2026-05-27 extractive spot-check, but with consolidators that
**actually compress** (the prior run kept ~16k tokens of episode text).

## Setup

- Answerer: `gpt-4o-mini`
- In-bake judge: `gpt-4o`, strict-ish prompt (refusal = wrong)
- Re-judge: Mem0's verbatim **`jscore`** prompt via `rejudge_aw.py:_jscore_correct`
- Base chunker: `FixedOverlapChunker(window=400w, step=400w)` — single window
  per conversation so the consolidator sees the full dialog
- Consolidators (both in `benchmarks/external/consolidators/`):
  - **extractive** — deterministic; 120-word summary cap + up to 12 midrange
    sentences as fact spans. No API calls.
  - **llm** — `gpt-4o-mini` with structured-JSON output; 120-word summary +
    up to 12 atomic SPO facts with confidence.
- Bake driver: `benchmarks/external/consolidation_bake.py` (self-contained;
  does **not** plumb through `stele.IndexingConfig` — see follow-up below).

## Results

n=30 (3 conversations × 10 QA, adversarial category 5 excluded by harness convention).

| lane | acc (strict, gpt-4o) | acc (jscore, gpt-4o) | mean prompt tokens | consolidate time | notes |
|---|---:|---:|---:|---:|---|
| consolidation_extractive | 0.133 | **0.200** | 552 | 0.01 s | free, deterministic |
| consolidation_llm | 0.133 | 0.167 | 433 | 59.67 s | 1 LLM call per conversation |

For context, against the **prior n=100 jscore same-ruler table** (different answerers / different N, included for orientation only — *not a direct comparison*):

| reference lane | answerer | acc (jscore) | mean tokens |
|---|---|---:|---:|
| Mem0 (qwen) | qwen | 0.34 | ~540 |
| Mem0 (gpt-4o) | gpt-4o | 0.18 | ~540 |
| stele digest (qwen) | qwen | 0.43 | ~1,300 |
| stele digest (gpt-4o) | gpt-4o | 0.18 | ~1,300 |
| stele raw_fetch (gpt-4o) | gpt-4o | 0.13 | ~10,000 |

## What this tells us

1. **The compression works.** Both consolidators bring per-question prompts to
   the Mem0-token-budget neighborhood (433–552 vs Mem0's 540). The prior
   extractive run's ~15.8k tokens was the bake-off scaffold keeping episode
   text, not the chunker's fault. With consolidators that distill, the lane
   sits in the same token band as Mem0.

2. **Accuracy is in the right neighborhood.** 0.17–0.20 jscore is the same
   ballpark Mem0 and stele's `digest` land in under strict judging on
   gpt-4o-class answerers. So as a lane, this is *plausible* — not magic,
   but not broken either.

3. **The LLM consolidator did NOT beat the extractive one here.** Surprising
   given that Mem0's whole pitch is LLM distillation. Possible reasons, in
   declining order of likelihood:
   - **n=30 is tiny.** A 1/30 difference (0.167 vs 0.200) is one question.
   - **Our LLM prompt may underspecify the task.** 12 SPO facts with confidence
     might not capture the temporal / multi-hop reasoning LoCoMo actually
     tests. Mem0's ingest prompt is more elaborate and tuned over multiple
     iterations.
   - **The base chunker is one window per conversation.** With multi-session
     LoCoMo (~5k chars typical), one consolidator call gets diluted across
     sessions. Mem0 ingests session-by-session.
   - **gpt-4o-mini-on-gpt-4o-mini** — the consolidator and answerer being the
     same small model means the distillation isn't smarter than the answerer.

4. **Neither beats stele's `digest`** on the prior n=100 table (digest 0.18-0.43
   depending on answerer, at ~1.3k tokens). The token premium digest pays
   versus the consolidation lane buys real accuracy across the matrix. At
   n=30 with a single small answerer, that gap isn't visible yet, but the
   prior n=100 evidence is the more credible signal.

## Honest caveats

- **n=30, single answerer, single judge model.** Read this as a directional
  read on whether the lane compresses and answers, not a head-to-head verdict.
- **In-bake judge is not identical to `rejudge_aw.py --prompt strict-bench`.**
  The bake's judge is a similar strict-ish prompt written inline; for the
  cross-system comparison the `jscore` re-judge is the load-bearing number.
- **The follow-up to make this rigorous** (separately scoped — not bundled
  with this bake):
  1. Plumb `ConsolidationChunker` through `stele.core.config.IndexingConfig`
     so it's selectable via the public stele API (`chunker: "consolidation"`).
  2. Add contract tests for the consolidation lane across backends.
  3. Add a `consolidation_extractive` / `consolidation_llm` strategy to
     `answer_workflow.py` so it runs alongside `digest`/`raw_fetch` in the
     same matrix.
  4. Re-run on n=100 LoCoMo with 4 answerers, jscored, as a real lane in the
     stele-vs-Mem0 same-ruler table.

## Artifacts

- `benchmarks/runs/consolidation/consolidation-extractive-20260528T151537Z.json`
  (n=30, 73 KB, includes per-row `question`/`expected`/`answer`/`context`/`prompt_tokens` for re-judging)
- `benchmarks/runs/consolidation/consolidation-llm-20260528T151735Z.json`
  (n=30, 65 KB, same shape)
- `benchmarks/external/consolidation_bake.py` (driver)
- `benchmarks/external/consolidators/{extractive,llm}.py` (callables)

## Verdict

The lever moves. Not impressively, not magically — but it moves. With ~10 lines
of consolidator code, chunkshop's `ConsolidationChunker` lands in Mem0's
token-budget band at roughly Mem0-accuracy levels. Whether the lane is worth
the production plumbing (steps 1-4 above) depends on whether a tuned LLM
prompt + session-by-session consolidation can close the gap to `digest`'s
0.43 ceiling — and that's a real follow-up, not a one-afternoon bake.
