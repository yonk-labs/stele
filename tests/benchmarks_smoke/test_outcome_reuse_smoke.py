"""Smoke + core-claim regression for the outcome-reuse benchmark.

Pins the honest signals of cost-gated, dependency-checked memory reuse:
- always-re-derive and a FULLY-declared ledger are both 0 false-valid (correct);
- naive caching (no dependency checks) is cheap but mostly wrong;
- a dependency check costs real turns, so the full ledger saves less than naive;
- UNDER-declaring one dependency reintroduces false-valid reuse (the gate is only as good
  as the declared dependency set), but still beats no checks at all.
"""

from __future__ import annotations

from typing import cast

from benchmarks.outcome_reuse import (
    ARMS,
    lane_breadth_noise,
    lane_coexisting,
    lane_cost_model,
    lane_generality,
    lane_scale,
    lane_scaling,
    lane_semantic_blindspot,
    lanes,
    run,
)


def _arms(report: dict[str, object]) -> dict[str, dict[str, object]]:
    arms = cast("list[dict[str, object]]", report["arms"])
    return {cast("str", a["arm"]): a for a in arms}


def test_outcome_reuse_claims() -> None:
    report = run(n_tasks=120)
    arms = _arms(report)
    assert set(ARMS) == set(arms)

    def m(arm: str, key: str) -> float:
        return cast("float", arms[arm][key])

    # Correct policies: always re-derive, and a fully-declared ledger, never act on stale.
    assert m("no-memory", "accuracy") == 1.0
    assert m("no-memory", "false_valid_rate") == 0.0
    assert m("ledger-v1", "accuracy") == 1.0
    assert m("ledger-v1", "false_valid_rate") == 0.0

    # Naive caching (no checks) is cheap but mostly wrong.
    assert m("naive-cache", "false_valid_rate") > 0.5
    assert m("naive-cache", "turns") < m("ledger-v1", "turns")  # checks cost real turns

    # The full ledger still saves turns vs always-re-deriving (reuse pays, modestly).
    assert m("ledger-v1", "turns") < m("no-memory", "turns")

    # Under-declaring ONE dependency reintroduces false-valid reuse...
    assert m("ledger-underdecl", "false_valid_rate") > 0.0
    assert m("ledger-underdecl", "false_valid_rate") > m("ledger-v1", "false_valid_rate")
    # ...but it is still no worse than having no checks at all.
    assert m("ledger-underdecl", "false_valid_rate") <= m("naive-cache", "false_valid_rate")


def test_outcome_reuse_learning_loop() -> None:
    arms = _arms(run(n_tasks=120))

    def m(arm: str, key: str) -> float:
        return cast("float", arms[arm][key])

    # The post-miss learning loop collapses the false-valid rate vs never learning...
    assert m("ledger-learn", "false_valid_rate") < m("ledger-underdecl", "false_valid_rate")
    assert m("ledger-learn", "accuracy") > m("ledger-underdecl", "accuracy")
    # ...but it is NOT free: the detection lag costs some false-valids before it converges.
    assert m("ledger-learn", "false_valid_rate") > 0.0
    assert m("ledger-learn", "accuracy") < m("no-memory", "accuracy")

    # Honest caveat: if the miss never surfaces (lag past the horizon), learning cannot
    # happen and ledger-learn degrades EXACTLY to ledger-underdecl.
    nolearn = _arms(run(n_tasks=120, detect_lag=999))
    assert (nolearn["ledger-learn"]["false_valid_rate"]
            == nolearn["ledger-underdecl"]["false_valid_rate"])
    assert nolearn["ledger-learn"]["turns"] == nolearn["ledger-underdecl"]["turns"]


def test_outcome_reuse_canary_robustness() -> None:
    arms = _arms(run(n_tasks=120))  # default noise_period=10

    def m(arm: str, key: str) -> float:
        return cast("float", arms[arm][key])

    # The canary is UNDER-declared (same declared set as ledger-underdecl) yet stays correct:
    # the broad fingerprint catches undeclared drift -> robustness WITHOUT perfect declaration.
    assert m("ledger-canary", "accuracy") == 1.0
    assert m("ledger-canary", "false_valid_rate") == 0.0
    assert m("ledger-canary", "false_valid_rate") < m("ledger-underdecl", "false_valid_rate")
    # The honest cost: it over-invalidates (re-derives on irrelevant churn ledger-v1 ignores).
    assert m("ledger-canary", "rederives") > m("ledger-v1", "rederives")

    # Over-invalidation scales with churn: more noise -> more re-derives -> dearer (the
    # tunable robustness/efficiency tradeoff). Robustness (0 false-valid) holds throughout.
    busy = _arms(run(n_tasks=120, noise_period=2))
    assert cast("int", busy["ledger-canary"]["turns"]) > cast("int", arms["ledger-canary"]["turns"])
    assert busy["ledger-canary"]["false_valid_rate"] == 0.0


def test_outcome_reuse_tiered_vs_canary() -> None:
    low = _arms(run(n_tasks=120, noise_period=10))
    high = _arms(run(n_tasks=120, noise_period=2))

    def turns(d: dict[str, dict[str, object]], arm: str) -> int:
        return cast("int", d[arm]["turns"])

    # High churn: tiered avoids the canary's over-invalidation (reuse on noise, not
    # re-derive), so it is cheaper AND re-derives far less.
    assert turns(high, "ledger-tiered") < turns(high, "ledger-canary")
    assert (cast("int", high["ledger-tiered"]["rederives"])
            < cast("int", high["ledger-canary"]["rederives"]))
    # Tiered is roughly churn-immune; the canary degrades toward no-memory as churn rises.
    assert turns(high, "ledger-canary") > turns(low, "ledger-canary")
    # Tiered's cost is a small learning lag the canary avoids (correctness, not a free lunch).
    assert cast("float", low["ledger-tiered"]["false_valid_rate"]) > 0.0
    assert cast("float", low["ledger-tiered"]["accuracy"]) > 0.95


# === assurance lanes: properties that must hold ACROSS swept configs, not just one =========


def test_lane_generality_holds_across_random_schedules() -> None:
    """Lane A: the canary's 0-false-valid + correct + never-costlier headline is not an
    artifact of the one hand-tuned schedule -- it holds across many random schedules/seeds."""
    v = lane_generality(n_scenarios=300, seed=0)
    assert v["ok"], v
    ev = cast("dict[str, object]", v["evidence"])
    assert ev["canary_false_valid_max"] == 0.0
    assert ev["canary_accuracy_min"] == 1.0
    assert ev["scenarios_costlier_than_no_memory"] == 0
    # a different seed must not break it either (true generality, not seed-luck).
    assert lane_generality(n_scenarios=300, seed=12345)["ok"]


def test_lane_breadth_noise_frontier() -> None:
    """Lane B: narrowing the slice past the real deps reopens the under-declaration hole; the
    sweet spot (all real deps, exclude noise) is correct AND noise-immune; full-env is correct
    but over-invalidates as churn rises."""
    assert lane_breadth_noise()["ok"]


def test_lane_semantic_blindspot_is_the_boundary() -> None:
    """Lane C: out-of-slice (semantic) drift is the canary's known boundary -- but it is NOT a
    canary-specific weakness: the fully-declared ledger-v1 false-valids identically, and only
    always-re-deriving is immune."""
    v = lane_semantic_blindspot()
    assert v["ok"], v
    ev = cast("dict[str, object]", v["evidence"])
    assert cast("float", ev["canary_false_valid"]) > 0.0
    assert ev["canary_false_valid"] == ev["ledger_v1_false_valid"]
    assert ev["no_memory_false_valid"] == 0.0


def test_lane_scaling_canary_beats_per_dep_checking() -> None:
    """Lane D: per-dependency checking collapses to no-memory once the checklist costs as much
    as deriving (deps>=4); the canary's single fingerprint keeps reusing at any dep count, and
    its full-env over-invalidation grows with independent noise sources while staying correct."""
    v = lane_scaling()
    assert v["ok"], v
    ev = cast("dict[str, object]", v["evidence"])
    dep_rows = cast("list[dict[str, object]]", ev["dep_rows"])
    big = next(r for r in dep_rows if r["n_deps"] == 8)
    assert big["v1_collapsed_to_no_memory"] is True       # per-dep checking gives up
    assert big["canary_cheaper_than_no_memory"] is True   # the fingerprint does not


def test_lane_coexisting_entities_stay_independent() -> None:
    """Lane E: two entities drifting at once keep separate records and separate fingerprints --
    no cross-invalidation, no over-merge, 0 false-valid."""
    v = lane_coexisting()
    assert v["ok"], v
    ev = cast("dict[str, object]", v["evidence"])
    assert ev["false_valid"] == 0
    assert ev["records"] == ["alpha", "beta"]


def test_lane_cost_model_collapse_point_moves() -> None:
    """Lane F: the deps>=4 collapse is cost-model-dependent, not universal. Across cost models
    the v1 collapse point matches the analytic prediction and the canary stays correct and
    cheaper whenever a single fingerprint check still pays off."""
    v = lane_cost_model()
    assert v["ok"], v
    rows = cast("list[dict[str, object]]", cast("dict[str, object]", v["evidence"])["rows"])
    collapse = {cast("str", r["derive/check/recall"]): r["v1_collapse_at_deps"] for r in rows}
    # the crossover genuinely MOVES with the ratio (not a fixed 4).
    assert collapse["5/1/1"] == 4
    assert collapse["8/1/1"] == 7
    assert len({str(c) for c in collapse.values()}) > 1


def test_lane_scale_holds_across_sizes_and_corpora() -> None:
    """Lane G: 0 false-valid and positive savings from 30 to 10k tasks; record count tracks
    entity count from 1 to 200 coexisting entities (no merge at scale)."""
    v = lane_scale()
    assert v["ok"], v
    ev = cast("dict[str, object]", v["evidence"])
    size_rows = cast("list[dict[str, object]]", ev["corpus_size_rows"])
    assert all(r["canary_false_valid_rate"] == 0 for r in size_rows)
    assert all(cast("float", r["pct_turns_saved"]) > 0 for r in size_rows)
    entity_rows = cast("list[dict[str, object]]", ev["entity_rows"])
    big = next(r for r in entity_rows if r["n_entities"] == 200)
    assert big["false_valid"] == 0
    assert big["records"] == 200


def test_all_assurance_lanes_pass() -> None:
    """The scoreboard: every independent lane confirms the canary."""
    report = lanes()
    failed = [cast("str", ln["lane"]) for ln in cast("list[dict[str, object]]", report["lanes"])
              if not ln["ok"]]
    assert report["all_ok"], f"failing lanes: {failed}"
