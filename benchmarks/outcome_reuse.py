"""Outcome-reuse benchmark: cost-gated, dependency-checked memory reuse.

Measures the HIGH-value corner (turns-to-OUTCOME, not single-fact recall): an agent
repeatedly produces a multi-step outcome whose correctness depends on several environment
variables that drift over time. It compares reuse policies and, crucially, the FALSE-VALID
REUSE rate when the dependency checklist is deliberately UNDER-DECLARED, the failure mode
every external reviewer of the ledger spec flagged as the whole ballgame.

This is a PURE POLICY SIMULATION (no stele backend): the cost-gated dependency-checked
reuse mechanism does not exist in core yet, so we model the policy to get data BEFORE
building it. Questions it answers: does dependency-checked reuse beat both naive caching and
always-re-derive on turns-to-outcome, how much does the check cost eat the savings, and how
badly does under-declaring ONE dependency hurt? See .remember/ledger-record-spec.md (v1).

Arms (the agent's task is identical; only the REUSE POLICY differs):
- no-memory:        always re-derive. Correct, most turns. The safe ceiling.
- naive-cache:      reuse on scope (router) match, NO dependency checks. Cheap, but
                    false-valid whenever a non-scope dependency drifted.
- ledger-v1:        reuse only if every DECLARED dependency check passes AND net > 0.
                    Catches declared drift (0 false-valid); the check cost eats most savings.
- ledger-underdecl: ledger-v1 but the checklist MISSES one real dependency, so it
                    false-valids exactly on that dimension's drift. The gate is only as good
                    as the declared dependency set.
- ledger-learn:     starts under-declared, but LEARNS the missed dependency after the miss
                    surfaces downstream (detect_lag tasks later) and corrects it. Models the
                    reviewers' post-miss learning loop, honestly including its lag: you suffer
                    false-valids until detection, then converge toward ledger-v1.
- ledger-canary:    UNDER-declared, but instead of per-dependency checks it runs ONE cheap
                    broad fingerprint of the env. Catches undeclared drift -> 0 false-valid
                    WITHOUT perfect declaration (the less-brittle answer), at the cost of
                    over-invalidating when irrelevant churn flips. Tunable by fingerprint
                    breadth (here: full env incl. a noise dimension).
- ledger-tiered:    canary + targeted: cheap broad fingerprint first, and ONLY on a trip a
                    narrow fingerprint (declared dims) to tell real drift from noise instead
                    of re-deriving. Reuses on noise trips (no over-invalidation) and learns
                    truly-relevant undeclared dims from misses. Wins over the plain canary as
                    churn rises; pays a small learning lag the canary avoids.

Design: docs/specs/ledger-record-spec.md and docs/specs/context-protocol-ledger-plan.md.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

# --- cost model (turns; the scarce currency the benchmark measures) ---
DERIVE_TURNS = 5    # cost to produce the outcome from scratch (always yields current truth)
CHECK_TURNS = 1     # cost to run ONE declared dependency's cheap check
RECALL_TURNS = 1    # cost to pull a stored outcome back into context


@dataclass(frozen=True)
class CostModel:
    """Per-primitive-operation costs. `derive` = produce the outcome from scratch (LLM-heavy);
    `check` = one cheap dependency/fingerprint comparison; `recall` = pull a stored outcome into
    context. TURNS are the scarce-currency proxy the benchmark gates on and the only hard-counted
    quantity. tokens/seconds/usd are MODELED report-only estimates (assumed constants, a
    calibration knob -- NOT measured) so accuracy, turns, tokens, cost, and latency can be read
    side by side. Defaults reproduce the committed turn numbers exactly."""

    derive_turns: int = DERIVE_TURNS
    check_turns: int = CHECK_TURNS
    recall_turns: int = RECALL_TURNS
    derive_tokens: int = 4000   # a from-scratch multi-step derivation (prompt + reasoning + out)
    check_tokens: int = 120     # a cheap comparison (fingerprint / one dependency probe)
    recall_tokens: int = 400    # pulling a stored record back into context
    derive_seconds: float = 12.0
    check_seconds: float = 0.4
    recall_seconds: float = 1.2
    usd_per_mtok: float = 5.0   # blended price; report-only


Arm = Literal["no-memory", "naive-cache", "ledger-v1", "ledger-underdecl", "ledger-learn",
              "ledger-canary", "ledger-tiered"]
ARMS: tuple[Arm, ...] = ("no-memory", "naive-cache", "ledger-v1", "ledger-underdecl",
                         "ledger-learn", "ledger-canary", "ledger-tiered")

# --- the drift world -------------------------------------------------------------------
# A Scenario is the world the arms run against. Real DEPENDENCY dims drive the true outcome
# AND are observable (an arm can fingerprint or check them). NOISE dims are observable but the
# outcome does NOT depend on them (a broad canary over-invalidates on their churn). HIDDEN
# dims drive the true outcome but are NOT observable -> no syntactic fingerprint or declared
# check can see them: the canary's (and ledger-v1's) semantic blind spot. The dataclass
# defaults reproduce the original single-schedule sim EXACTLY, so the committed headline
# numbers and the smoke pins hold; sweeps vary it to assure the canary across many lanes.


@dataclass(frozen=True)
class Scenario:
    n_tasks: int = 120
    detect_lag: int = 2
    # real dependency dims: (name, before, after, drift_task). Observable + outcome-relevant.
    deps: tuple[tuple[str, str, str, int], ...] = (
        ("db_version", "17", "18", 20),
        ("workload", "oltp", "analytics", 30),
        ("data_volume", "small", "large", 40),
    )
    scope_dim: str = "db_version"
    # noise dims: (name, period). Observable + fingerprinted but outcome-IRRELEVANT; flips
    # A/B every `period` tasks (period <= 0 -> constant, i.e. no churn).
    noise: tuple[tuple[str, int], ...] = (("ci_runner", 10),)
    # hidden SEMANTIC dims: (name, before, after, drift_task). Outcome-relevant but NOT
    # observable -> drift here slips past every syntactic check (the canary blind spot).
    hidden: tuple[tuple[str, str, str, int], ...] = ()
    # which OBSERVABLE dims the broad canary fingerprint covers (the tuning knob). None = the
    # whole observable env (deps + noise); a subset narrows the slice (Lane B frontier).
    canary_dims: tuple[str, ...] | None = None
    # cost model: per-operation turns/tokens/seconds/usd. Defaults reproduce the committed turn
    # numbers; tokens/latency/cost are modeled report-only. Lane F varies the turn ratio.
    cost: CostModel = field(default_factory=CostModel)

    @property
    def dep_names(self) -> tuple[str, ...]:
        return tuple(d[0] for d in self.deps)

    def declared_full(self) -> tuple[str, ...]:
        """A fully-declared ledger: every real dependency."""
        return self.dep_names

    def declared_under(self) -> tuple[str, ...]:
        """Under-declared: omit the LATEST-drifting dep that still drifts within the horizon
        (the silent tail), so the miss is guaranteed to surface. If nothing drifts in horizon,
        under-declaration is meaningless and equals the full set."""
        drifting = [(dt, name) for name, _b, _a, dt in self.deps if dt < self.n_tasks]
        if not drifting:
            return self.dep_names
        omit = max(drifting)[1]
        return tuple(n for n in self.dep_names if n != omit)


DEFAULT_SCENARIO = Scenario()


def _dim_val(task: int, before: str, after: str, drift_task: int) -> str:
    return before if task < drift_task else after


def env_at(task: int, scenario: Scenario = DEFAULT_SCENARIO) -> dict[str, str]:
    """The OBSERVABLE world state at a task index: real deps at their current value plus noise
    dims churning on their period. This is everything an arm can see (and a canary
    fingerprints). Hidden semantic dims are deliberately absent here."""
    env = {name: _dim_val(task, b, a, dt) for name, b, a, dt in scenario.deps}
    for name, period in scenario.noise:
        env[name] = "B" if (period > 0 and (task // period) % 2 == 1) else "A"
    return env


def true_outcome(task: int, scenario: Scenario = DEFAULT_SCENARIO) -> str:
    """The correct distilled outcome at a task: a function of the real deps AND any hidden
    semantic dims. Re-derivation always yields this for the current task; a reused record
    yields the outcome of the task it was derived in. Does NOT depend on noise dims."""
    env = env_at(task, scenario)
    dep_vals = [env[name] for name in scenario.dep_names]
    hidden_vals = [_dim_val(task, b, a, dt) for _name, b, a, dt in scenario.hidden]
    return "cfg[" + "|".join(dep_vals + hidden_vals) + "]"


def _canary(env: dict[str, str], dims: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """A cheap BROAD drift fingerprint over an observable env slice (by default the WHOLE
    slice, including churn the outcome may not depend on). One comparison catches ANY in-slice
    drift, including UNDECLARED dimensions (robust to imperfect declaration), at the cost of
    over-invalidating when irrelevant state in the slice churns. Real systems scope the slice
    (pass `dims`) to cut that: the tuning knob Lane B sweeps."""
    keys = sorted(env) if dims is None else sorted(d for d in dims if d in env)
    return tuple(env[k] for k in keys)


@dataclass
class Stored:
    outcome: str
    deps: dict[str, str]  # env values captured AT DERIVATION (the validity anchors)
    canary: tuple[str, ...] = ()  # broad env fingerprint at derivation (for ledger-canary)


@dataclass
class ArmMetrics:
    arm: str
    cost: CostModel = field(default_factory=CostModel)
    tasks: int = 0
    correct: int = 0
    false_valid: int = 0   # reused a stored outcome that was stale -> acted on wrong info
    reuses: int = 0        # == number of recalls (each reuse pulls exactly one stored outcome)
    rederives: int = 0     # == number of from-scratch derivations
    checks: int = 0        # number of dependency/fingerprint comparisons performed
    turns: int = 0

    @property
    def tokens(self) -> int:
        c = self.cost
        return (self.rederives * c.derive_tokens + self.checks * c.check_tokens
                + self.reuses * c.recall_tokens)

    @property
    def latency_s(self) -> float:
        c = self.cost
        return round(self.rederives * c.derive_seconds + self.checks * c.check_seconds
                     + self.reuses * c.recall_seconds, 2)

    @property
    def usd(self) -> float:
        return round(self.tokens / 1_000_000 * self.cost.usd_per_mtok, 4)

    def summary(self) -> dict[str, object]:
        n = self.tasks or 1
        return {
            "arm": self.arm,
            "tasks": self.tasks,
            "accuracy": round(self.correct / n, 4),
            "false_valid_rate": round(self.false_valid / n, 4),
            "reuse_rate": round(self.reuses / n, 4),
            "rederives": self.rederives,
            "turns": self.turns,
            "turns_per_task": round(self.turns / n, 4),
            "tokens": self.tokens,
            "tokens_per_task": round(self.tokens / n, 1),
            "usd": self.usd,
            "latency_s": self.latency_s,
        }


def run_arm(arm: Arm, scenario: Scenario = DEFAULT_SCENARIO) -> ArmMetrics:
    m = ArmMetrics(arm=arm, cost=scenario.cost)
    store: dict[str, Stored] = {}  # scope_key -> record

    def canary(e: dict[str, str]) -> tuple[str, ...]:
        return _canary(e, scenario.canary_dims)

    dt, ct, rt = scenario.cost.derive_turns, scenario.cost.check_turns, scenario.cost.recall_turns

    # ledger-learn state: a checklist that GROWS after a detected false-valid reuse, and a
    # queue of (fire_at_task, missed_dims) scheduled when a false-valid is committed.
    declared_learn = list(scenario.declared_under())
    learn_queue: list[tuple[int, tuple[str, ...]]] = []

    for task in range(scenario.n_tasks):
        env = env_at(task, scenario)
        truth = true_outcome(task, scenario)
        skey = env[scenario.scope_dim]

        # Post-miss learning loop (ledger-learn): a false-valid reuse surfaces detect_lag
        # tasks later (downstream failure). On detection, learn the missed dependency and
        # correct the outcome (one re-derive); the grown checklist catches it thereafter.
        if arm in ("ledger-learn", "ledger-tiered"):
            due = [e for e in learn_queue if e[0] <= task]
            learn_queue = [e for e in learn_queue if e[0] > task]
            added = False
            for _, dims in due:
                newly = [d for d in dims if d not in declared_learn]
                if newly:
                    declared_learn.extend(newly)
                    added = True
            if added:
                store[skey] = Stored(outcome=truth, deps=dict(env), canary=canary(env))
                m.turns += dt  # the corrective re-derivation
                m.rederives += 1
                m.tasks += 1
                m.correct += 1
                continue

        rec = store.get(skey)

        if arm == "no-memory":
            answer, turns, reused = truth, dt, False
            m.rederives += 1
        elif rec is None:
            # cache miss (router has nothing for this scope): derive and store.
            answer, turns, reused = truth, dt, False
            store[skey] = Stored(outcome=truth, deps=dict(env), canary=canary(env))
            m.rederives += 1
        elif arm == "naive-cache":
            # scope matched -> reuse with NO dependency checks (no checks charged).
            answer, turns, reused = rec.outcome, rt, True
        elif arm == "ledger-canary":
            # one cheap BROAD-fingerprint check instead of per-dependency checks: catches ANY
            # drift in the slice, including UNDECLARED dims (robust to imperfect declaration),
            # but over-invalidates when irrelevant churn (ci_runner) flips.
            net = dt - ct - rt
            if canary(env) == rec.canary and net > 0:
                answer, turns, reused = rec.outcome, ct + rt, True
                m.checks += 1
            else:
                answer, turns, reused = truth, dt, False
                store[skey] = Stored(outcome=truth, deps=dict(env), canary=canary(env))
                m.rederives += 1
        elif arm == "ledger-tiered":
            # Tiered: cheap BROAD fingerprint first; only on a trip check the NARROW
            # fingerprint (declared/believed-relevant dims) to tell real drift from noise,
            # instead of blindly re-deriving (the canary's over-invalidation). A trip from an
            # UNDECLARED dim is reused optimistically (no over-invalidation) and LEARNED if it
            # turns out stale. Converges to targeted precision + noise tolerance.
            declared = tuple(declared_learn)
            if canary(env) == rec.canary:
                # broad clean: nothing in the slice changed -> reuse (one fingerprint).
                answer, turns, reused = rec.outcome, ct + rt, True
                m.checks += 1
            elif tuple(env[d] for d in declared) != tuple(rec.deps[d] for d in declared):
                # a believed-relevant (declared) dim drifted -> re-derive (precise).
                answer, turns, reused = truth, dt, False
                store[skey] = Stored(outcome=truth, deps=dict(env), canary=canary(env))
                m.rederives += 1
            else:
                # broad tripped but narrow clean -> only UNDECLARED dims changed -> assume
                # noise and reuse (no over-invalidation); a candidate false-valid, learned if
                # the undeclared dim was actually relevant.
                answer, turns, reused = rec.outcome, 2 * ct + rt, True
                m.checks += 2
        else:
            # ledger arms: run the DECLARED dependency checks, gate on checks + net value.
            if arm == "ledger-learn":
                declared = tuple(declared_learn)
            else:
                declared = (scenario.declared_full() if arm == "ledger-v1"
                            else scenario.declared_under())
            verify = len(declared) * ct
            net = dt - verify - rt
            all_pass = all(env[d] == rec.deps[d] for d in declared)
            if all_pass and net > 0:
                answer, turns, reused = rec.outcome, verify + rt, True
                m.checks += len(declared)
            else:
                # a declared check failed (or reuse is not worth it): re-derive and refresh.
                answer, turns, reused = truth, dt, False
                store[skey] = Stored(outcome=truth, deps=dict(env), canary=canary(env))
                m.rederives += 1

        m.tasks += 1
        m.turns += turns
        if reused:
            m.reuses += 1
        if answer == truth:
            m.correct += 1
        else:
            m.false_valid += 1  # reused a stale outcome: confident, cheap, and WRONG
            if arm in ("ledger-learn", "ledger-tiered") and rec is not None:
                # schedule learning the undeclared dimension(s) that actually drifted.
                missed = tuple(d for d in scenario.dep_names
                               if d not in declared_learn and env[d] != rec.deps[d])
                if missed:
                    learn_queue.append((task + scenario.detect_lag, missed))

    return m


def run(n_tasks: int = 120, detect_lag: int = 2, noise_period: int = 10) -> dict[str, object]:
    scenario = Scenario(n_tasks=n_tasks, detect_lag=detect_lag,
                        noise=(("ci_runner", noise_period),))
    results = [run_arm(arm, scenario).summary() for arm in ARMS]
    return {
        "benchmark": "outcome_reuse",
        "tasks": n_tasks,
        "detect_lag": detect_lag,
        "noise_period": noise_period,
        "cost_model": {
            "derive_turns": scenario.cost.derive_turns,
            "check_turns": scenario.cost.check_turns,
            "recall_turns": scenario.cost.recall_turns,
            "derive_tokens": scenario.cost.derive_tokens,
            "check_tokens": scenario.cost.check_tokens,
            "recall_tokens": scenario.cost.recall_tokens,
            "usd_per_mtok": scenario.cost.usd_per_mtok,
        },
        "arms": results,
        "generated_at": datetime.now(UTC).isoformat(),
    }


# === ASSURANCE LANES =======================================================================
# Each lane is an INDEPENDENT stress on the canary, returning a verdict (lane, claim, ok,
# evidence). The canary's core invariant is structural: it reuses ONLY when its slice
# fingerprint is unchanged, so it can act on stale info ONLY when drift falls OUTSIDE the
# slice (Lane C). The lanes confirm this empirically across random schedules (A), map the
# breadth/noise tuning knob (B), bound the semantic blind spot (C), show it scales with
# dependency count where per-dependency checking cannot (D), and that coexisting entities
# stay independent (E).


def _random_scenario(rng: random.Random, n_tasks: int, n_deps: int, n_noise: int) -> Scenario:
    """A random IN-SLICE drift world: every outcome-relevant dim is observable (no hidden
    dims), so a correct canary must stay 0 false-valid no matter the drift timing."""
    deps = tuple((f"dep{i}", "a", "b", rng.randint(5, n_tasks - 5)) for i in range(n_deps))
    noise = tuple((f"noise{j}", rng.choice([2, 3, 5, 7, 10, 20])) for j in range(n_noise))
    return Scenario(n_tasks=n_tasks, deps=deps, scope_dim="dep0", noise=noise)


def lane_generality(n_scenarios: int = 200, seed: int = 0,
                    n_tasks: int = 120) -> dict[str, object]:
    """Lane A: across many random drift schedules + seeds the canary stays 0 false-valid,
    fully correct, and never costlier than always-re-deriving. Proves the headline is not an
    artifact of the one hand-tuned schedule."""
    rng = random.Random(seed)
    fv_max = 0.0
    acc_min = 1.0
    tpts: list[float] = []
    costlier = 0
    for _ in range(n_scenarios):
        sc = _random_scenario(rng, n_tasks, rng.randint(1, 5), rng.randint(0, 3))
        c = run_arm("ledger-canary", sc)
        nm = run_arm("no-memory", sc)
        fv_max = max(fv_max, c.false_valid / c.tasks)
        acc_min = min(acc_min, c.correct / c.tasks)
        tpts.append(c.turns / c.tasks)
        if c.turns > nm.turns:
            costlier += 1
    ok = fv_max == 0.0 and acc_min == 1.0 and costlier == 0
    return {
        "lane": "A generality",
        "claim": "0 false-valid + correct + never costlier than re-derive, across random "
                 "schedules/seeds",
        "ok": ok,
        "evidence": {
            "scenarios": n_scenarios,
            "canary_false_valid_max": round(fv_max, 4),
            "canary_accuracy_min": round(acc_min, 4),
            "canary_tpt_min": round(min(tpts), 3),
            "canary_tpt_mean": round(sum(tpts) / len(tpts), 3),
            "canary_tpt_max": round(max(tpts), 3),
            "scenarios_costlier_than_no_memory": costlier,
        },
    }


def lane_breadth_noise() -> dict[str, object]:
    """Lane B: sweep the canary slice breadth x noise frequency. Narrowing the slice past the
    real deps reopens the under-declaration hole; the sweet spot fingerprints all real deps
    and EXCLUDES known noise (0 false-valid AND noise-immune); the full-env slice is safe but
    over-invalidates as churn rises. Quantifies the bound-the-slice tuning knob."""
    base = DEFAULT_SCENARIO
    breadths: tuple[tuple[str, tuple[str, ...] | None], ...] = (
        ("declared-only", base.declared_under()),
        ("all-deps", base.dep_names),
        ("full-env", None),
    )
    rows: list[dict[str, object]] = []
    grid: dict[tuple[str, int], dict[str, object]] = {}
    for label, dims in breadths:
        for period in (0, 10, 2):
            sc = Scenario(n_tasks=120, deps=base.deps, scope_dim=base.scope_dim,
                          noise=(("ci_runner", period),), canary_dims=dims)
            c = run_arm("ledger-canary", sc)
            row: dict[str, object] = {
                "breadth": label, "noise_period": period,
                "false_valid_rate": round(c.false_valid / c.tasks, 4),
                "rederives": c.rederives, "turns_per_task": round(c.turns / c.tasks, 4),
            }
            rows.append(row)
            grid[(label, period)] = row

    def fv(k: tuple[str, int]) -> float:
        return cast("float", grid[k]["false_valid_rate"])

    def rd(k: tuple[str, int]) -> int:
        return cast("int", grid[k]["rederives"])

    narrow_reopens_hole = fv(("declared-only", 0)) > 0
    sweet_correct = all(fv(("all-deps", p)) == 0 for p in (0, 10, 2))
    sweet_noise_immune = rd(("all-deps", 10)) == rd(("all-deps", 0)) == rd(("all-deps", 2))
    full_over_invalidates = rd(("full-env", 2)) > rd(("all-deps", 2))
    ok = narrow_reopens_hole and sweet_correct and sweet_noise_immune and full_over_invalidates
    return {
        "lane": "B breadth x noise",
        "claim": "sweet spot = fingerprint all real deps and exclude known noise; narrowing "
                 "past deps reopens the miss, full-env over-invalidates on churn",
        "ok": ok,
        "evidence": {"rows": rows},
    }


def lane_semantic_blindspot() -> dict[str, object]:
    """Lane C: the honest boundary. A HIDDEN dim drifts under a stable observable fingerprint
    (meaning changes, the value string does not). The canary AND the fully-declared ledger-v1
    both false-valid IDENTICALLY -- this is a property of all syntactic fingerprinting, not a
    canary-specific weakness -- and only always-re-deriving (no-memory) is immune."""
    sc = Scenario(n_tasks=80, deps=(("db_version", "18", "18", 999),), scope_dim="db_version",
                  noise=(("ci_runner", 0),), hidden=(("schema_meaning", "v2a", "v2b", 25),))
    cv = run_arm("ledger-canary", sc)
    v1 = run_arm("ledger-v1", sc)
    nm = run_arm("no-memory", sc)
    cfv = cv.false_valid / cv.tasks
    vfv = v1.false_valid / v1.tasks
    nfv = nm.false_valid / nm.tasks
    ok = cfv > 0 and abs(cfv - vfv) < 1e-9 and nfv == 0
    return {
        "lane": "C semantic blind spot",
        "claim": "out-of-slice (semantic) drift: canary and ledger-v1 false-valid IDENTICALLY; "
                 "only re-derivation is immune (the canary's known boundary)",
        "ok": ok,
        "evidence": {
            "canary_false_valid": round(cfv, 4),
            "ledger_v1_false_valid": round(vfv, 4),
            "no_memory_false_valid": round(nfv, 4),
        },
    }


def lane_scaling() -> dict[str, object]:
    """Lane D: vary #real-deps and #noise-dims. Per-dependency checking collapses to no-memory
    once the checklist costs as much as deriving (deps >= derive-recall = 4: net <= 0, never
    reuses); the canary's single fingerprint keeps reusing at any dep count. Separately, the
    full-env canary's over-invalidation grows with #noise-dims yet stays 0 false-valid."""
    dep_rows: list[dict[str, object]] = []
    dep_grid: dict[int, dict[str, object]] = {}
    for n_deps in (1, 2, 3, 4, 5, 8):
        deps = tuple((f"dep{i}", "a", "b", 10 + 5 * i) for i in range(n_deps))
        sc = Scenario(n_tasks=120, deps=deps, scope_dim="dep0", noise=(("ci_runner", 0),))
        v1 = run_arm("ledger-v1", sc)
        cv = run_arm("ledger-canary", sc)
        nm = run_arm("no-memory", sc)
        row: dict[str, object] = {
            "n_deps": n_deps,
            "v1_turns": v1.turns, "v1_reuse_rate": round(v1.reuses / v1.tasks, 4),
            "canary_turns": cv.turns, "canary_reuse_rate": round(cv.reuses / cv.tasks, 4),
            "no_memory_turns": nm.turns,
            "v1_collapsed_to_no_memory": v1.turns == nm.turns,
            "canary_cheaper_than_no_memory": cv.turns < nm.turns,
        }
        dep_rows.append(row)
        dep_grid[n_deps] = row
    v1_collapses = all(cast("bool", dep_grid[d]["v1_collapsed_to_no_memory"]) for d in (4, 5, 8))
    v1_reuses_when_cheap = (cast("float", dep_grid[3]["v1_reuse_rate"]) > 0
                            and not cast("bool", dep_grid[3]["v1_collapsed_to_no_memory"]))
    canary_scales = all(cast("bool", dep_grid[d]["canary_cheaper_than_no_memory"])
                        for d in (1, 2, 3, 4, 5, 8))

    noise_rows: list[dict[str, object]] = []
    periods = (7, 11, 13, 17, 19)  # distinct: independent noise sources churn on their own
    for n_noise in (0, 1, 2, 3, 4):  # cadences, so each added source adds NEW churn points
        deps = (("db_version", "17", "18", 20), ("workload", "oltp", "analytics", 30),
                ("data_volume", "small", "large", 40))
        noise = tuple((f"noise{j}", periods[j]) for j in range(n_noise))
        sc = Scenario(n_tasks=120, deps=deps, scope_dim="db_version", noise=noise)
        cv = run_arm("ledger-canary", sc)
        noise_rows.append({
            "n_noise": n_noise, "canary_rederives": cv.rederives,
            "canary_false_valid_rate": round(cv.false_valid / cv.tasks, 4),
        })
    rds = [cast("int", r["canary_rederives"]) for r in noise_rows]
    noise_grows = rds[-1] > rds[0] and all(b >= a for a, b in zip(rds, rds[1:], strict=False))
    noise_correct = all(cast("float", r["canary_false_valid_rate"]) == 0 for r in noise_rows)
    ok = (v1_collapses and v1_reuses_when_cheap and canary_scales
          and noise_grows and noise_correct)
    return {
        "lane": "D scaling",
        "claim": "per-dep checking collapses to no-memory at deps>=4 (verify>=derive); the "
                 "canary's one fingerprint keeps reusing at any dep count; full-env "
                 "over-invalidation grows with noise-dims but stays 0 false-valid",
        "ok": ok,
        "evidence": {"dep_rows": dep_rows, "noise_rows": noise_rows},
    }


def lane_coexisting(n_tasks: int = 90) -> dict[str, object]:
    """Lane E: two entities (distinct scope keys) queried on alternating tasks, each drifting
    on its OWN schedule at the same time. The store is keyed per scope, so each entity gets its
    own record and its own canary -> drift in one must not invalidate or corrupt the other.
    Confirms the per-record fingerprint stays clean (the over-merge concern)."""
    drift = {"alpha": 18, "beta": 31}
    after = {"alpha": "olap", "beta": "stream"}
    before = {"alpha": "oltp", "beta": "etl"}

    def env_of(ent: str, t: int) -> dict[str, str]:
        wl = before[ent] if t < drift[ent] else after[ent]
        return {"entity": ent, "workload": wl}

    store: dict[str, Stored] = {}
    fv = correct = reuses = rederives = 0
    net = DERIVE_TURNS - CHECK_TURNS - RECALL_TURNS
    for t in range(n_tasks):
        ent = ("alpha", "beta")[t % 2]
        env = env_of(ent, t)
        truth = f"{ent}:{env['workload']}"
        rec = store.get(ent)
        if rec is not None and _canary(env) == rec.canary and net > 0:
            answer = rec.outcome
            reuses += 1
        else:
            answer = truth
            store[ent] = Stored(outcome=truth, deps=dict(env), canary=_canary(env))
            rederives += 1
        if answer == truth:
            correct += 1
        else:
            fv += 1
    ok = fv == 0 and correct == n_tasks and reuses > 0 and set(store) == {"alpha", "beta"}
    return {
        "lane": "E coexisting drifts",
        "claim": "two entities drifting at once stay independent: per-record fingerprint, "
                 "0 false-valid, no cross-invalidation or over-merge",
        "ok": ok,
        "evidence": {
            "tasks": n_tasks, "false_valid": fv, "reuses": reuses, "rederives": rederives,
            "records": sorted(store),
        },
    }


def lane_cost_model() -> dict[str, object]:
    """Lane F: the per-dependency-check collapse point is NOT a universal "deps>=4" -- it MOVES
    with the derive/check/recall ratio. For each cost model, find the smallest dep count at
    which ledger-v1 stops reusing (collapses to no-memory) and confirm it matches the analytic
    prediction; confirm the canary stays 0 false-valid and cheaper than re-deriving whenever one
    fingerprint check still pays (derive > check + recall)."""
    rows: list[dict[str, object]] = []
    ok = True
    models = ((5, 1, 1), (8, 1, 1), (10, 2, 1), (6, 1, 2), (4, 1, 1), (2, 1, 1))
    for d_t, c_t, r_t in models:
        cm = CostModel(derive_turns=d_t, check_turns=c_t, recall_turns=r_t)
        collapse_at: int | None = None
        for n_deps in range(1, 16):
            deps = tuple((f"dep{i}", "a", "b", 10 + 5 * i) for i in range(n_deps))
            sc = Scenario(n_tasks=160, deps=deps, scope_dim="dep0",
                          noise=(("ci_runner", 0),), cost=cm)
            if run_arm("ledger-v1", sc).turns == run_arm("no-memory", sc).turns:
                collapse_at = n_deps
                break
        predicted = next((n for n in range(1, 16) if n * c_t >= d_t - r_t), None)
        sc6 = Scenario(n_tasks=160,
                       deps=tuple((f"dep{i}", "a", "b", 10 + 5 * i) for i in range(6)),
                       scope_dim="dep0", noise=(("ci_runner", 0),), cost=cm)
        cv = run_arm("ledger-canary", sc6)
        nm = run_arm("no-memory", sc6)
        canary_can_reuse = d_t - c_t - r_t > 0
        canary_correct = cv.false_valid == 0
        canary_cheaper = cv.turns < nm.turns if canary_can_reuse else cv.turns == nm.turns
        match = collapse_at == predicted
        ok = ok and match and canary_correct and canary_cheaper
        rows.append({
            "derive/check/recall": f"{d_t}/{c_t}/{r_t}",
            "v1_collapse_at_deps": collapse_at, "predicted": predicted, "matches": match,
            "canary_can_reuse": canary_can_reuse, "canary_false_valid": cv.false_valid,
            "canary_turns@6deps": cv.turns, "no_memory_turns@6deps": nm.turns,
        })
    return {
        "lane": "F cost-model sensitivity",
        "claim": "the per-dep collapse point moves with the derive/check/recall ratio (matches "
                 "analytic); the canary stays 0 false-valid and cheaper whenever one fingerprint "
                 "check still pays (derive > check + recall)",
        "ok": ok,
        "evidence": {"rows": rows},
    }


def _interleaved_canary(n_entities: int, n_tasks: int, seed: int) -> dict[str, object]:
    """Run the canary policy over `n_entities` entities queried round-robin, each drifting once
    on its own schedule. Distinct scope keys -> distinct records -> independent fingerprints."""
    rng = random.Random(seed)
    ents = [f"e{i}" for i in range(n_entities)]
    drift = {e: rng.randint(2, max(3, n_tasks)) for e in ents}
    store: dict[str, Stored] = {}
    fv = correct = reuses = 0
    net = DERIVE_TURNS - CHECK_TURNS - RECALL_TURNS
    for t in range(n_tasks):
        e = ents[t % n_entities]
        env = {"entity": e, "state": "x" if t < drift[e] else "y"}
        truth = f"{e}:{env['state']}"
        rec = store.get(e)
        if rec is not None and _canary(env) == rec.canary and net > 0:
            answer = rec.outcome
            reuses += 1
        else:
            answer = truth
            store[e] = Stored(outcome=truth, deps=dict(env), canary=_canary(env))
        if answer == truth:
            correct += 1
        else:
            fv += 1
    return {
        "n_entities": n_entities, "n_tasks": n_tasks, "false_valid": fv,
        "reuse_rate": round(reuses / n_tasks, 4), "records": len(store),
        "records_ok": len(store) == n_entities,
    }


def lane_scale() -> dict[str, object]:
    """Lane G: numbers across CORPUS SIZE (tasks) and ENTITY COUNT (coexisting scope keys). The
    canary stays 0 false-valid and keeps saving turns+cost from 30 to 10k tasks (no small-n
    artifact), and keeps records separate from 1 to 200 entities (no merge at scale)."""
    size_rows: list[dict[str, object]] = []
    for n in (30, 120, 500, 2000, 10000):
        sc = Scenario(n_tasks=n)
        cv = run_arm("ledger-canary", sc)
        nm = run_arm("no-memory", sc)
        size_rows.append({
            "n_tasks": n,
            "canary_false_valid_rate": round(cv.false_valid / cv.tasks, 4),
            "canary_turns_per_task": round(cv.turns / cv.tasks, 4),
            "canary_tokens_per_task": round(cv.tokens / cv.tasks, 1),
            "canary_usd": cv.usd, "no_memory_usd": nm.usd,
            "pct_turns_saved": round(100 * (nm.turns - cv.turns) / nm.turns, 1),
            "pct_usd_saved": round(100 * (nm.usd - cv.usd) / nm.usd, 1),
        })
    entity_rows = [_interleaved_canary(e, max(e * 20, 200), seed=7)
                   for e in (1, 2, 10, 50, 200)]
    sizes_correct = all(cast("float", r["canary_false_valid_rate"]) == 0 for r in size_rows)
    sizes_save = all(cast("float", r["pct_turns_saved"]) > 0 for r in size_rows)
    entities_correct = all(cast("int", r["false_valid"]) == 0 and cast("bool", r["records_ok"])
                           for r in entity_rows)
    ok = sizes_correct and sizes_save and entities_correct
    return {
        "lane": "G scale & corpora",
        "claim": "canary stays 0 false-valid and keeps saving turns+cost from 30 to 10k tasks, "
                 "and keeps records separate from 1 to 200 coexisting entities (no merge)",
        "ok": ok,
        "evidence": {"corpus_size_rows": size_rows, "entity_rows": entity_rows},
    }


def lanes() -> dict[str, object]:
    """Run every assurance lane and report a pass/fail scoreboard."""
    results = [
        lane_generality(),
        lane_breadth_noise(),
        lane_semantic_blindspot(),
        lane_scaling(),
        lane_coexisting(),
        lane_cost_model(),
        lane_scale(),
    ]
    return {
        "benchmark": "outcome_reuse_lanes",
        "all_ok": all(cast("bool", r["ok"]) for r in results),
        "lanes": results,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _lanes_markdown(report: dict[str, object]) -> str:
    lanes_list = cast("list[dict[str, object]]", report["lanes"])
    verdict_all = "ALL LANES PASS" if report["all_ok"] else "FAILURES PRESENT"
    lines = [
        "# Canary Assurance Lanes",
        "",
        f"Generated {report['generated_at']} · overall: {verdict_all}",
        "",
        "| lane | verdict | claim |",
        "| --- | --- | --- |",
    ]
    for ln in lanes_list:
        lines.append(f"| {ln['lane']} | {'PASS' if ln['ok'] else 'FAIL'} | {ln['claim']} |")
    lines.append("")
    for ln in lanes_list:
        lines.append(f"## {ln['lane']} -- {'PASS' if ln['ok'] else 'FAIL'}")
        ev = cast("dict[str, object]", ln["evidence"])
        scalars: list[tuple[str, object]] = []
        for k, v in ev.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                table = cast("list[dict[str, object]]", v)
                cols = list(table[0].keys())
                lines.append(f"_{k}_:")
                lines.append("| " + " | ".join(cols) + " |")
                lines.append("| " + " | ".join("---" for _ in cols) + " |")
                for r in table:
                    lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
                lines.append("")
            else:
                scalars.append((k, v))
        for k, v in scalars:
            lines.append(f"- {k}: {v}")
        if scalars:
            lines.append("")
    return "\n".join(lines) + "\n"


def _markdown(report: dict[str, object]) -> str:
    arms = cast("list[dict[str, object]]", report["arms"])
    base = next((a for a in arms if a["arm"] == "no-memory"), None)
    base_turns = cast(int, base["turns"]) if base else 0
    cols = ["arm", "accuracy", "false_valid_rate", "turns", "tokens", "usd", "latency_s",
            "reuse_rate", "rederives"]
    lines = [
        "# Outcome-Reuse Benchmark (cost-gated, dependency-checked memory)",
        "",
        f"Tasks: {report['tasks']} · detect_lag {report['detect_lag']} · noise_period "
        f"{report['noise_period']} · cost model {report['cost_model']} · "
        f"{report['generated_at']}",
        "",
        "| " + " | ".join([*cols, "turns_saved_vs_no_memory"]) + " |",
        "| " + " | ".join("---" for _ in range(len(cols) + 1)) + " |",
    ]
    for a in arms:
        saved = base_turns - cast(int, a["turns"])
        pct = f"{round(100 * saved / base_turns, 1)}%" if base_turns else "-"
        lines.append("| " + " | ".join(str(a[c]) for c in cols) + f" | {saved} ({pct}) |")
    lines += [
        "",
        "Lower is better: false_valid_rate, turns, turns_per_task. Higher is better: "
        "accuracy. `false_valid_rate` = fraction of tasks where the arm REUSED a stale "
        "outcome (confident and wrong).",
        "`no-memory` always re-derives (correct, dearest). `naive-cache` reuses on the "
        "scope/router key with no dependency checks (cheap, false-valid when a non-scope "
        "dependency drifts). `ledger-v1` checks every DECLARED dependency (0 false-valid, "
        "but the check cost eats most of the turn savings: verify approaches derive). "
        "`ledger-underdecl` omits ONE real dependency, so it false-valids on exactly that "
        "dimension's drift: the gate is only as good as the declared dependency set.",
        "`ledger-learn` starts under-declared but LEARNS the missed dependency after the "
        "miss surfaces `detect_lag` tasks downstream, then converges toward ledger-v1. It "
        "suffers a bounded burst of false-valids (the lag) plus a corrective re-derive, "
        "then stops. CAVEAT: this assumes the miss IS detected; with a large detect_lag (or "
        "a silent failure that never surfaces) ledger-learn degrades to ledger-underdecl.",
        "`ledger-canary` replaces per-dependency checks with ONE cheap broad fingerprint of "
        "the env. It is UNDER-declared like ledger-underdecl yet stays 0 false-valid, because "
        "the fingerprint catches undeclared drift too: robustness WITHOUT perfect "
        "declaration. The cost is over-invalidation: it also re-derives when irrelevant churn "
        "(ci_runner, every noise_period tasks) flips. Smaller noise_period -> more "
        "over-invalidation -> the canary degrades toward no-memory. Scoping the fingerprint "
        "(excluding known-irrelevant churn) is a coarser, more forgiving form of declaration.",
        "`ledger-tiered` keeps the broad fingerprint but, on a trip, checks a NARROW "
        "fingerprint (declared dims) before re-deriving: a noise-only trip is reused, not "
        "re-derived, so the over-invalidation cost is removed. It reuses an undeclared-relevant "
        "drift once (false-valid) then LEARNS it. Net: it matches the canary on clean tasks "
        "and beats it as churn rises (reuse vs re-derive on noise), at a small learning lag.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Outcome-reuse benchmark (policy simulation)")
    ap.add_argument("--tasks", type=int, default=120)
    ap.add_argument("--detect-lag", type=int, default=2,
                    help="tasks before a false-valid reuse surfaces for ledger-learn "
                         "(high lag = detection never happens -> learn == underdecl)")
    ap.add_argument("--noise-period", type=int, default=10,
                    help="how often the irrelevant ci_runner dimension flips; smaller = more "
                         "churn = the broad ledger-canary over-invalidates toward no-memory")
    ap.add_argument("--out", default=None, help="output dir (default benchmarks/runs/<date>)")
    ap.add_argument("--lanes", action="store_true",
                    help="run the canary assurance lanes (generality, breadth x noise, "
                         "semantic blind spot, scaling, coexisting drifts) instead of one run")
    args = ap.parse_args()

    default_dir = Path("benchmarks/runs") / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir = Path(args.out) if args.out else default_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.lanes:
        report = lanes()
        (out_dir / "LanesAssurance.json").write_text(json.dumps(report, indent=2))
        (out_dir / "LanesAssurance.md").write_text(_lanes_markdown(report))
        print(_lanes_markdown(report))
        print(f"wrote {out_dir}/LanesAssurance.{{md,json}}")
        return

    report = run(args.tasks, args.detect_lag, args.noise_period)
    (out_dir / "OutcomeReuse.json").write_text(json.dumps(report, indent=2))
    (out_dir / "OutcomeReuse.md").write_text(_markdown(report))
    print(_markdown(report))
    print(f"wrote {out_dir}/OutcomeReuse.{{md,json}}")


if __name__ == "__main__":
    main()
