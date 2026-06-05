# Recipe Distiller: Design (PROPOSED)

> **STATUS: PROPOSED. Not shipped.** No code in this document exists yet. It
> describes a future `distill.recipes()` view plus the provenance, materiality, and
> governance machinery it needs. Validated by a throwaway spike, not by tests. See
> the evidence in
> [recipe-distillation-spike-2026-06-05.md](../benchmarks/findings/recipe-distillation-spike-2026-06-05.md).

## Problem

`distill.skills()` returns a flat list of one-line `instruction` memories. Users
expect a "skill" to be what an agent skill is: a **named, triggerable how-to** that
combines precedents (worked examples), best practices, and the facts that bound them.
The shipped distiller cannot produce that. It maps each `MemoryKind` to a parallel
flat view (`skills` <- `instruction`, `best_practices` <- `preference`, `precedents`
<- `decision`, ...) and never composes across kinds. It is a compaction pipeline, not
a composition pipeline.

## Design: a four-stage pipeline

```
1. SCOUT      gather candidate memories per kind        (exists: extraction + memory facade)
2. JUDGE      materiality: "does this really matter?"    (exists for behavioral kinds only)
3. CLUSTER    group survivors by topic, cross-kind       (new)
4. COMPOSE    render each cluster as a recipe            (new)
```

Stages 1-2 are the "two-pass scout/judge" pattern; stages 3-4 are the composition the
current views lack.

### Stage 1: Scout

Reuse `extract.from_session` (the real v0.6.2 extractor) and the `memory` facade. No
change except provenance capture (below). Note: the shipped 3-window default
under-mines large multi-MB sessions (measured: 6 windows ~2x yield); `recipes` should
expose the window cap.

### Stage 2: Materiality judge (hybrid)

A deterministic prefilter keeps the obviously-material items for free
(human/prompt-authored, or recurring across >=2 sessions) and routes only the
ambiguous middle (agent-authored, single-session) to an LLM judge prompted "does this
matter as durable, reusable engineering knowledge?". Rationale: never pay LLM cost on
items authority or recurrence already vouch for, and the judge is nondeterministic
(measured), so minimize reliance on it.

- **Facts and precedents get a judge for the first time.** Today `distill.facts()`
  and `distill.precedents()` have no precision pass (`used_llm=False`); the highest-
  volume, noisiest kind is unfiltered.
- **Separate scout and judge LLMs.** Two model slots, default identical; a fast coder
  model can scout while a stronger generalist judges.

### Stage 3: Cross-kind cluster

Embed survivor summaries (the existing fastembed memory embedder, reusing the cosine
helpers in `distill/base.py`) and greedy-cluster. Clusters span kinds by design.
Oversized clusters (a likely over-merge) are re-split at a tighter threshold;
measured: threshold 0.66 with an 8-item split at 0.74 cleanly separated an over-merged
TDD blob.

### Stage 4: Compose

Per cluster, bucket members by kind into a recipe skeleton (steps/rules from
`instruction`; don't/fix from `pitfall`+`workaround`; best practices from
`preference`; precedents from `decision`; facts/constraints from `fact`) and use an
LLM pass to name it, write the `use when` trigger, and flag incoherent clusters
(which it should refuse to force into a fake recipe).

## Provenance and authority model

Authorship is a new attribute, **orthogonal to `MemoryKind`** (a `fact` or `decision`
can be human-stated or agent-derived), present on **every** memory and surfaced in
**every** view, not just `skills`.

- **Values:** `human` (a user turn), `prompt` (the first user turn), `agent`
  (assistant/tool/result). Authority rank: human > prompt > agent.
- **Authorship is set-valued.** A memory's authority is the **max over all turns that
  contributed**, not the identity of one best-matching turn. Human-said-then-agent-
  echoed resolves to human. (Spike result: this single rule moved instruction
  human-share from 33% to 55%; better text matching alone did nothing.)
- **Capture method (production):** turn-indexed extraction. Number the turns in each
  window (`[T0 USER] [T1 ASSISTANT] ...`) and have the extractor emit the source turn
  index per memory. Role is then a **deterministic lookup**, not an LLM guess, and the
  index doubles as an evidence ref (satisfying the "every memory cites its evidence"
  invariant). The spike used a similarity-floor heuristic instead; it over-credits
  some agent-ops items to human, which is exactly why turn-indexing is the real fix.

## Governance schema (the external-harness contract)

The distiller **proposes**, an external harness **disposes**, consumers **filter**.
Every item and every composed recipe carries:

| field | values | who sets it |
|---|---|---|
| `provenance` / `is_human` | human / prompt / agent / unknown | distiller (from turn role) |
| `review_state` | new \| accepted \| rejected | distiller seeds `new`, judge seeds `rejected`; only the harness sets `accepted` |
| `priority` | low \| med \| high | distiller (transparent score) |

- **`review_state` naming is deliberate.** It must NOT be called `state`: `distill.state()`
  is already a view and `MemoryRecord.status` (active/superseded/retracted) is storage
  lifecycle. Three different "state" concepts; do not collide them.
- **Priority score (transparent):** human +2 / prompt +1; recurs>=2 +1; recurs>=3 +1;
  `instruction`|`decision` +1. `>=3` high, `==2` med, else low; rejected forced low.
  Priority and provenance are the same signal reused, so the attribution fix is the
  primary input to the priority downstream tools sort on.
- **Self-correcting:** priority is only as accurate as the provenance under it, so
  nothing is trusted until a human/harness flips it to `accepted`. Imperfect priority
  degrades to "review this first", not "trust blindly".

## Output shape (proposed)

A new `RecipeItem` (a `DistilledItem` subtype), returned by `distill.recipes(scope)`:

```
RecipeItem:
  name: str                      # short skill name
  use_when: str                  # trigger
  steps: list[str]               # from instruction
  dont_fix: list[tuple]          # from pitfall + workaround
  best_practices: list[str]      # from preference
  precedents: list[str]          # from decision
  facts: list[str]               # from fact
  authority: str                 # max provenance over members
  priority: str                  # low | med | high
  review_state: str              # new | accepted | rejected
  source_refs: list[str]         # stele:// evidence (incl. turn refs)
```

## What changes in the shipped code (all proposed)

- `core/memory_record.py`: a `provenance` attribute (column vs `metadata` is an open
  question) plus `review_state` / `priority`. Keep them out of the `MemoryKind` axis.
- `extraction/session.py`: turn-indexed extraction (emit source turn index per item)
  and provenance capture; optionally raise the window cap for large sessions.
- `distill/`: a new `recipes` view (cluster + compose), and extend the materiality
  judge (today's behavioral `_refine`) to `facts` and `precedents`.
- `distill/facade.py` + CLI/MCP: a `recipes` mode and governance fields on outputs.

## Decisions (recommended)

1. **Provenance persistence: first-class `MemoryRecord` column.** Provenance and
   `is_human` drive priority and filtering, so they must be queryable, not buried in
   `metadata`. Migrate in-place via the existing guarded `DO` block pattern (as 0.4.0
   did for the cq kinds). `metadata` is reserved for non-queried annotations.
2. **`review_state` persistence: a separate `memory_review` table** keyed by memory id
   (`review_state`, `priority`, `reviewer`, `ts`), not a column on the memory. Memories
   are immutable and evolve by supersession; curation is mutable, human-owned, and may
   come from several harnesses/policies. Keep the two lifecycles decoupled. The
   distiller seeds rows (`new`/judge-`rejected`); only the harness writes `accepted`.
3. **Attribution: ship the max-authority floor (best-validated so far); turn-indexing
   is the intended successor but is NOT yet shown to be better.** A single-source,
   post-hoc turn-indexing prototype (run E) scored 11% person-authored vs the floor's
   42%, with 32% of its pointers landing on the wrong turn: single-source pointing
   defaults to the agent's longer turn and discards the max-authority rule. To actually
   win, turn-indexing must run DURING extraction, allow multiple source turns with
   max-authority, and be validated. Until then, ship the deterministic prefilter +
   max-authority floor labeled "approximate", and gate either approach on a hand-labeled
   calibration set.
4. **Compose determinism: deterministic skeleton, advisory LLM naming.** Kind-bucketing
   and authority ordering are always deterministic. The LLM only writes `name` +
   `use_when` and flags incoherence; cache its output by cluster signature so re-runs
   are stable. The materiality judge is treated as advisory and stabilized by best-of-K
   majority vote (the deterministic prefilter never wobbles; only the judged middle
   does). Spike run F: 96% of judge verdicts were unanimous across 3 runs, ~4% wobble on
   borderline items, and majority vote yields one stable answer.
5. **Recurrence scope: per-namespace, distinct sessions.** Count distinct sessions
   within a namespace, optionally time-decayed; cross-namespace recurrence is noise.

### Still needs data (not decided)

- **Provenance accuracy (floor value AND whether turn-indexing wins):** no labeled set
  yet. The spike used floor 0.50 by eye (over-credits some agent-ops items), and a
  single-source turn-indexing prototype did worse, not better (run E). A hand-labeled
  calibration set is the prerequisite to choosing and tuning either approach; it cannot
  be skipped by assuming turn-indexing is ground-truth.

## Validation status

Every stage was exercised on 16 real stele sessions in the spike (see findings). What
is **not** done: tests, contract coverage, calibration of the provenance floor against
labeled data, cross-project generalization, and any of the schema/persistence
decisions above. This is a design to build against, not a shipped feature.
