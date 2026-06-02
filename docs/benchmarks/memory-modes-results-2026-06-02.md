# Memory Modes: Consolidated Results (2026-06-02)

What the six-mode memory benchmark measured, in one place. Every headline number
is deterministic (regex, set-intersection, id-join, or closed-vocab state); the
LLM judge is never a headline. Numbers are labeled with sample size and source.
Harness and usage: [`benchmarks/external/memory_modes/README.md`](../../benchmarks/external/memory_modes/README.md).
Endpoints: answerer Qwen @ 192.168.1.193, judge (unused for headlines) Gemma @ 192.168.1.133.

## The framing: memory is not RAG

Memory and RAG only diverge when the history is no longer in the prompt, when a
fact has changed, or when behavior must be enforced. A memory store used as a
naive retriever, on a task where the whole document is also present, loses to
document RAG, and it should. The baseline (LoCoMo, n=40):

| lane (population to engine) | jscore |
|---|---|
| doc_rag (raw doc to chunk-hybrid) | 0.675 |
| mem_fragment (fragments to memory) | 0.125 |
| facts_to_chunks (extracted to chunk) | 0.050 |
| mem_extracted (extracted to memory) | 0.000 |

That number is real and stays in the record. It is the wrong question. The six
modes below measure the regime where memory is the only source.

## Headline results (full run, n as noted, vector leg on)

Every mode compares `memory_driven` against `no_memory` (floor) and
`prompt_stuffed` (put everything in the prompt). The shape to watch: memory
matching or beating the stuffed baseline at a fraction of the tokens.

### Similarity recall

**precedent_recall** (synthetic, n=40): retrieve the right prior task episode.

| condition | triple_recall | hit@1 | tokens |
|---|---|---|---|
| no_memory | 0.00 | 0.00 | 1 |
| prompt_stuffed | 1.00 | n/a | 1435 |
| **memory_driven** | **1.00** | **1.00** | **179** |

Match the stuff-everything accuracy at ~8x fewer tokens, with perfect retrieval.

**fact_recall** (real LoCoMo, n=40): recall the evidence turn for a question.

| condition | recall@K | exact_match | tokens |
|---|---|---|---|
| no_memory | n/a | 0.00 | 1 |
| prompt_stuffed | n/a | 0.15 | 15,631 |
| **memory_driven** | **0.75** | 0.00 | **92** |

Memory surfaces the evidence turn 75% of the time at 1/170th the tokens of
stuffing the whole conversation. `exact_match` reads 0.0 (and stuffing only 0.15)
because LoCoMo gold answers are dates and short phrases the model rewords
("May 7th" vs "7 May 2023"); `recall@K` is the honest, judge-free headline.
Synthetic fact_recall (n=6, clean golds): memory_driven exact_match 1.0,
recall@K 1.0 at 67 tokens.

### Structured-state lookup

**resume_task_state** (synthetic, n=16): current completion state of a named feature.

| condition | state_accuracy | false_state | tokens |
|---|---|---|---|
| no_memory | 0.81 | 0.00 | 6 |
| prompt_stuffed | 0.81 | 0.00 | 12 |
| **memory_driven** | **1.00** | **0.00** | 6 (no LLM) |

Perfect, deterministic, beats the LLM conditions, never invents a status.

### Enforcement

**skill_adherence** (n=3): apply a learned "always do X" habit.

| condition | application_rate | tokens |
|---|---|---|
| no_memory | 0.00 | 1 |
| prompt_stuffed | 1.00 | 159 |
| **memory_driven** | **1.00** | **23** |

**best_practice** (n=3): surface a learned suggestion (no LLM, suggest-only).

| condition | surfaced_recall | tokens |
|---|---|---|
| no_memory | 0.00 | 0 |
| **memory_driven** | **1.00** | 25 |

**guardrail_adherence** (synthetic n=5): obey a learned "never do X" rule.

| condition | violation_rate | tokens |
|---|---|---|
| no_memory | 0.40 | 1 |
| prompt_stuffed | 0.40 | 285 |
| memory_driven | 0.40 | 72 |

The domain-selection fix works (memory_driven carries the right rules at 72
tokens vs 285 stuffed), but injecting a rule did not lower the violation rate at
this small n. This is an open finding, not a win: see caveats.

## Dog-food run: this session's own history (real_trace)

The benchmark pointed at its own project's real git commits and state.

| mode | metric | memory_driven | baseline |
|---|---|---|---|
| precedent_recall (9 real commits) | hit@1 | **1.00** @ 52 tok | stuffed 0.0 @ 478 |
| resume_task_state (8 deliverables) | state_accuracy | **1.00** @ 15 tok | LLM 0.25 |

Memory recalled the right commit every time, and correctly reported all eight
deliverables, including flagging the benchmark-to-blog workflow as `absent`
(genuinely unbuilt) without hallucinating it as done.

## Cross-cutting findings

1. **The token story is consistent.** Where memory wins, it wins at a small
   fraction of the prompt-stuffing tokens (8x on precedent, 170x on fact-recall
   vs whole-conversation stuffing, ~7x on skill), because it carries only what is
   relevant.
2. **Similarity recall whiffs on enforcement and on chatty queries.** Guardrails
   cannot be selected by query similarity (the task shares no words with the
   rule), so selection is by applicability domain. Recall keyed on a chatty
   question fails under keyword search (`plainto_tsquery` ANDs terms), so recall
   keys on the task descriptor or the vector leg.
3. **Deterministic over judge.** Every headline is judge-free; the run that
   needed the judge most (LoCoMo answers) is exactly where it flapped 0.80 vs
   0.22 in earlier work, which is why `exact_match`/`recall@K` carry the result.

## Caveats (read before quoting)

- **Small n on the enforcement modes.** guardrail (5), skill (3), best_practice
  (3) ship fixed-small corpora; treat them as directional. Scale the rulebook
  before quoting adherence numbers.
- **Guardrail adherence is unresolved.** Selecting the right rule is solved;
  making the model obey an injected "never" is not, at n=5. Needs a bigger task
  set and likely a stronger enforcement step than prompt injection.
- **`exact_match` is confounded on real conversational data** (date and phrasing
  variance). `recall@K` is the honest fact-recall headline.
- **real_trace coverage is partial.** fact (LoCoMo), guardrail (real rules),
  precedent and resume (this session's git) mine real data; skill and
  best_practice are synthetic-only until a trace miner lands.

## Honesty boxes (verbatim from each mode)

- **fact_recall**: measures session-aware recall of the evidence turn without the
  transcript in context; does NOT test multi-hop/open-ended, nor memory-beats-RAG
  when the document is present (it does not, ~0.10 vs ~0.65).
- **precedent_recall**: measures retrieving the right prior episode + its
  tool/result/state; episodes are synthetic until a real-trace miner derives gold.
- **resume_task_state**: measures correct current state from the supersession head
  + WorkGraph node, and not inventing a status; does not score NL phrasing.
- **guardrail/skill/best_practice**: measure injected-rule compliance / application
  / surfacing by deterministic checks; do not judge semantic style rules a regex
  cannot, nor cross-session persistence of a one-correction fix.
