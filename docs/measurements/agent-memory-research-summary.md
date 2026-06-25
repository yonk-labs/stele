# Agent memory: which levers actually save tokens

A condensed digest of the memory-lever research behind the features in this
release. The full workstream (raw measurement logs, daily findings, the
deterministic simulations, and the four-model design reviews) is archived on the
`design/evolving-world-sim-benchmark` branch and synthesized in the
"Process Is the Memory" white paper. This doc is the readable summary; the
benchmarks named below are committed and reproducible.

## The question

Does an off-prompt memory layer remove *real* inference tokens for an agent, and
through which mechanism? We tested candidate "reuse" levers against both
deterministic policy simulations and real agent transcripts, holding the agent
policy constant so any delta is attributable to memory, not to a smarter agent.

## What we found (levers, ranked)

| Lever | Idea | Verdict |
| --- | --- | --- |
| Over-fetch reduction | Agent reads a whole file when one function was needed | **Real and large for coding agents** (~65% of edit-anchored read tokens). Capturable only with dependency-aware retrieval (AST / call-graph), not a naive window or vector RAG. Falsification: a naive span window recovered the needed context in 1 of 30 cases, dependency-aware in 30 of 30, both at ~6% of full-file tokens. |
| Evolving-fact memory | Supersede / consolidate facts that change underneath the agent | **Real where facts change** (conversational / assistant workloads). Storing a *verification method* beats storing the value: under efficiency pressure, a bare stale value scored 0% task accuracy versus 100% for no memory or for storing the re-derivation method. |
| Outcome / process reuse | Reuse an expensive multi-step result if its dependencies still hold | **Holds in simulation** (canary / tiered policy: a flat ~54% turn saving at zero false-valid reuse across 200 randomized drift schedules). **Did not reproduce on real coding transcripts**: coding agents rarely re-derive the same expensive outcome, so the recurrence the canary needs is scarce. |
| Re-read dedup | Serve a re-read file from memory | Real, but it moves data: it saves transfer, not reasoning tokens. |
| Command-level canary / verbatim redundancy | Reuse on a command fingerprint | Collapsed to ~0 once measured correctly (an earlier 29% reading was a fingerprint-conflation bug). |

## Two headlines

1. **For coding agents, the one real token lever is the retrieval lane**, specifically over-fetch, and capturing it needs *dependency-aware* bounded retrieval rather than similarity search. The bounded-retrieval feature is future work; the measurement tool that found and quantified the lever, `benchmarks/session_reuse_audit.py`, ships in this release.
2. **For evolving-world / conversational agents, the value is evolving-fact memory and (in simulation) outcome reuse.** The process-reuse machinery is implemented here behind an experimental flag, and its real-coding-agent value is explicitly unproven.

## What shipped from this research

- `Stele.memory` outcome reuse: canary / tiered / cost-gated, with settable TTL and an `is_stale` context gate (`core/reuse.py`, `core/memory.py`). Experimental; see the caveat above.
- `recall.shortcut`: a 3-tier cascade (outcome then context then procedure) for reusing prior work (`recall/shortcut.py`, design in `docs/specs/recall-shortcut-cascade-design.md`).
- `kind_filter` on memory search, implemented across all five storage backends.
- Context & Protocol Ledger memory kinds (`core/ledger.py`, schema in `docs/specs/ledger-record-spec.md`).

## Reproducing

Deterministic, no LLM required: `benchmarks/outcome_reuse.py`, `benchmarks/evolving_world.py`, `benchmarks/return_format.py`. Real-transcript over-fetch audit: `benchmarks/session_reuse_audit.py`. The full method and the four-model design reviews are in the white paper.

## Honest caveats

- Simulation results measure policy behavior, not production wall-clock or token cost.
- The over-fetch numbers come from coding-agent transcripts; the outcome-reuse simulation targets evolving-world / conversational workloads. These are different lanes and the numbers are not cross-comparable.
- Outcome reuse is unproven on real coding data and is flagged accordingly in code.
