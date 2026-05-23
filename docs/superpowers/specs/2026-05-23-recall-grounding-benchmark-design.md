# Design — Recall Grounding Benchmark

Date: 2026-05-23
Status: Draft for review
Topic: Honest baselines on larger docs with a graded answer-equivalence judge,
to ground the `digest_search` strategy's defaults in evidence.

Sibling of `2026-05-22-digest-search-recall-design.md`. **This spec runs
FIRST**: the `digest_search` implementation plan depends on this study's
findings for its defaults and a ship/no-ship decision.

## Purpose

Establish whether the accuracy ceiling on compressed-context recall is the
*model* or the *method*, by measuring honest baselines (cold LLM, full doc, raw
N chunks) against the digest lanes on **larger documents**, graded by an
answer-equivalence judge. The point is to avoid chasing white whales: if the
cold LLM already answers, or if full-doc context can't, summarization tuning is
beside the point.

Outputs feed `digest_search`:
- chosen defaults: `report_backend`, `summary_floor_chars`,
  `summary_ceiling_chars`, `summary_chars_per_returned_char`,
  `min_corpus_tokens_to_summarize`, `soft_filter_weight`, `hint_focus`.
- a go/no-go: does any digest lane beat the raw-chunk baselines by enough
  (accuracy within noise) at a real token saving to justify shipping?

## Settled decisions (from brainstorming)

- **Corpora:** SCOTUS (new loader + authored gold) + LongBench-long (filter
  existing) + MHR/medical-hrt (existing gold, accuracy anchor to the bake-off).
- **Judge:** graded **0 / 0.5 / 1** answer-equivalence; a new `--judge-prompt`
  variant developed via `rejudge.py` replay.
- **Cost control:** core matrix first at fixed mid params; sweep only the
  winning digest lane. `n≈60/dataset` default, configurable.
- **Prerequisite:** raise the ~2000-char ingest truncation cap (config-gated).

## Corpora

| Corpus | Source | Gold | Role |
|---|---|---|---|
| **SCOTUS** | `pg-raggraph/benchmarks/scotus/*.md` (391 opinions) | **author ~40 Q+gold pairs** → `benchmarks/external/scotus_gold.yaml` | genuine long single-docs |
| **LongBench-long** | wired `musique`/`2wikimqa`/`multifieldqa_en`, filtered by the `length` field to the longest records | existing | multi-hop at length |
| **MHR (medical-hrt)** | `pg-raggraph/benchmarks/medical-hrt/gold.yaml` | existing | accuracy anchor; ties back to the 10-strategy bake-off |

New loader `load_scotus()` in `benchmarks/external/loaders.py`, following the
existing loader pattern (cache, honest-failure on missing source — never
fabricate). SCOTUS gold authored by hand; document the authoring method + date
in the yaml header (authoring bias is a known caveat).

## Prerequisite fix

`benchmarks/external/judge_lane.py:172-189` truncates ingested context to
~2000 chars. The `full_doc` and large-N-chunk baselines are dishonest on big
docs under that cap. Make the cap a config knob (default preserves current
behavior; the grounding run raises it). This is a hard prerequisite for the
large-doc lanes.

## Lanes

Added to `benchmarks/answer_workflow.py` `Strategy` type (line 35) + a case in
`_run_strategy()` (line 650). All digest lanes call `readable_report` via the
same summarizer the `digest_search` strategy will use.

**Baselines**
- `cold_llm` — no context; LLM answers from parametric knowledge. The grounding
  floor: is the model simply good/bad at these questions?
- `full_doc` — entire document(s) as context. The ceiling: best achievable with
  all information present (requires the truncation-cap fix).
- `chunks_10` / `chunks_20` / `chunks_30` — raw N retrieved chunks. The control
  family (raw "chunks" was the 53% bake-off control).

**Digest**
- `digest_regex` — `readable_report(backend="regex")` over the retrieved chunks
  (the 50% bake-off winner: hint-biased summary + hint-biased key_facts).
- `digest_spacy` — `readable_report(backend="spacy")`; opt-in, includes
  `correlate_facts` (worst isolated lane — measured here, not assumed).

**Scenarios d–f**
- `d_docreport_chunk1` — full-doc summary-with-facts as chunk 1 + other chunks.
- `e_docreport_on_chunks` — full-doc summary+facts+hints prepended to 10 chunks.
- `f_docreport_then_chunksummary` — full-doc report (facts+toc+hints), THEN
  summarize the chunks with hints; return that.

(The bake-off already settled per-chunk summarization loses; not re-run.)

## Judge

New graded **answer-equivalence** prompt, scored 0 / 0.5 / 1:
- **1** — candidate conveys the same answer to the question as the gold
  (paraphrase/format-agnostic).
- **0.5** — right core entity/value but incomplete, or correct plus a material
  wrong addition.
- **0** — wrong, or no answer.

World knowledge is neither required nor penalized — grade against gold
answer-equivalence, not fact coverage and not "the model happens to know it."
This sits between the existing `default` (world-knowledge-inclusive) and
`strict-bench` (gold-substring) prompts.

Implemented as a third `--judge-prompt` variant. Developed and A/B'd via
`rejudge.py` replay over stored `Report.json` rows — re-grade without re-running
retrieval+answer, so prompt iteration is cheap. Judge model: gpt-5-mini
(bake-off parity), configurable via `--judge-model`. GPT-5-family token handling
already exists (`answer_workflow.py:422`).

## Run plan & cost control

1. **Core matrix** — all lanes × 3 corpora at fixed mid params
   (`soft_filter_weight=0.5`, moderate budget), `n≈60/dataset`.
2. **Sweep** — only the winning digest lane: `soft_filter_weight` ∈
   {0.25, 0.5, 0.75} and the budget floor/ceiling + size-gate threshold.
3. Report the noise band (bake-off was n=30, ±~9pp; n≈60 tightens it).

`n` and the sweep grid are CLI-configurable so a quick smoke run is cheap.

## Metrics & output

Per lane × corpus:
- **graded accuracy** (mean of 0/0.5/1)
- **input tokens** (the cost axis)
- **latency** (must not add seconds — a hard constraint, not just a metric)
- **token reduction** vs `full_doc` and vs `chunks_30`

Reuse `benchmarks/runs/<date>/`. Extend the cross-benchmark consolidator
(`benchmarks/external/consolidate_answer_workflow.py`) with a grounding table:
accuracy vs token-cost per lane/corpus, with the cold/full-doc baselines as the
floor/ceiling rails.

## Out of scope

- The `digest_search` strategy code itself (sibling spec).
- chunkshop 0.5.0 native search (digest_search slice 2).
- pg-raggraph changes.
- Any non-deterministic answerer beyond the existing OpenAI-compatible judge.

## Deliverables checklist

- [ ] `load_scotus()` loader + `scotus_gold.yaml` (~40 authored pairs)
- [ ] LongBench-long length filter
- [ ] truncation-cap config knob
- [ ] new lanes (`cold_llm`, `full_doc`, `chunks_10/20/30`, `digest_regex`,
      `digest_spacy`, `d`/`e`/`f`)
- [ ] graded answer-equivalence `--judge-prompt` variant + rejudge support
- [ ] consolidator grounding table
- [ ] core-matrix run + winning-lane sweep
- [ ] findings written back as `digest_search` defaults + ship/no-ship call
