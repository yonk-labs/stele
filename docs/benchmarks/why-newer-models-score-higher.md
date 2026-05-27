# Why newer models score higher on the *same* retrieved context

stele's retrieval is deterministic: for a given query it returns the same
chunks, the same extracted facts, and the same digest regardless of which LLM
reads them. Yet swapping the **local quantized Qwen3-Coder + gemma** stack for
**gpt-4o-mini + gpt-4o** lifted almost every lane — on identical context. This
note explains why, and why one lane (`digest`) was the exception.

## The observation (LoCoMo, 18 QA, same retrieved context)

| Strategy (context held constant) | local: Qwen+gemma | matched: gpt-4o-mini+gpt-4o | Δ |
|---|---:|---:|---:|
| search_first (raw top chunks) | 0.278 | **0.611** | **+0.33** |
| adaptive | 0.444 | 0.667 | +0.22 |
| summary_only | 0.278 | 0.556 | +0.28 |
| full-context (all turns) | 0.556 | 0.667 | +0.11 |
| **digest** (summary+facts+top-5) | 0.500 | **0.444** | **−0.06** |

LongMemEval moved the same way (full-context 0.50→0.75; digest 0.75→0.83). The
verbatim lanes jumped; digest barely moved.

## Why a better model extracts more from the *same* text

1. **Grounded extraction / instruction-following.** The task is "answer using
   only this context." A stronger general-assistant model reliably locates and
   lifts the answer span from the provided chunks. The weaker model misreads it,
   or abstains ("I don't have enough information") even when the answer is right
   there. Same chunks, different extraction skill.
2. **Model specialization mismatch.** The local answerer was
   `Qwen3-Coder` — a **code** model, not tuned for conversational / temporal QA.
   gpt-4o-mini is a general assistant. On dialogue-recall questions the coder
   model is out of its domain; the general model is in it.
3. **Quantization precision loss.** The local model was **int4-quantized**.
   4-bit weights degrade exactly the fine-grained reasoning and recall these
   needle questions need ("which day", "sunset vs sunrise"). The OpenAI models
   run full precision.
4. **Long-context competence.** full-context feeds 8–15k tokens. Stronger models
   track detail across long inputs better, so full-context rose even though the
   bytes were identical.
5. **Less hallucination.** Stronger models stay anchored to the supplied context
   instead of confabulating, which matters most when the answer *is* present and
   just needs to be read out.

## Why `digest` was the exception (the important part)

`digest`'s context is a **lossy summary** (`lede.readable_report` — a hint-biased
extractive summary + an extracted-facts section + the top-N raw chunks). The
summary is produced by a deterministic summarizer **before any LLM sees it**, so:

- The **information ceiling is set by the summary, not the answerer.** If the
  summary paraphrased "sunset" into "sunrise" or "December 2022" into "last
  month," a better answerer can't recover the lost precision — it faithfully
  reports the distorted detail. (Diagnosed directly: 6/10 LoCoMo digest misses
  had *sufficient* context but imprecise answers.)
- Verbatim lanes (raw chunks, full context) hand the model the **exact text**,
  so model improvements *compound* — a smarter reader extracts more. A
  pre-summarized context gives both weak and strong readers the **same lossy
  input**, so they converge to the same ceiling. Hence digest stayed flat while
  chunks/full-context climbed.

**One-line takeaway:** model upgrades compound with *verbatim* context but are
**capped by lossy pre-summarization**. Summarize to *denoise* long histories
(LongMemEval, where digest still won); keep raw text for *precise* recall
(LoCoMo), and there the better model — not the summary — is what you want to feed.

## Honest caveats

- **Two variables moved at once.** Both the *answerer* (Qwen→gpt-4o-mini) and the
  *judge* (gemma→gpt-4o) changed, so part of the uplift is a fairer/stricter
  judge, not only a better answerer. A clean isolation (hold the judge fixed,
  swap only the answerer) would separate the two; the direction is unambiguous
  but the exact split is not.
- **Small N** (18 LoCoMo QA): treat deltas as directional.
- This is about *reading* retrieved context. It says nothing about which system
  *retrieves* better — that's the separate Mem0 head-to-head.
