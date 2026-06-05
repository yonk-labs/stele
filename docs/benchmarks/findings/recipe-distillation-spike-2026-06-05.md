# Recipe Distillation Spike: Skills-as-Recipes, Provenance, Materiality (2026-06-05)

A diagnostic spike testing whether distilled `skills` can become **agent-skill-shaped
recipes** (a named, triggerable how-to that combines precedents + best practices +
facts), instead of the one-line `instruction` memories `distill.skills()` returns
today. Along the way it measures three things the shipped pipeline never has: real
precedent yield, memory provenance/authorship, and per-item materiality.

**Status:** throwaway diagnostic. The spike scripts live under
`benchmarks/runs/recipe-distiller-spike/` (gitignored) and are **not** part of the
package. The durable artifact is the proposed design in
[`docs/specs/recipe-distiller-design.md`](../../specs/recipe-distiller-design.md).
Nothing here changed shipped behavior.

## Setup

- **Corpus:** the 16 most recent **real** stele Claude Code sessions (~70 MB of
  transcripts), parsed by the shipped `parse_claude_jsonl` + `reduce_event`.
- **Scout (extraction):** the real, unchanged v0.6.2 `extract_session_memories`
  (`Intel/Qwen3-Coder-Next-int4-AutoRound`, local).
- **Judge (materiality):** `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit`, local. The scout
  and judge LLMs are separate knobs (default same; deliberately split here).
- **Embedder:** the real fastembed memory embedder (768-dim), for cross-kind
  clustering and provenance matching.
- **Windows:** 6/session (the shipped `from_session` default is 3; both reported).

## Finding 1: precedent scarcity was a corpus artifact, not an extraction defect

The live `.stele/memory_stele.db` held **4** `decision` memories against 72,751
facts, which looked like a precedent-extraction failure. It is not. That store is
LoCoMo / LongMemEval / RAGBench benchmark conversation, where engineering
"decisions" do not occur. On **real agent work** the v0.6.2 extractor yields
precedents fine:

| | benchmark-chitchat store | real sessions, faithful (3 windows) | real sessions, extended (6) |
|---|---|---|---|
| `decision` (precedents) | 4 | **25** | **37** |

Roughly 1.5 decisions/session at the shipped default. The precedent leg of a recipe
is populated. (This run does not isolate pre-vs-post #59 on `decision`; it shows the
absolute yield is healthy, which is what matters for building recipes.)

### Full kind yield (real sessions)

| kind | faithful (3 win) | extended (6 win) |
|---|---|---|
| fact | 80 | 145 |
| instruction | 56 | 106 |
| pitfall | 41 | 83 |
| preference | 24 | 51 |
| workaround | 24 | 50 |
| decision | 25 | 37 |
| **total** | **250** | **472** |

Two side findings: **27 of 96 windows (28%) extracted zero memories**, and the
shipped 3-window cap **under-mines large multi-MB sessions** (extending to 6 windows
nearly doubled yield, 250 -> 472). The corpus-average ~1.42 windows/session holds,
but the recent sessions here are large outliers where the cap leaves memory on the
table.

## Finding 2: extraction discards authorship, and authorship is authority

The extractor emits `{kind, summary, detail}` and nothing about **who said it**. A
human directive ("always run the trio before commit") and an agent musing ("Phase 4
must preserve the lazy-import pattern") land in the store as indistinguishable
`instruction` memories. They are not equal: a human directive outranks an agent
opinion.

Provenance is recoverable ground truth from the transcript: `user` turns are the
human, the first `user` turn is the original prompt, `assistant`/`tool`/`result`
turns are the agent. Attributing each extracted memory to its source turn's role
(naive token-overlap, M0) gives:

| kind | human | prompt | agent | reading |
|---|---|---|---|---|
| instruction | 33 | 2 | 66 | 62% of "rules" are the agent talking to itself |
| decision | 0 | 0 | 37 | every precedent is agent-authored (expected) |
| preference | 8 | 1 | 40 | the human ones are the real best-practices |
| fact | 10 | 4 | 130 | mostly agent observation |

## Finding 3: the attribution fix is max-authority, not better matching

Naive token-overlap is agent-biased: a terse human instruction is restated at length
by the agent, so the memory matches the agent's longer turn. Re-attributing the same
472 memories (no re-extraction, deterministic re-parse + fastembed):

| method | person-authored (all kinds) | instruction human |
|---|---|---|
| M0 token-overlap (baseline) | 14% | 33% |
| M1 cosine argmax (better matching) | **14%** | **32%** |
| M2 cosine + max-authority @0.50 | **42%** | **55%** |
| M2 cosine + max-authority @0.40 | 52% | 61% |

The lesson: better *matching* (M1) does nothing, because a faithful agent restatement
really is the closest text. The fix is **authority = max over all contributing turns**
(if any user turn contributed above a similarity floor, the memory is human-authored).
The recovered agent->human flips are genuine directives ("Release workflow: branch off
main, bump version, add CHANGELOG, then PR"; "Always validate prompt changes against a
real multi-session transcript"; "Never commit to the active branch").

**Caveat (honest):** the 0.50 floor over-credits some agent-experienced ops items to
human (e.g. "Edit to CHANGELOG.md failed: file not read first" flips to human because
the session's human turns discussed CHANGELOG closely enough to clear the floor). The
floor is a precision/recall dial with no labeled set to pin it. Turn-indexing is the
intended structural successor, but a single-source, post-hoc prototype of it
underperformed the floor (see Mitigations, run E), so it is not yet a validated win.
The honest unblock is a hand-labeled calibration set. See the design doc.

## Finding 4: a hybrid materiality judge cuts genuine noise

Most extracted memories are session bookkeeping ("GitHub issues #6-#11 created",
"Git commit failed with nothing to commit"), not durable knowledge. A two-pass judge
(deterministic prefilter keeps human/prompt-authored or cross-session-recurring items
for free; the LLM judge runs only on the agent-authored singletons) cut scout output
to ~52-75% across runs. Representative drops:

- "The from_session/from_messages facades exist at lines 186..." (trivial location)
- "Live store contains 72,751 facts..." (transient snapshot)
- "Always run tests before committing." (obvious, not stele-specific)

**The judge is nondeterministic.** Identical input, two runs: kept 132 then 154 (temp
0, but vLLM batching is not bit-deterministic). The deterministic prefilter never
varies; only the LLM judge does. This argues for keeping as much as possible on the
deterministic side and treating judge verdicts as advisory.

## Finding 5: cross-kind recipes compose

Clustering survivors on real embeddings (cross-kind by design) and composing each
cluster yielded **52-58 coherent proto agent-skills**, e.g. "Strict Test-Driven
Development Workflow", "Executing a version release workflow", "Managing Git-Pinned
Chunkshop Dependencies", "Preventing Deadlocks from Session Advisory Locks". Each has
a `use when` trigger and buckets its members into steps/rules, don't/fix, best
practices, precedents, and facts. They are recognizably the project's own repeated
workflows, not generic.

- **Over-merge was a clustering-granularity bug, not a noise problem.** At threshold
  0.60 a 31-item TDD blob was rejected as incoherent; splitting oversized clusters at
  a tighter 0.74 turned it into a clean TDD skill, all lines correctly human-authored
  after the provenance fix.
- The composer **fails honestly**: the remaining ~25 incoherent clusters are small
  same-kind fact grab-bags it refuses to force into a fake how-to.

## Finding 6: a review-queue + priority governance falls out

Each item (and each composed skill) carries governance fields so an external harness
can curate: `is_human` (all kinds), `review_state` (new | accepted | rejected; the
judge seeds machine-`rejected`, the harness promotes `accepted`), and `priority`
(low | med | high from a transparent score: human +2 / prompt +1, recurs>=2 +1,
recurs>=3 +1, instruction|decision +1). On the run:

```
review_state : new 355   rejected 117 (rejected_by=judge)
priority(new): high 71   med 123   low 161
skills (58)  : high 31   med 21   low 6   |   human-authored 51/58
```

Consumers can `skip rejected`, review only `new`, and sort `accepted` by `priority`.
Priority is only as accurate as the provenance under it, which is why `review_state`
is the safety net: nothing is trusted until accepted.

## Mitigations measured (follow-up experiments)

Two of the caveats below were probed directly.

**Judge nondeterminism is small and handled (run F).** The materiality judge run 3x on
the identical 271 to-judge items kept 136 / 133 / 138 (spread 5, ~2% of the kept
count). 261/271 verdicts (96%) were unanimous; only 10 (4%) wobbled, and they are
genuinely borderline ("Never trust a single judge", "Always verify API against docs").
Best-of-3 majority collapses the spread to one stable answer (135 keeps). The
deterministic prefilter (201/472) never wobbles. So: keep most items off the judge,
majority-vote the rest, and the residual nondeterminism is ~4% of the judged minority.

**Turn-indexing, as a single-source post-hoc prototype, did NOT beat the floor (run
E).** Asking the LLM to point each memory at its originating turn (role then by
deterministic lookup) gave **11%** person-authored vs the floor's **42%**, and 32% of
pointers landed on a turn that barely contains the memory. Single-source pointing
defaults to the agent's (longer) turn and discards the max-authority rule that made the
floor work; post-hoc pointing on a reduced window is also just unreliable. Lesson:
turn-indexing only wins if it (a) runs DURING extraction, (b) allows multiple source
turns with max-authority, and (c) is validated. None of that is shown. The floor
heuristic remains the best-validated option so far, and the honest unblock is a
hand-labeled calibration set, not a presumed structural win.

## Caveats

- **Single, small corpus:** 16 stele-only sessions. Cross-project generalization
  untested.
- **Provenance floor uncalibrated:** no hand-labeled set; @0.50 is eyeballed and
  over-credits some ops items. A single-source turn-indexing prototype underperformed it
  (run E), so the real unblock is a labeled calibration set, not a presumed structural
  fix.
- **Judge nondeterminism is small and handled:** survival moves run-to-run, but the
  wobble is ~4% of judged items and best-of-3 majority stabilizes it (run F).
- **Throwaway harness:** the scripts are gitignored and not reproducible from
  committed code; promote them to a committed benchmark only if the feature is built.

## What this validates

The full thesis holds on real data: skills-as-recipes compose, precedents are
healthy, the materiality judge cuts real noise, provenance/authority works once
attribution is fixed, and a review/priority governance layer emits cleanly. The one
heuristic weakness (attribution floor) has a clear structural successor. Next step is
the proposed design, not a shipped feature.
