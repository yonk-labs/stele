# Evolving-World Agent Simulation: Benchmark Design

Status: DESIGN (ready for `writing-plans`)
Date: 2026-06-21
Source: collaborative design (human + Claude) with a 3-model Abe debate
(gemma + qwen + codex) on validity threats. Builds on `benchmarks/longrun.py`,
`benchmarks/answer_workflow.py`, the Subject Registry / Temporal Recall Phase 1
(v0.6.4), the `extra_subjects` hook (v0.6.5), and evolving-fact consolidation
(0.6.3). Targets issue #69 efficacy proof.

## TL;DR

Simulate long-running agents running thousands of sessions over compressed
virtual time, while the world they operate in changes underneath them (software
upgrades, dependency updates, deprecations, config changes the agent did not
cause). Prove stele's memory layer delivers the four goals: (a) fewer turns, (b)
better decisions, (c) fewer tokens, (d) faster. The load-bearing claim is that
the new Subject Registry plus cross-session supersession keeps an agent acting on
the *current* state of a fact whose value changed across sessions, where before
this machinery 60% of cross-session evolving facts left a stale, contradictory
fact active (measured, issue #69).

The harness holds the agent policy constant across arms and varies only the
memory subsystem, so any delta is attributable to memory and not to a smarter
scripted agent. The single biggest validity threat is circularity ("schema
coercion"): if the agent retrieves the same key the oracle uses to define truth,
we test database indexing, not agentic memory. We defeat it by feeding the agent
noisy unstructured artifacts and judging it on action outcome against the world,
not on string-matching a key.

## What we are proving (and the crux)

The four goals, each tied to a measurable:

- (a) fewer turns: turns-to-success per session, summed over the run.
- (b) better decisions: task-success rate, stale-action rate, and staleness-lag.
- (c) fewer tokens: total tokens consumed, priced from real artifact bytes.
- (d) faster: recall-path latency p50/p95 vs the re-exploration path.

The crux the rest of the project does not yet test: memory must EVOLVE based on
real-world conditions OUTSIDE the agent's control. A `VALUE_CHANGE` or
`DEPRECATION` flips a fact's correct value at a virtual time the agent neither
caused nor was told about. The agent only learns the new value when a later
session happens to carry evidence of it. The test measures the gap: how long does
an agent keep acting on the outdated value after the world moved and after
evidence first appeared (staleness-lag), and does the memory layer ever surface a
retired value as current (stale-action rate).

## What is under test

The new machinery (the reason this benchmark exists):

- Subject Registry (v0.6.4): deterministic `resolve_subject` maps the same
  real-world entity to one stable `subject_id` across sessions even when an LLM
  labels it differently. Cross-session supersession then chains current value +
  history (recoverable via `as_of`).
- `from_session(extra_subjects=)` (v0.6.5): caller-seedable known subjects.
- Evolving-fact consolidation (0.6.3): the `(scope, kind=fact, subject, aspect)`
  slot + supersession chain this sits on.

Mechanism is proven by contract tests. Efficacy at scale is unproven (a prior
qwen A/B at n=8 was inconclusive). This harness produces the efficacy evidence.

## Locked design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Fidelity | Hybrid: deterministic scripted-agent core for scale + a thin real-LLM lane | Reproducible bulk + a non-scripted lane that defeats schema coercion. Matches the existing `longrun` (deterministic) / `answer_workflow` (LLM-judged) split. |
| Arms | Two-tier (below) + a stale-injection control arm | Scale run proves commercial value; small attribution suite isolates the hero component; control arm is the adversarial + noise-floor probe. |
| Oracle | Both: value-recall for the scale run, action-outcome for the proof subset + LLM lane | Cheap reproducible scale plus a publishable, hard-to-rig proof. |
| Where | Lab-first in this repo (synthetic evolving world), then a GATED bento confirmation pass | Reproducible/CI-able evidence first; real-consumer confirmation second, behind an explicit human gate. |

## Architecture

Four units, each independently testable, communicating through narrow
interfaces. The world is agent-blind; the agent is memory-pluggable.

### 1. World Simulator (the oracle, agent-blind)

A deterministic timeline of `WorldEvent`s over compressed virtual time. Two event
types only (YAGNI):

- `VALUE_CHANGE`: an entity's correct value changes at `effective_at` (an upgrade,
  a config change, a new pinned version).
- `DEPRECATION`: an entity is retired at `effective_at`; the correct action
  becomes "stop using / abstain".

The simulator exposes exactly one read to the scoring layer (never to the agent):
`current_truth(entity, aspect, at_virtual_time) -> value | RETIRED`. The agent has
no access to this function. This separation is the structural defense against
circularity.

### 2. Artifact Generator (the noisy world surface)

Each session emits a noisy, unstructured artifact (a synthetic CI log, a README
diff, a dependency list, a changelog snippet) that may or may not carry evidence
of a recent world change. Two deliberate properties:

- Entities are referred to by VARYING surface forms across sessions. This is the
  exact #69 failure mode the Subject Registry must collapse. If the generator
  used one canonical label per entity, it would delete the test.
- Evidence of a `VALUE_CHANGE` appears in a session strictly after the event's
  `effective_at`, and not in every later session. The lag between event and
  first-evidence is what the agent must survive on memory.

The artifact is what gets routed through `stash_tool_result` and extracted into
memory. It is also the only thing the agent observes.

### 3. Agent (held constant across all arms)

Per session: `Observe artifact -> Recall memory -> Act`. The decision policy is
FIXED and IDENTICAL across every arm; only what `recall` returns differs. Holding
the agent constant is what makes any cross-arm delta attributable to the memory
subsystem rather than to a cleverer agent.

- Value-recall oracle: the agent commits a value for the entity; scored correct
  iff it equals `current_truth` at that virtual time. Cheap, reuses the existing
  `longrun` forbidden/expected substring oracle almost as-is.
- Action-outcome oracle: the agent extracts the fact from the unstructured
  artifact and chooses an action phrased in task terms ("pin to version V", "use
  endpoint E", "stop using retired tool T"). Scored correct iff the action
  succeeds against world state. The "outcome" is a pure deterministic function of
  `(action, current_truth)`; no real sandbox or command execution is built.

The real-LLM lane swaps the fixed policy for a real LLM that labels entities in
its own words (real phrasing variance), confirming the deterministic core is not
gaming the schema.

### 4. Memory subsystem (the swappable variable)

The only thing that differs across arms. Defined by the arm matrix below.

## Arms

Two tiers plus a control. The expensive comparison runs at scale; the
fine-grained ablations run on a small fixed scenario set (Abe's headline-vs-
attribution split, so we do not pay 5 arms x thousands of sessions).

Headline scale run (thousands of sessions, value-recall oracle):

| Arm | Memory behavior | Isolates |
|---|---|---|
| `no-memory` | nothing persisted; every session re-derives from its own artifact | the floor |
| `naive-append` | every observation persisted as a new active row; no consolidation | "does memory help at all" |
| `stele-full` | registry + cross-session supersession + temporal recall | the product |

Attribution suite (small fixed scenario set, action-outcome oracle):

| Arm | Memory behavior | Isolates |
|---|---|---|
| `stele-no-registry` | supersession on, registry off (cross-session identity by LLM string luck) | the Subject Registry's specific contribution (the #69 fix) |
| `stele-no-supersession` | registry on, supersession off | supersession's specific contribution |
| `stele-full` | both | reference |

Control arm (adversarial + noise floor):

| Arm | Behavior | Purpose |
|---|---|---|
| `stale-injection` | deliberately seed a known-retired value with no fresh evidence; also re-run `stele-full` on reshuffled seeds | does stele-full ever surface a retired value as current? establishes the run-to-run noise floor so a measured delta can be called significant |

Attribution math: `stele-full - naive-append` is the product delta;
`stele-full - stele-no-registry` is the registry's contribution;
`stele-full - stele-no-supersession` is supersession's contribution.

## Metrics, mapped to goals

| Goal | Metric | Where measured | Non-circular because |
|---|---|---|---|
| (a) fewer turns | turns-to-success / session, summed | agent loop | turn cost model is arm-independent; only candidate set differs |
| (b) better decisions | task-success rate; stale-action rate; staleness-lag | scoring layer vs world | staleness-lag and stale-action rate are store-side, independent of the agent's policy |
| (c) fewer tokens | total tokens (recall payload + re-exploration), priced from real artifact bytes | cost model | one fixed cost model across all arms; bytes come from the actual stored artifacts |
| (d) faster | recall-path latency p50/p95 vs re-exploration | timers | direct measurement |
| composite | `Efficiency = successes / (tokens + lambda * turns)` | derived | combines (a)(b)(c) into one headline number |

Per the project testing spec, report p50/p95/p99 and breakeven, not only means.

## Validity defenses (in priority order)

1. Schema coercion (the #1 threat). The agent never sees the `(subject, aspect)`
   schema and never reads `current_truth`. It observes unstructured artifacts; it
   is judged on action outcome. The structured key lives only inside stele's
   extraction/registry/recall, which is the machinery under test.
2. Hold the agent constant. Identical fixed decision policy across all arms; only
   the memory subsystem varies. The LLM lane confirms a non-fixed policy shows the
   same direction.
3. Store-side anchor metric. Staleness-lag and stale-action rate are computed by
   querying the store, not by inspecting the agent's choices, so the harness
   author cannot rig them via the decision policy.
4. Cost grounded in real bytes. Re-exploration cost is derived from the actual
   stored artifact sizes, not invented constants.
5. Real label variance. Entities use varying surface forms (deterministic lane)
   and the LLM names them freely (LLM lane), so the registry is genuinely exercised.

## Build plan (lean)

Extend, do not greenfield:

- World Simulator + Artifact Generator: a thin timeline layer over the existing
  `_TEMPORAL_PAIRS` scenario families in `benchmarks/longrun.py`. The forbidden/
  expected substring oracle already present becomes the value-recall oracle.
- Token / round-trip / judge accounting for the LLM lane: reuse
  `benchmarks/answer_workflow.py`.
- Reports follow the existing `benchmarks/runs/<date>/` markdown + JSON pattern
  and the `report.json` schema in `testing-benchmark-spec.md`.

Deliberate cuts (YAGNI):

- No literal "fleet of thousands of agents". 1 agent x thousands of sessions
  gives the same signal. Multi-agent appears only as a shared-namespace
  contention scenario where namespace isolation is the thing under test.
- No continuous time. Discrete virtual timestamps; `as_of` already takes a
  datetime.
- No `VALUE_CHANGE`/`DEPRECATION` beyond the two types. Add more only if a real
  scenario needs it.
- No real sandbox/command execution. Action outcome is a pure function of
  `(action, current_truth)`.
- No LLM judge in the deterministic core. The oracle is deterministic there; the
  LLM judge is only for the thin efficacy lane.
- No expected-utility / regret decision theory. Binary action success/failure
  (the Abe panel sided against utility modeling).

## Phasing and the bento gate

1. Lab core: World Simulator + Artifact Generator + the constant agent +
   value-recall oracle + the headline 3-arm scale run. Deterministic, CI-able.
2. Attribution suite: the two ablation arms + the stale-injection control arm,
   action-outcome oracle, small fixed scenario set.
3. Thin real-LLM lane: a subset of scenarios through a real LLM (real label
   variance) to confirm the deterministic core is not gaming the schema.
4. GATE: bento confirmation pass is a HARD STOP. The harness pauses and requires
   explicit human go-ahead before anything runs against the real consumer. (Bento
   is a live consumer; do not point the harness at it without sign-off.)

## Open questions / risks

- `lambda` in the Efficiency composite needs a defensible value; report the
  component metrics separately so the composite never hides them.
- The action-outcome oracle's "action vocabulary" needs to be small and fixed so
  scoring stays deterministic; over-rich action spaces reintroduce ambiguity.
- Re-exploration cost model needs one honest definition (which original tool calls
  re-run, at what byte cost) applied identically across arms; document it.
- The deterministic core can only prove mechanism and cost, not "intelligence".
  The efficacy claim ultimately leans on the LLM lane and the gated bento pass;
  the deterministic numbers must be labeled as mechanism-and-cost, not decision
  quality, per the project's measurement-integrity norm.
