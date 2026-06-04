# Memory Modes: Consolidated Results (2026-06-02)

What the six-mode memory benchmark measured, in one place. Every headline number
is deterministic (regex, set-intersection, id-join, or closed-vocab state); the
LLM judge is never a headline. Numbers are labeled with sample size, source, and
the precondition that makes the mode work. Harness and usage:
[`benchmarks/external/memory_modes/README.md`](../../../benchmarks/external/memory_modes/README.md).
Endpoints: answerer Qwen @ 192.168.1.193, judge (unused for headlines) Gemma @ 192.168.1.133.

> Revision note (re-verified 2026-06-02): an earlier cut of this doc reported a
> few numbers that did not survive re-running. Three modes (fact, best_practice,
> guardrail) only work under a named precondition, and that precondition is now
> stated next to each. The resume margin was re-measured on a realistic corpus.
> The superseded numbers and what replaced them are listed at the bottom.

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

## Headline results

Every mode compares `memory_driven` against `no_memory` (floor) and, where it
applies, `prompt_stuffed` (put everything in the prompt). The shape to watch:
memory matching or beating the stuffed baseline at a fraction of the tokens. Each
mode names the precondition under which the number holds.

### Similarity recall

**precedent_recall** (synthetic, n=40, keyword recall): retrieve the right prior
task episode among semantically adjacent distractors.

| condition | triple_recall | hit@1 | tokens |
|---|---|---|---|
| no_memory | 0.00 | 0.00 | 1 |
| prompt_stuffed | 1.00 | n/a | 1435 |
| **memory_driven** | **1.00** | **1.00** | **~35** |

Matches the stuff-everything accuracy at a fraction of the tokens, with perfect
retrieval. Recall keys on the short task descriptor, not the chatty question.
Precondition: none beyond a descriptor-keyed query. This is the cleanest win.

**fact_recall** (real LoCoMo): recall the evidence turn for a question.
**Precondition: the vector leg (`--memory-vector`).**

| condition | recall@K | tokens | note |
|---|---|---|---|
| no_memory | 0.00 | 1 | |
| prompt_stuffed | n/a (exact_match 0.11 to 0.15) | ~15,000 | whole conversation |
| **memory_driven, vector** | **0.73 (n=100), 0.75 (n=40)** | **~90** | the headline |
| memory_driven, keyword only | 0.25 (n=40) | ~9 | AND-semantics whiffs on NL queries |

With the vector leg, memory surfaces the evidence turn ~0.73 to 0.75 of the time
at roughly 1/160th the tokens of stuffing the conversation. Keyword-only recall
manages only 0.25, because `plainto_tsquery` ANDs the query terms and a long
natural-language question rarely matches a short fact. `exact_match` is ~0.0
everywhere (LoCoMo golds are dates and short phrases the model rewords, e.g.
"May 7th" vs "7 May 2023"); `recall@K` is the honest, judge-free headline.

### Structured-state lookup

**resume_task_state**: current completion state of a named feature.
**Precondition: a realistically messy history** (a clean synthetic corpus where
events plainly state status is too easy and shows no margin).

| condition | state_accuracy | tokens | corpus |
|---|---|---|---|
| no_memory | 0.33 | ~3 | synthetic n=45, contradictory logs |
| prompt_stuffed | 0.58 | ~18 | synthetic n=45 |
| **memory_driven** | **1.00** | ~6 (no LLM) | synthetic n=45 |
| no_memory / prompt_stuffed | 0.25 | ~17 to 20 | real git, n=8 |
| **memory_driven** | **1.00** | ~15 (no LLM) | real git, n=8 |

When the raw log contains a loud stale event (a prod deploy later rolled back),
an LLM reading the full ordered history still mis-reports current state ~42% of
the time. The supersession head plus WorkGraph node carry the resolved truth and
score a deterministic 1.0, never inventing a status for an absent feature. On a
clean synthetic corpus (events that plainly say "shipped"/"descoped") all three
conditions hit 1.0 and there is no margin: that earlier 1.0-vs-0.81 result is
superseded.

### Enforcement

**skill_adherence** (synthetic, n=3): apply a learned "always do X" habit.
Small n, reproduces across runs; treat as directional.

| condition | application_rate | tokens |
|---|---|---|
| no_memory | 0.00 | 1 |
| prompt_stuffed | 1.00 | 159 |
| **memory_driven** | **1.00** | **23** |

**best_practice** (synthetic, n=18): surface the right learned suggestion among
same-domain siblings (suggest-only, no LLM). **Precondition: the vector leg.**

| condition | hit@1 | surfaced_recall | tokens |
|---|---|---|---|
| no_memory | 0.00 | 0.00 | 0 |
| **memory_driven, vector** | **1.00** | **1.00** | ~46 |
| memory_driven, keyword only | 0.00 | 0.00 | 0 |

The hardened corpus has multiple practices per domain plus paraphrased task
queries, so a domain filter alone is not enough: the right practice must be
discriminated from same-domain siblings by recall. With the vector leg it ranks
the right one first every time; keyword-only returns nothing (NL query, AND
semantics).

**guardrail_adherence** (synthetic, n=12): obey a learned "never do X" rule.
**Precondition: enforcement (check + repair), not injection.**

| condition | violation_rate | tokens |
|---|---|---|
| no_memory | 0.50 | 1 |
| prompt_stuffed | 0.42 | 285 |
| memory_driven (inject only) | 0.42 | 72 |
| **memory_enforced (check + repair)** | **0.00** | 72 |

The finding has two halves. Selecting the right rule by applicability domain is
cheap and works (72 tokens vs 285 for the whole rulebook). Injecting that rule
does NOT lower the violation rate: `memory_driven` ties `prompt_stuffed` at 0.42.
What works is `memory_enforced`: memory selects which deterministic checks apply,
the output is checked, and a hit triggers a targeted rewrite. That drives
violations to 0.0. Injection is dead; a checker is not.

## Dog-food run: this session's own history (real_trace)

The benchmark pointed at its own project's real git commits and state.

| mode | metric | memory_driven | baseline |
|---|---|---|---|
| precedent_recall (real commits) | hit@1 | **1.00** | stuffed found nothing |
| resume_task_state (8 deliverables) | state_accuracy | **1.00** @ ~15 tok | LLM 0.25 |

Memory recalled the right commit every time, and correctly reported all eight
deliverables, including flagging the benchmark-to-blog workflow as `absent`
(genuinely unbuilt) without hallucinating it as done.

## Cross-cutting findings

1. **Three modes need a precondition the original framing hid.** fact and
   best_practice need the vector leg (keyword AND-semantics whiffs on a natural
   language query). guardrail needs an enforcement step (injection does not
   enforce). resume needs a realistic corpus to show its margin. Named, not
   hidden.
2. **The token story is consistent where memory wins.** Precedent matches
   stuffing at a fraction of the tokens; fact at ~1/160th; skill at ~1/7;
   guardrail selection at ~1/4. Memory carries only what is relevant.
3. **Deterministic over judge.** Every headline is judge-free. The run that
   needed a judge most (LoCoMo answers) is exactly where it flapped 0.80 vs 0.22
   in earlier work, which is why `recall@K` carries the result.

## Caveats (read before quoting)

- **Preconditions are load-bearing.** Quote fact and best_practice only with the
  vector leg on; quote guardrail as `memory_enforced`, not inject-only; quote
  resume on a realistic corpus.
- **Small n on the enforcement modes.** guardrail (12), skill (3),
  best_practice (18) ship fixed-small corpora; directional, not definitive.
- **`exact_match` is confounded on real conversational data** (date and phrasing
  variance). `recall@K` is the honest fact-recall headline.
- **real_trace coverage is partial.** fact (LoCoMo), guardrail (real rules),
  precedent and resume (this session's git) mine real data; skill and
  best_practice are synthetic-only until a trace miner lands.

## Superseded numbers (what changed and why)

- fact_recall "0.75 on real LoCoMo" stated without qualifier -> 0.73 to 0.75
  **with the vector leg**; keyword-only is 0.25. The original number was a vector
  run that was not labeled as such.
- resume_task_state "1.00 vs 0.81 (synthetic n=16)" -> superseded. That corpus
  was too easy; all conditions score 1.0 on it. The real margin is 1.00 vs 0.58
  (prompt_stuffed) / 0.33 (no_memory) on a hardened n=45 corpus, and 1.00 vs 0.25
  on real git.
- best_practice "surfaced_recall 1.0 (n=3)" -> replaced by hit@1 1.0 (n=18) with
  same-domain distractors; the old metric could not fail because the domain
  filter always returned the domain's practice.
- guardrail_adherence "open finding, injection flat at n=5" -> resolved.
  Injection is confirmed dead (0.42); `memory_enforced` reaches 0.0.

## Honesty boxes (verbatim from each mode)

- **fact_recall**: measures session-aware recall of the evidence turn without the
  transcript in context; does NOT test multi-hop/open-ended, nor memory-beats-RAG
  when the document is present (it does not, ~0.10 vs ~0.65).
- **precedent_recall**: measures retrieving the right prior episode + its
  tool/result/state; episodes are synthetic until a real-trace miner derives gold.
- **resume_task_state**: measures correct current state from the supersession head
  + WorkGraph node, and not inventing a status; does not score NL phrasing.
- **guardrail/skill/best_practice**: measure injected-rule compliance / application
  / surfacing by deterministic checks; guardrail additionally measures whether a
  check+repair step enforces what injection cannot.
