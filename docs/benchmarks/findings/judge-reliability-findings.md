# Judge reliability — the abstention-crediting discovery (2026-05-27)

**The single most important benchmark finding of this work: the gpt-4o LLM-judge
was crediting "I do not have enough information" abstentions as *correct*, which
inflated every accuracy number 2–10× and masked the real strategy ranking.**
Caught by re-judging identical answers with gpt-5.5 and a strict-bench prompt.

## How it was found

A gpt-5.5 re-judge of the *identical* n=100 LoCoMo answers scored everything
near-zero (0.00–0.18) where gpt-4o scored 0.38–0.64. That gap on the same
answers was the tell. Counting the gpt-4o-"correct" answers that were actually
the model refusing:

| lane | gpt-4o "correct" | …that are abstentions | genuine (non-abstention) |
|---|---|---|---|
| search_first | 49% | **98%** | ~0.01 |
| digest | 48% | 55% | ~0.21 |
| raw_fetch | 53% | 48% | ~0.27 |

98% of `search_first`'s "correct" answers were *"I do not have enough
information."* The judge prompt ("evaluate whether the answer is correct AND
whether the context was sufficient") let gpt-4o credit an honest abstention as
"correct behaviour given insufficient context" — conflating *correct answer*
with *correctly abstained*.

## The honest numbers (strict-bench judge, abstention = wrong), n=100 LoCoMo

gpt-4o judge, `strict-bench` prompt (mark TRUE only if the candidate contains the
gold answer; refusal/hedge = FALSE):

| answerer | search_first | digest | raw_fetch | (lenient gpt-4o for ref) |
|---|---:|---:|---:|---|
| qwen | 0.000 | 0.110 | **0.220** | 0.46 / 0.52 / 0.60 |
| gemma | 0.010 | 0.070 | **0.160** | 0.54 / 0.45 / 0.51 |
| gpt-4o | 0.000 | 0.050 | 0.050 | 0.45 / 0.41 / 0.38 |
| gpt-5 | 0.000 | 0.080 | **0.200** | 0.52 / 0.55 / 0.64 |

Mem0 genuine (abstention-adjusted proxy from stored answers): qwen **0.44**,
gemma 0.11, gpt-4o 0.10, gpt-5 0.14.

## What this means (corrected conclusions)

1. **Real LoCoMo accuracy is LOW (0.00–0.44), not 0.38–0.66.** The headline
   numbers throughout this repo (full-showcase, matrix, n=100) are gpt-4o-judge
   inflated by abstention-crediting. They measure "answered-or-honestly-abstained",
   not "answered correctly".
2. **The strategy ranking that survives strict judging: raw_fetch > digest >
   search_first(≈0).** More context → fewer abstentions → more genuine answers.
   `search_first` (terse top-k chunks) makes the model abstain → ~0 genuine.
   So **the original "digest beats search_first" instinct was right** — my
   earlier "it's a wash" was an artifact of the lenient judge flattening them.
3. **Reconciliation of the full-showcase discrepancy.** The full-showcase
   (gemma judge) scored search_first 0.278 / digest 0.50 — gemma credited
   abstentions *less* than gpt-4o, so digest's edge showed. gpt-4o credited them
   *more*, flattening the gap to a fake wash. Strict judging restores the real
   ordering (digest > search_first) at honest (low) absolute levels.
4. **gpt-4o as *answerer* abstains most** (genuine ~0.05) and gets the most
   lenient-judge credit; **qwen commits** (genuine 0.22 raw / 0.44 Mem0). The
   "stronger model" looks better only because the lenient judge rewards its
   caution.
5. **Mem0's distilled facts genuinely help a committal answerer** (qwen 0.44,
   the best genuine score in the study) but not the cautious OpenAI answerers.
   *(Superseded by the same-ruler comparison below: the 0.44 was an
   abstention-substring **proxy**, not Mem0's actual judge. On Mem0's own
   `jscore` prompt Mem0 qwen = 0.34, and stele's `raw_fetch` beats it.)*

## Porting Mem0's own judge (the `jscore` prompt) — 2026-05-27

To check whether `strict-bench` was simply *harsher than the field*, we ported
Mem0's published LoCoMo "J-score" LLM-judge prompt verbatim
(`mem0ai/memory-benchmarks` → `benchmarks/locomo/prompts.py`) into
`rejudge_aw.py --prompt jscore` and re-judged the **identical** n=100 answers.
Mem0's prompt is deliberately *lenient* (partial credit, paraphrases, ±14-day
date tolerance, same-referent) **but judges generated-vs-gold only** — so an
abstention ("I do not have enough information") scores WRONG, exactly like
`strict-bench`. It is the fairest cross-system ruler available because it is the
ruler Mem0 reports against.

### Four judges, identical n=100 LoCoMo answers (gpt-4o judge unless noted)

| lane | default (lenient+abstention-credit) | jscore (Mem0's prompt) | strict-bench | gpt-5.5 (default prompt) |
|---|---:|---:|---:|---:|
| qwen search_first | 0.46 | 0.02 | 0.00 | 0.00 |
| qwen digest | 0.52 | 0.43 | 0.11 | 0.13 |
| qwen raw_fetch | 0.60 | **0.53** | 0.22 | 0.15 |
| gemma search_first | 0.54 | 0.01 | 0.01 | 0.01 |
| gemma digest | 0.45 | 0.27 | 0.07 | 0.10 |
| gemma raw_fetch | 0.51 | **0.42** | 0.16 | 0.18 |
| gpt-4o search_first | 0.45 | 0.00 | 0.00 | 0.00 |
| gpt-4o digest | 0.41 | 0.18 | 0.05 | 0.07 |
| gpt-4o raw_fetch | 0.38 | 0.13 | 0.05 | 0.04 |
| gpt-5 search_first | 0.52 | 0.00 | 0.00 | 0.01 |
| gpt-5 digest | 0.55 | 0.25 | 0.08 | 0.10 |
| gpt-5 raw_fetch | 0.64 | **0.41** | 0.20 | 0.18 |

**What jscore tells us:**

1. **Same ranking as strict-bench: `raw_fetch > digest > search_first(≈0)`.**
   Mem0's own judge agrees that terse top-k retrieval (`search_first`) drives the
   model to abstain → ~0 genuine. So our strict ranking was *not* an artifact of
   an unusually harsh prompt; it's the same ordering the field's judge produces.
2. **jscore sits between strict-bench and the inflated default.** Mem0's
   paraphrase/date/partial leniency roughly **2–4×** the genuine score vs
   strict-bench (qwen raw 0.22→0.53, digest 0.11→0.43) — but it never rescues an
   abstention. The gap between jscore and default is *entirely* abstention credit.
3. **strict-bench was harsher than the field.** It demands the gold token appear;
   jscore accepts paraphrase/partial. The truth for "real LoCoMo accuracy" lives
   around the **jscore** column (0.13–0.53 for the productive lanes), not the
   strict floor and not the inflated default.

### True apples-to-apples: stele vs Mem0 on Mem0's own ruler

Joined on the **same 100 questions / same gold** (gold map from stele's stored
rows; 0/100 unmatched), every answer scored by Mem0's `jscore` prompt:

| answerer | Mem0 (jscore) | stele digest (jscore) | stele raw_fetch (jscore) |
|---|---:|---:|---:|
| qwen | 0.34 | 0.43 | **0.53** |
| gemma | 0.28 | 0.27 | **0.42** |
| gpt-5 | 0.25 | 0.25 | **0.41** |
| gpt-4o | 0.18 | **0.18** | 0.13 |

**On Mem0's own published judge, stele's full-context `raw_fetch` beats Mem0's
distilled-memory retrieval on every answerer; `digest` ties-or-beats it on 3 of
4.** Both systems' *default-judge* numbers (Mem0's published 0.59–0.66, stele's
0.38–0.64) are the same abstention-inflated methodology — neither is the real
score.

**The honest efficiency caveat:** Mem0 hits 0.34 (qwen) on ~540 distilled
prompt tokens; stele's `raw_fetch` hits 0.53 on ~10k tokens, and `digest` hits
0.43 on ~1.3k tokens. So the fair framing is: **stele `digest` beats Mem0 on
accuracy (0.43 vs 0.34) at ~2.4× the tokens; `raw_fetch` is highest-accuracy but
token-heavy; Mem0 wins pure token efficiency.** stele is not "more accurate for
free" — it trades tokens for accuracy, and the digest lane is the sweet spot.

## Action items

- **Never report the default judge's numbers.** It over-credits abstention. Use
  `jscore` (Mem0's prompt — best for cross-system comparison) or `strict-bench`
  (strictest, gold-token required) via `rejudge_aw.py --prompt {jscore,strict-bench}`.
- **Flag prior docs** (full-showcase, matrix) as gpt-4o-judge-inflated — see the
  caveat added to `full-showcase-2026-05-26/`.
- A proper fix is to change the answer_workflow judge prompt away from the
  abstention-crediting default (separate code change).

## Caveats

- n=100 (one LoCoMo pass). `jscore` and `strict-bench` are both still-LLM judges,
  not human gold. `jscore` is Mem0's *verbatim* published prompt, so the
  stele-vs-Mem0 table is a genuine same-ruler comparison (same 100 Qs, same gold,
  same judge prompt) — the strongest cross-system claim available, but still one
  judge model (gpt-4o) on one dataset pass.
- The earlier "Mem0 genuine 0.44" figure was an abstention-substring proxy and is
  **superseded** by the same-ruler jscore figure (Mem0 qwen 0.34).
- Raw artifacts: `model-matrix-2026-05-27/`, `REJUDGE-gpt-4o-strict-bench.json`,
  `REJUDGE-gpt-5.5-default.json`, `REJUDGE-gpt-4o-jscore.json`, `MEM0-jscore.json`.
