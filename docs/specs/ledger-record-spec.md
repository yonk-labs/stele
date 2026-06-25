# Ledger Record Schema & Retrieval Protocol (draft spec)

Status: DRAFT spec, graduated to inform the core build. Companion to the committed phased
plan (`docs/specs/context-protocol-ledger-plan.md`) and the off-git design explainer
(`.remember/ledger-design-explainer.md`, rationale). Required revisions are in section 11;
v1 benchmark validation is in section 12 (the mechanism is proven; open issues remain).
Pydantic-shaped so it maps onto `stele/core/` when built. No em-dashes by house rule.

---

## 1. Core principle

Store validated, EXPENSIVE-to-derive work (outcomes, decisions, dead-ends, procedures) as
ASSUMPTION-BOUND artifacts that carry (a) their own measured cost and (b) their own validity
boundary. Reuse only when reuse is provably cheaper than re-deriving AND the validity
boundary re-checks. Cheap facts are scope selectors and freshness gates, never standalone
retrieval targets. Memory serves the agent's PLANNING step ("what do I need, how do I get
it"), it does not hand back "the answer, trust it".

---

## 2. The record

Append-only and immutable. A correction or reversal is a NEW record linked to the prior.
Running usage stats (hits, re-measured costs) are NOT stored in the record; they live in a
separate projection (section 5) so the record stays immutable.

```python
class LedgerRecord(BaseModel):
    # --- identity & type ---
    id: str
    kind: Literal["observation", "verification_method", "decision",
                  "dead_end", "procedure", "completion", "outcome"]
    created_at: datetime
    schema_version: int = 1
    supersedes: str | None = None          # link only; never overwrite
    superseded_by: str | None = None        # set by a later linked record

    # --- payload (DISTILLED: keep footprint small) ---
    title: str                              # one line, the retrieval handle
    body: str                               # the distilled answer/procedure/decision
    evidence_refs: list[str]                # stele:// source refs (required, non-empty)

    # --- scope: WHICH context this applies to (the router) ---
    scope: dict[str, str]                   # {dbengine: postgres, version: "17",
    #                                         project: stele, branch: main, ...}

    # --- validity boundary: the "12 things" this outcome depends on ---
    dependencies: list[Dependency]
    do_not_apply_when: list[str] = []       # explicit negative conditions

    # --- cost spine: the empirical value model (turns AND tokens) ---
    derive_turns: int                       # what it cost to PRODUCE (value of one reuse)
    derive_tokens: int
    verify_turns: int                       # cheapest full re-validation (sum of dep checks)
    verify_tokens: int
    footprint_tokens: int                   # cost to pull THIS record into context per reuse
    recall_turns: int = 1                   # the memory round-trip

    # --- trust ---
    authority: Literal["user", "system", "agent_inference", "observation"]
    confidence: float                       # 0..1, agent-assessed at write
    provenance: Provenance


class Dependency(BaseModel):
    name: str                               # workload_shape, data_volume, schema, extensions
    resolve: Literal["provided", "recall", "fetch"]
    fetch_cmd: str | None = None            # how to get it live if resolve == "fetch"
    value_at_derivation: str                # what it was when this was derived
    cheap_check: str | None = None          # the verification_method to re-confirm it
    check_turns: int = 1                     # cost of that check
    check_tokens: int = 0


class Provenance(BaseModel):
    produced_by: str                        # agent/session id
    corrected_by: list[str] = []            # who/what corrected it, in order
    derived_from: list[str] = []            # prior record ids this built on
```

### Field notes
- `scope` is the ROUTER: structured key/value, exact-matchable. It answers "which process".
- `dependencies` is the VALIDITY BOUNDARY: the bundle of assumptions a single freshness gate
  misses (the external reviewers' #1 objection). Each carries its own cheap re-check.
- The cost spine is a VECTOR (turns + tokens), not a scalar: weight by the scarce currency.
- `footprint_tokens` is the RECURRING reuse cost. Distill the body to shrink it; never
  distill away `dependencies`/`scope`/`provenance` (that is the "compression erases safety"
  failure mode).

---

## 3. Record kinds

| kind | what it captures | required beyond base | typical derive cost |
| --- | --- | --- | --- |
| `outcome` | a distilled multi-step result ("PG17 perf tuning for this workload") | dependencies, scope | HIGH |
| `procedure` | a reusable how-to / sequence ("how we cut a release here") | dependencies | HIGH |
| `decision` | a chosen direction + rationale ("Redis Streams over Kafka") | rationale in body | HIGH |
| `dead_end` | a tried-and-failed approach + why ("global lock deadlocks") | failure_reason, scope | HIGH |
| `completion` | a done/reviewed marker ("spec X approved") | scope | MED |
| `verification_method` | how to cheaply re-derive/check a volatile fact | the method, target | LOW (it IS the gate) |
| `observation` | a witnessed fact bound to a process (audit/scope) | context, value | LOW |

Only `outcome`/`procedure`/`decision`/`dead_end` are usually worth the cost spine. `observation`
and `verification_method` are scope/gate material, not standalone retrieval targets.

---

## 4. Retrieval / reuse protocol (the planning step)

Step 1 = the QUESTION. Step 2 = the PLAN. Memory is consulted in step 2:

1. **ROUTE.** Match `scope` discriminators (exact + provided-by-question) to candidate records.
   Fill missing discriminators from memory's continuity facts ("which DB last session?").
2. **RANK.** Order candidates by net reuse value in the scarce currency:
   `net = derive_cost - verify_cost - recall_footprint` (per currency).
3. **RESOLVE the dependency checklist.** For each dependency: `provided` (in the question),
   `recall` (from memory), or `fetch` (run `fetch_cmd`). Run each `cheap_check`.
4. **DECIDE:**

```
if scope matches
   and every dependency.cheap_check passes (within the verify budget)
   and net_reuse_value > 0  in the scarce currency:
       REUSE  (executable: apply the body)
elif scope matches but some dependency unresolved/unverifiable:
       ADVISORY  (inject body as context, do NOT act on it as truth)
       or return "I need these N things: [...]"   # the agent's step-2 output
else:
       RE-DERIVE   # cache miss
```

5. **On re-derive (miss):** measure the actual derive cost, write a fresh record (append-only),
   and update the usage projection (hits, cost prior).

Authority breaks ties and gates execution: a `user`/`system` record can be executed; an
`agent_inference` record at low confidence stays advisory regardless of net value.

---

## 5. Append-only + usage projection

- Records are immutable; current-state "views" are projected from the log (CQRS).
- Usage stats live OUTSIDE the record, in a projection keyed by `record_id`:

```python
class RecordUsage(BaseModel):
    record_id: str
    hits: int = 0                           # reuse count, grows over time
    observed_derive_turns: list[int] = []   # re-measured on each miss (running prior)
    observed_derive_tokens: list[int] = []
    last_used_at: datetime | None = None
```

- Write-time value uses `derive_* ` assuming >= 1 hit; `hits` then promotes/demotes the
  record. The record's stated `derive_*` is the agent's first measurement; the projection's
  observations refine it.

---

## 6. Storage threshold & garbage collection

- **Write gate:** persist as a durable ledger record only if
  `derive_cost - verify_cost - recall_footprint > 0` (cost can override kind: a 12-hop
  "fact" qualifies; a 1-hop fact does not). Otherwise it is session working memory or a
  live re-fetch, not the ledger.
- **GC / eviction:** cost-aware, GreedyDual-Size style: evict lowest `(net_value x hits)`
  first. Append-only history is retained for audit but compacted out of the hot retrieval
  set.
- Cheap facts enter the ledger ONLY as `scope`/`dependency.cheap_check` material on
  higher-value records, never as their own `outcome`.

---

## 7. Failure modes and how the schema mitigates them (from external review)

| failure mode | mitigation in this spec |
| --- | --- |
| false-valid reuse (gate passes, outcome stale) | `dependencies` checklist + per-dep `cheap_check`, not one gate |
| cache poisoning (bad conclusion reused) | `authority` + `confidence`; low-trust stays advisory; supersession |
| fossilization / anchoring (dead-end blocks now-valid path) | `dead_end` carries `scope` + `do_not_apply_when`; advisory, re-testable |
| branch / workspace contamination | `branch`/`commit` in `scope` discriminators |
| user-intent drift (same facts, different goal) | `goal`/`intent` in `scope` |
| verification-method rot (the check itself breaks) | if a `cheap_check` cannot run, dependency is UNVERIFIED -> advisory, not reuse |
| no GC story (append-only bloat) | cost-aware eviction (section 6) |
| authority confusion | explicit `authority` ordering, gates execution |
| compression erases safety | distill `body` only; `dependencies`/`scope`/`provenance` never compressed |
| retrieval precision (wrong cheap hit) | RANK by net value + scope exactness; advisory default |

---

## 8. Prior art this formalizes

Event sourcing + CQRS (append-only log, projected views); memoization with precondition
checks; assumption-based Truth Maintenance Systems (conclusions valid under declared
assumptions); build-system dependency invalidation (Bazel/Make/Skyframe reuse a derived
artifact only if inputs hold); cost-aware cache replacement (GreedyDual-Size); Case-Based
Reasoning; Reflexion/procedural agent memory. The novel glue is the per-record COST SPINE
driving an empirical reuse/store/evict decision.

---

## 9. Open questions (unresolved before graduation)

1. **Who declares the dependency set?** The agent at derivation time, a critic pass, or
   learned from misses? Under-declared dependencies are the main residual risk.
2. **Verify cost can approach derive cost.** If `verify >= derive`, caching is pointless;
   the net-value gate handles it, but we should log how often this happens.
3. **Shared-memory cost noise.** `derive_*` is the cost THIS agent paid; across agents of
   different skill it is noisy. Per-agent priors vs shared?
4. **Scope as a latent space** (reviewers): flat KV discriminators may be too coarse for some
   dimensions; some may need a fingerprint/hash. Which dimensions?
5. **Naming.** "Ledger" hides the mechanism (validated reuse of derived work). Keep "ledger"
   as the substrate, describe behavior as a "guarded reasoning cache"?

---

## 10. Minimal v1 (ponytail: build this slice first, defer the rest)

Do NOT build all of the above at once. v1 that proves the thesis:

- Add the **cost spine** (`derive_turns`, `derive_tokens`, `footprint_tokens`) to records +
  a `RecordUsage` projection with `hits`.
- Add `scope` (flat KV) and a flat `dependencies` list with `cheap_check`.
- Reuse policy: scope-match -> run cheap_checks -> reuse iff `net > 0`, else advisory/re-derive.
- Benchmark it: `evolving_world` already counts turns; add `derive_turns` + the net-value
  reuse policy and measure TURNS-TO-OUTCOME saved on a multi-step goal.

Defer to later phases: authority tiers, full provenance graph, CQRS projection machinery,
intent modeling, fingerprint scopes, shared-memory cost reconciliation.

The v1 question to answer with data: does cost-gated, dependency-checked reuse beat both
"always re-derive" and "naive cache" on turns-to-outcome, without false-valid reuse?

---

## 11. External review round 2 (codex second-opinion + abe panel gemma/qwen/codex) and required revisions

Strong consensus: the SHAPE is right (`scope + dependencies + cost`), but the spec handwaves
the hardest parts and has real bugs. Required before graduation:

### Must-fix (consensus)
1. **Replace raw `fetch_cmd` / `cheap_check: str` with a TYPED, SANDBOXED check contract.**
   Storing arbitrary shell to run during planning is an RCE + portability + reliability hole
   (unanimous). Typed adapters instead:
   `Check = {kind: file_hash|git_ref_exists|package_version|test_command|api_schema_hash|predicate,
   target, comparator: eq|gte|contains|matches, expected, timeout_ms, side_effects: forbidden,
   result: pass|fail|UNKNOWN}`. The rule that matters most: **no check, no reuse.**
2. **Dependency declaration is THE failure mode, not an open question.** Agents under-report
   deps (laziness, or gaming `net_value` by declaring few). Require: (a) per-kind REQUIRED
   dependency CLASSES (repo identity, commit/file fingerprints, package versions, runtime/tool
   versions, config/env, user intent, external API versions, permissions, prior evidence);
   (b) a write-time critic pass ("what would make this record wrong?"); (c) a post-miss
   learning loop that adds the dependency that was missed.
3. **`resolve="recall"` poisons the gate (codex).** Memory validating memory lets stale
   assumptions self-reinforce. For VALIDATION allow only `provided` (current user/context) or
   `fetch` (live source); unresolved -> UNVERIFIED -> hint-only. Recall is for ROUTING, never
   validity.
4. **Add a reuse AUDIT / feedback loop.** Log deps checked vs skipped, costs, the reuse
   outcome, later success/failure -> learn from false-valid reuse. Without it the system
   cannot improve its dependency models.
5. **Conflict / current-view semantics are mandatory (codex), not CQRS polish.** Define: can
   two active records disagree? Does supersede require same scope/kind? lower-authority
   superseding higher? two records superseding one parent? how does the router exclude
   superseded records?
6. **`net` is a probabilistic heuristic, not "provably cheaper."** LLM cost is stochastic; one
   turn can be a 5-minute tool run. Treat net as expected-value with variance + a max verify
   budget; do not drive policy on exact token arithmetic. Add a CANDIDATE BUDGET
   (`max_candidates`, `max_verify_turns`, stop after first verified positive-net candidate) -
   the formula ignores the cost of checking several near-right memories.

### Schema bugs (fix inline on graduation)
- `superseded_by` violates append-only immutability -> move it to the projection.
- `list[str] = []` -> `default_factory=list`.
- `RecordUsage.observed_*: list` grows forever -> store count/min/max/mean or capped samples.
- kind table requires fields (failure_reason, method, target) the schema does not model -> model them.
- `ADVISORY` -> rename `HINT`, constrained: may inform the plan, agent must re-derive before acting.

### Cut for v1 (consensus over-engineering)
authority tiers; `confidence` float (-> low|med|high + reason); full provenance graph (keep
`derived_from` + `supersedes`); GreedyDual-Size GC (-> quota + weighted-LRU, AND keep
cost-value separate from RISK-value so GC never deletes rare safety records); CQRS language;
intent/goal in scope; shared-agent cost reconciliation; granular token arithmetic as a policy
driver (store it, do not decide on it yet); too many kinds (collapse toward
procedure/decision/finding/dead_end).

### Scope needs typed match policies (not flat exact KV)
Exact commit match -> ~0 hits; loose branch match -> contamination. Per-dimension policy:
repo:exact, file_hash:exact, package_major:exact, package_minor:compatible, branch:weak_signal,
commit:advisory. Branch alone is a weak freshness signal.

### Honest disagreements (NOT consensus)
- "authority gates execution": most call it a category error (source-trust != factual validity;
  a user can be wrong). qwen defends it as risk-based "use as-is but still validate." Resolution:
  authority informs TRUST, not executability; gate execution on authority + evidence +
  dependency-validity + risk.
- recursion via verification_method-as-record: codex says fundamental (needs primitive base
  checks); qwen says manageable (precompute checks at write time, store verified_at/status; deps
  are usually sparse). Resolution: primitive built-in checks are the base layer; memory-stored
  procedures compile down to them or stay hint-only.

### Revised minimal v1 (post-review)
Record: id, kind (few: procedure|decision|finding|dead_end), title, body, evidence_refs, scope
(typed match policies), dependencies (typed Check; source = provided|fetch only), derive_turns,
verify_turns, footprint_tokens. Projection: hits, capped cost samples, superseded_by, audit log.
Policy: route by scope -> run typed checks -> "no check, no reuse" -> reuse iff all checks pass
AND net>0 within a candidate/verify budget, else HINT or re-derive. Benchmark turns-to-outcome.

---

## 12. v1 benchmark validation (benchmarks/outcome_reuse.py, committed)

The v1 policy was simulated (pure policy sim, no backend): an agent repeatedly produces a
multi-step outcome whose correctness depends on three environment dimensions that drift; one
drifts silently and stays drifted.

Result (120 tasks):

| arm | accuracy | false_valid | turns/task |
| --- | --- | --- | --- |
| no-memory (always re-derive) | 1.00 | 0.00 | 5.00 |
| naive-cache (no checks) | 0.25 | 0.75 | 1.07 |
| ledger-v1 (all 3 deps checked) | 1.00 | 0.00 | 4.03 |
| ledger-underdecl (1 dep missed) | 0.33 | 0.67 | 3.05 |
| ledger-learn (learns the miss, lag=2) | 0.98 | 0.017 | 3.71 |
| ledger-canary (under-declared + broad fingerprint) | 1.00 | 0.00 | 2.30 |
| ledger-tiered (broad + narrow-on-trip + learn) | 0.98 | 0.017 | 2.53 (low churn) / 2.58 (5x churn) |

Findings:
1. The mechanism works: fully-declared dependency-checked reuse is 0 false-valid.
2. The check cost eats most of the savings (ledger-v1 saves only 19%: verify approaches
   derive). Reuse pays only when derive cost >> dependency count.
3. Under-declaring ONE of three dependencies -> 0.67 false-valid (near naive). The gate is
   only as good as the declared set.
4. A post-miss learning loop recovers it: false-valid 0.67 -> 0.017 at LOWER cost than
   declaring everything upfront, BUT only if the miss is DETECTED. With detection past the
   horizon, ledger-learn degrades exactly to ledger-underdecl.

**Reframe of open question #1:** declaration does NOT have to be perfect IF misses are
detected and learned. The new linchpin is DETECTION ("how does the agent notice it acted on
a stale outcome?"), softer than perfect upfront declaration but not free and not guaranteed.
Open question #2 (verify approaches derive) is confirmed: gate reuse on net > 0.

**Brittleness, addressed (benchmarked):** requiring perfect declaration is itself naive. A
cheap BROAD drift canary (a fingerprint over a bounded env slice) makes the gate robust to
imperfect declaration: ledger-canary is UNDER-declared yet 1.0 accuracy / 0 false-valid
(the fingerprint catches undeclared drift), AND the cheapest correct arm (2.30 turns/task,
one fingerprint check replaces N per-dependency checks). Cost: over-invalidation on
irrelevant churn (12 re-derives vs ledger-v1's 4), which scales with churn in the slice
(noise_period=2 -> 3.50 turns/task, degrading toward no-memory). Robustness (0 false-valid)
holds throughout. Design lesson: replace "declare every dependency exactly" (brittle, must
be perfect) with "bound the relevant slice and fingerprint it" (forgiving: undeclared drift
INSIDE the slice is caught; only drift OUTSIDE the slice fails, a coarser thing to get
right). Scoping the slice (excluding known-irrelevant churn) is the tuning knob and a much
more forgiving form of declaration than a per-dependency checklist.
