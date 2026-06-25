"""Outcome reuse via the canary gate on Stele.memory.

record_outcome stores a cached multi-step outcome plus its broad fingerprint (in metadata);
reuse_outcome finds the latest active outcome in scope and decides reuse-or-re-derive by
comparing the stored fingerprint against the current environment.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryScope

SCOPE = MemoryScope(user_id="alice")


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def _record(stele: Stele, env: dict[str, str], **kw: object) -> object:
    return stele.memory.record_outcome(
        text="cfg-outcome",
        source_refs=["stele://default/evidence"],
        scope=SCOPE,
        env=env,
        **kw,  # type: ignore[arg-type]
    )


def test_record_outcome_uses_outcome_kind(stele: Stele) -> None:
    res = _record(stele, {"db_version": "18"})
    got = stele.memory.get(res.record.id)  # type: ignore[attr-defined]
    assert got is not None
    assert got.kind == "outcome"


def test_reuse_when_environment_unchanged(stele: Stele) -> None:
    env = {"db_version": "18", "workload": "analytics"}
    rec = _record(stele, env).record  # type: ignore[attr-defined]
    result = stele.memory.reuse_outcome(SCOPE, env)
    assert result.reuse is True
    assert result.record is not None
    assert result.record.id == rec.id


def test_rederive_when_environment_drifts(stele: Stele) -> None:
    _record(stele, {"db_version": "18", "workload": "analytics"})
    result = stele.memory.reuse_outcome(SCOPE, {"db_version": "18", "workload": "oltp"})
    assert result.reuse is False


def test_reuse_miss_when_nothing_stored(stele: Stele) -> None:
    result = stele.memory.reuse_outcome(SCOPE, {"db_version": "18"})
    assert result.reuse is False
    assert result.record is None


def test_canary_catches_undeclared_drift(stele: Stele) -> None:
    env = {"db_version": "18", "workload": "analytics", "data_volume": "small"}
    _record(stele, env)  # broad fingerprint over all dims; data_volume never "declared"
    result = stele.memory.reuse_outcome(SCOPE, {**env, "data_volume": "large"})
    assert result.reuse is False


def test_fingerprint_dims_excludes_noise(stele: Stele) -> None:
    env = {"db_version": "18", "ci_runner": "A"}
    _record(stele, env, fingerprint_dims=("db_version",))
    # only the excluded noise dimension changed -> still valid to reuse.
    result = stele.memory.reuse_outcome(SCOPE, {"db_version": "18", "ci_runner": "B"})
    assert result.reuse is True


def test_tiered_reuses_noise_only_trip_where_canary_rederives(stele: Stele) -> None:
    # broad fingerprint covers db_version + ci_runner; declared (narrow) = [db_version].
    _record(stele, {"db_version": "18", "ci_runner": "A"}, declared_deps=["db_version"])
    noisy = {"db_version": "18", "ci_runner": "B"}
    canary = stele.memory.reuse_outcome(SCOPE, noisy, mode="canary")
    tiered = stele.memory.reuse_outcome(SCOPE, noisy, mode="tiered")
    assert canary.reuse is False  # canary over-invalidates on noise
    assert tiered.reuse is True  # tiered reuses: only an undeclared dim changed
    assert tiered.reason == "reused-noise"


def test_tiered_rederives_when_declared_dim_drifts(stele: Stele) -> None:
    _record(stele, {"db_version": "18", "ci_runner": "A"}, declared_deps=["db_version"])
    tiered = stele.memory.reuse_outcome(
        SCOPE, {"db_version": "19", "ci_runner": "A"}, mode="tiered"
    )
    assert tiered.reuse is False
    assert tiered.reason == "drift"


def test_tiered_learns_an_undeclared_dependency_from_feedback(stele: Stele) -> None:
    env = {"db_version": "18", "feature_flag": "off"}
    rec = _record(stele, env, declared_deps=["db_version"]).record  # type: ignore[attr-defined]
    drifted = {"db_version": "18", "feature_flag": "on"}
    # undeclared dim flips -> tiered optimistically reuses (a candidate false-valid).
    assert stele.memory.reuse_outcome(SCOPE, drifted, mode="tiered").reason == "reused-noise"
    # the caller detects the bad reuse and teaches the missed dependency.
    stele.memory.learn_dependencies(rec.id, drifted)
    # now the learned dim is declared, so tiered re-derives on that drift.
    after = stele.memory.reuse_outcome(SCOPE, drifted, mode="tiered")
    assert after.reuse is False
    assert after.reason == "drift"


def test_cost_gate_rederives_when_reuse_not_worth_it(stele: Stele) -> None:
    env = {"db_version": "18"}
    _record(stele, env, cost={"derive": 2})  # cheap to re-derive: validate+recall costs as much
    result = stele.memory.reuse_outcome(SCOPE, env)
    assert result.reuse is False
    assert result.reason == "not-worth-reuse"


def test_cost_gate_reuses_when_derivation_is_deep(stele: Stele) -> None:
    env = {"db_version": "18"}
    _record(stele, env, cost={"derive": 20})  # expensive to re-derive: reuse clearly pays
    assert stele.memory.reuse_outcome(SCOPE, env).reuse is True


def test_no_cost_spine_means_gate_off(stele: Stele) -> None:
    env = {"db_version": "18"}
    _record(stele, env)  # no cost recorded -> gate off, reuse on validity (back-compat)
    assert stele.memory.reuse_outcome(SCOPE, env).reuse is True


def test_expired_outcome_is_not_reused_even_when_fingerprint_matches(stele: Stele) -> None:
    # TTL is the time bound on the canary's semantic blind spot: a stale outcome is distrusted
    # even when nothing observable drifted (same env -> fingerprint still matches).
    env = {"db_version": "18"}
    rec = _record(stele, env, ttl_seconds=60).record  # type: ignore[attr-defined]
    past_window = rec.created_at + timedelta(seconds=120)
    result = stele.memory.reuse_outcome(SCOPE, env, now=past_window)
    assert result.reuse is False
    assert result.reason == "expired"  # takes precedence over "fingerprint-match"


def test_fresh_outcome_within_ttl_still_reuses(stele: Stele) -> None:
    env = {"db_version": "18"}
    rec = _record(stele, env, ttl_seconds=3600).record  # type: ignore[attr-defined]
    within_window = rec.created_at + timedelta(seconds=10)
    assert stele.memory.reuse_outcome(SCOPE, env, now=within_window).reuse is True


def test_no_ttl_means_never_expires(stele: Stele) -> None:
    env = {"db_version": "18"}
    # no ttl_seconds -> off (back-compat)
    rec = _record(stele, env).record  # type: ignore[attr-defined]
    far_future = rec.created_at + timedelta(days=3650)
    assert stele.memory.reuse_outcome(SCOPE, env, now=far_future).reuse is True


def test_reuse_outcome_routes_by_intent_not_latest(stele: Stele) -> None:
    # two outcomes, SAME scope + SAME env fingerprint, different intents. Without an intent the
    # latest wins (the cross-task leakage abe flagged); with an intent the matching outcome wins.
    env = {"v": "1"}
    auth = stele.memory.record_outcome(
        text="result of building the auth module",
        source_refs=["stele://default/a"],
        scope=SCOPE,
        env=env,
    ).record
    stele.memory.record_outcome(
        text="result of running the test suite",
        source_refs=["stele://default/b"],
        scope=SCOPE,
        env=env,
    )  # the latest in scope
    latest = stele.memory.reuse_outcome(SCOPE, env)  # no intent -> latest
    assert latest.reuse is True
    assert latest.record is not None
    assert latest.record.text == "result of running the test suite"
    routed = stele.memory.reuse_outcome(SCOPE, env, intent="building the auth module")
    assert routed.reuse is True
    assert routed.record is not None
    assert routed.record.id == auth.id
