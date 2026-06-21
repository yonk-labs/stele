# Memory-value thesis: store the durable, not the volatile (2026-06-21)

A strategic finding that reframes what stele should optimize for. Pairs with the
evolving-world findings ([evolving-world-69-72](evolving-world-69-72-2026-06-21.md)).

## The thesis

Cheaply re-derivable facts are LOW or NEGATIVE value to store and evolve. "Am I on
Postgres 16 or 17" is a one-line command: re-deriving is cheaper, fresher, and
SAFER than recalling memory, because a confidently-stored STALE value suppresses
the cheap re-check (the agent trusts memory and acts on the wrong value).

The HIGH-value memories are the agent's non-re-derivable process history, which the
environment cannot answer at any cost: DECISIONS and rejections ("we decided not to
use Kafka"), COMPLETIONS ("did we already review this spec?"), DEAD-ENDS tried ("we
tried Y, it failed because Z"), and PROCEDURAL know-how ("when processing workflow
X, here are the tips/sequences/gotchas"). Memory's value is highest exactly where
the world cannot answer.

## Cross-model debate verdict (gemma + qwen + codex)

All three converged: the thesis is correct. Stele should pivot from an "Evolving
Fact Engine" to an "Agentic Context and Protocol Ledger." Key points:

- **Discriminator is epistemic authority, not re-derivation cost.** If a value has
  an authoritative, idempotent, accessible source (the environment), storing the
  VALUE is an anti-pattern. Store the verification protocol and the rationale.
- **Decisions/procedure are append-only.** Overwriting a decision causes "epistemic
  amnesia": the agent repeats rejected work because the rejection is gone. State is
  supersedable (a change in the world); decisions are append-only (a change in
  intent). A reversal is a new record with a pointer to the old, never an overwrite.
- **Steelman (when NOT storing a cheap fact hurts):** the discovery gap (store the
  hint "check `.tool-versions`"), the latency/permission barrier (re-derivation is
  only cheap with creds and a responsive env), and the planning anchor (a known
  value scaffolds a plan before execution). Resolution: store methods and hints;
  where you cache a reading, mark it low-confidence/ephemeral so it reads as
  "re-verify me," never as durable truth.

## Proof: the return-format experiment

`benchmarks/return_format.py` (gemma-26B, N=4 stale-memory scenarios, under realistic
efficiency pressure: "avoid unnecessary tool calls"). A verifiable fact whose stored
memory is now stale; the agent has a verify() tool; we vary ONLY what stele returns.

| return format | accuracy | verified |
|---|---|---|
| `bare-stale` ("X is 16") | 0.00 | 0% |
| `dated-stale` ("X is 16, observed 40d ago") | 0.00 | 0% |
| `method` ("to find X, call verify()") | 1.00 | 100% |
| `none` (no memory) | 1.00 | 100% |

Findings:

1. **Storing the value is strictly worse than storing nothing.** `bare-stale` made
   the agent wrong every time (0%); `none` made it right every time (100%). The
   stored value suppressed the re-check.
2. **Dating the fact did not save it.** `dated-stale` was also 0%: gemma trusted the
   stale value and never verified. Signalling staleness is not enough; you must
   WITHHOLD the volatile value and give the method instead.
3. **Return-format is the lever, not the store.** Identical underlying staleness,
   four framings, a 0% -> 100% accuracy swing driven purely by how stele frames the
   return and how the model interprets it. "Memory efficacy" is
   `store x return-format x model-interpretation`, not a property of the store.

## The extraction-time rule (the deliverable)

For every candidate memory:

Step A, categorize truth-mode:
- Current observable state ("version is 16") -> SKIP durable storage; extract the
  verification method instead.
- Historical/process (decisions, dead-ends, completions) -> STORE append-only.
- Procedural (workflow tips, gotchas) -> STORE append-only / accumulate.
- Constraint/policy ("never use Redis") -> STORE append-only.

Step B, supersession fence:
- Current-state + cheap re-derivation -> never supersede; discard the volatile
  value, keep the method.
- Decision/procedure -> never supersede; new record + pointer to the old.
- Only genuinely-mutable, expensive-to-re-derive state stays in the supersession
  chain (the narrow slice the registry/#72 machinery actually serves).

## Implications for stele

- The temporal-recall / Subject Registry / #72 effort optimizes the LOW-value
  corner (keeping re-derivable facts current). Not wasted (it characterized the
  corner and surfaced the staleness trap) but no longer the headline.
- New headline: a truth-mode classifier at extraction (store-vs-skip,
  supersedable-vs-append-only), append-only decisions/procedure, and
  verification-protocol extraction over volatile readings.
- Return-format is a product surface: returned memories should carry confidence /
  staleness / verification-method so the model interprets them correctly.

## Caveats

- One model (gemma-26B), N=4, temperature 0. `dated-stale = 0%` is likely
  model-specific and should be run across models before generalizing.
- The efficiency-pressure framing is a realistic but deliberate design choice;
  without it a cautious model just always verifies and the format does not matter
  (the first run showed exactly this).
- N=4 yields coarse 0/4 vs 4/4 numbers; the separation is clean but should be
  widened (more scenarios, more models) before any public claim.

## Next

- A high-value-memory experiment: decisions / dead-ends / procedural tips, measuring
  turns saved by NOT re-litigating and bad decisions avoided by NOT re-doing
  rejected work (the case the current benchmark does not yet test).
- Then the core re-scope: the truth-mode classifier + append-only fence +
  verification-protocol extraction, validated by the refocused oracle.
