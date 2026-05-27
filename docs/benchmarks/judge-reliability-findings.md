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

## Action items

- **Use `strict-bench` judging** (`rejudge_aw.py --prompt strict-bench`) for any
  reported accuracy. The default answer_workflow judge over-credits abstention.
- **Flag prior docs** (full-showcase, matrix) as gpt-4o-judge-inflated — see the
  caveat added to `full-showcase-2026-05-26/`.
- A proper fix is to change the answer_workflow judge prompt to strict-bench by
  default (separate code change).

## Caveats

- n=100 (one LoCoMo pass); strict-bench is a stricter-but-still-LLM judge, not
  human gold. The Mem0 genuine figure is an abstention-substring proxy (Mem0's
  runner didn't store full context/expected for a full strict re-judge).
- Raw artifacts: `model-matrix-2026-05-27/` + this run's
  `REJUDGE-gpt-4o-strict-bench.json` / `REJUDGE-gpt-5.5-default.json`.
