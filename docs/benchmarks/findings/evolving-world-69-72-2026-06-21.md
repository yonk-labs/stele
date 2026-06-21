# Evolving-World Agent Simulation: #69 / #72 findings (2026-06-21)

Lab oracle for the cross-session staleness problem. Reproducible, in-repo,
complements the downstream bento harness (which is the gated real-consumer
confirm). Design: [evolving-world-simulation-benchmark-design.md](../../specs/evolving-world-simulation-benchmark-design.md).

## What it is

A long-running agent runs hundreds of sessions over compressed virtual time while
a world-simulator flips facts the agent did not cause (upgrades, deprecations).
The agent policy is held CONSTANT across arms; only the memory subsystem varies,
so any delta is the memory's doing. Two oracles: agent-side value-recall, and a
store-side staleness probe (the #72 gate: is a superseded value still active?).

Three lanes:
- `benchmarks/evolving_world.py` deterministic headline + fix arm (postgres).
- `benchmarks/evolving_world.py --fix` adds the `stele-role` fix arm.
- `benchmarks/evolving_world_llm.py` real-LLM lane (gemma-26B), the only lane that
  can see extraction-induced staleness.

## Headline run (440 sessions, postgres, hermetic)

| arm | accuracy | active_staleness (#72) | over_merge | turns | tokens | efficiency |
|---|---|---|---|---|---|---|
| no-memory | 0.952 | 0.00 | 0 | 604 | 14402 | 0.028 |
| naive-append | 0.914 | 1.00 | 0 | 440 | 31728 | 0.012 |
| stele-full | 0.914 | 0.43 | 0 | 440 | 2890 | 0.121 |
| stele-role (fix) | 0.914 | 0.29 | 0 | 440 | 2528 | 0.135 |

Store-side staleness by scenario class:

| arm | stable | value (entity-named-by-its-value, #72) |
|---|---|---|
| naive-append | 1.00 | 1.00 |
| stele-full | 0.00 | 1.00 |
| stele-role (fix) | 0.00 | 0.667 |

## What it shows

1. **The registry is perfect on stable subjects, fails on value-named ones.**
   `stele-full` stable-class staleness is 0.00; value-named is 1.00. Overall 0.43,
   reproducing bento's 38.9%. This is #72's bimodal structure, in the lab.

2. **The win over blind append is store-cleanliness and tokens, not agent
   accuracy.** Under a recency policy every memory arm answers the current value
   (~0.91 accuracy), so the differentiator is latent store staleness (naive 1.00
   vs stele-full 0.43) and an ~11x token gap (31728 vs 2890). Do not quote agent
   accuracy as the memory win; quote active_staleness and tokens.

3. **The win over no-memory is turns and tokens.** no-memory re-runs the tool on
   every memory-dependent session (604 turns vs 440) and cannot keep a clean store.
   Its accuracy is high only because re-running the tool returns ground truth.

4. **The recommended #72 fix works on its identity half, not the rest.** The
   `stele-role` arm (a stable role anchor, modeled with the shipped
   `subject_aliases` layer) cuts value-named staleness 1.00 -> 0.667 and overall
   0.43 -> 0.29, with over_merge held at 0.00 (precision preserved) and the stable
   class unregressed. It does NOT reach the <=0.10 bar: the residual is the
   write-order supersession half (a stale doc resurfacing promotes the old value
   back to active), a different mechanism that needs the reconcile / effective-time
   backstop. This independently confirms the downstream debate's conclusion that a
   single identity fix is insufficient and must be paired with a reconcile pass.

## Real-LLM lane (gemma-26B)

| scenario | ideal (forced-stable) | real-llm |
|---|---|---|
| web tier (replicas 3->5) | clean | undetected* |
| python (3.11->3.12, stable subject) | clean | STALE |
| auth token TTL (3600->900) | clean | clean |
| primary datastore (value-named) | clean | STALE |

ideal staleness 0.00, real-LLM staleness 0.50. The key result: a STABLE-subject
fact (python version) goes stale under a real extractor because the model drifts
on subject_label / aspect. The deterministic core reports that same fact as 0.00
because it cannot drift. So the deterministic numbers are a FLOOR; the real number
includes an extraction-instability term the core is blind to (#72's `replicas`
finding). *web tier is a detection miss (the model paraphrased the digit), not a
true clean; the substring value-detector is this thin lane's weak link.

## Honest caveats

- The deterministic core proves mechanism and cost, not decision quality. It
  forces the WORST-case label per class (upper bound on identity staleness). The
  efficacy claim leans on the real-LLM lane and the gated bento pass.
- The `stele-role` arm proves the fix's BACK half (slotting on a correct role
  collapses staleness with 0 over-merge). It does not prove the FRONT half
  (deterministically deriving the role), which the debate flagged as the real
  risk: the role must be schema-enforced, never LLM-invented.
- agent accuracy parity across memory arms is a property of the recency policy;
  a non-recency policy would expose naive-append's 100% latent staleness directly.

## Reproduce

```bash
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
.venv/bin/python -m benchmarks.evolving_world --sessions 440 --backend postgres --fix
.venv/bin/python -m benchmarks.evolving_world_llm --backend postgres   # needs a model endpoint
.venv/bin/pytest tests/benchmarks_smoke/test_evolving_world_smoke.py    # no network, sqlite
```

## Relation to the tickets

- #69 (cross-session evolving-fact staleness): the lab confirms the residual after
  the registry is ~0.43, failing the <=0.10 bar, concentrated in value-named facts.
- #72 (entity-named-by-its-value): reproduced exactly (value-named 1.00, stable
  0.00, over_merge 0). The role anchor is necessary but not sufficient; pair with
  the reconcile backstop.
