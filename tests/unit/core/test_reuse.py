"""Pure canary reuse-gate logic (no I/O, no LLM): fingerprint + validity check.

Mirrors the validated mechanism in benchmarks/outcome_reuse.py (`_canary`): one cheap broad
fingerprint of the observable environment decides whether a stored outcome is still valid to
reuse. Drift anywhere IN the fingerprinted slice (including undeclared dimensions) invalidates;
only drift OUTSIDE the slice slips through (the semantic blind spot, measured in the lanes).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from stele.core.reuse import (
    decide_canary,
    decide_tiered,
    fingerprint,
    is_expired,
    is_stale,
    is_valid,
    source_hash,
    worth_reusing,
)


def test_valid_when_environment_unchanged() -> None:
    env = {"db_version": "18", "workload": "analytics"}
    fp = fingerprint(env)
    assert is_valid(fp, env) is True


def test_invalid_when_a_declared_dimension_drifts() -> None:
    env = {"db_version": "18", "workload": "analytics"}
    fp = fingerprint(env)
    drifted = {"db_version": "18", "workload": "oltp"}
    assert is_valid(fp, drifted) is False


def test_canary_catches_undeclared_drift() -> None:
    # the whole point: a dimension nobody declared still moves the broad fingerprint.
    env = {"db_version": "18", "workload": "analytics", "data_volume": "small"}
    fp = fingerprint(env)
    drifted = {**env, "data_volume": "large"}
    assert is_valid(fp, drifted) is False


def test_fingerprint_is_order_independent() -> None:
    assert fingerprint({"x": "1", "y": "2"}) == fingerprint({"y": "2", "x": "1"})


def test_is_valid_tolerates_json_roundtrip_shape() -> None:
    # the stored fingerprint comes back from metadata as list-of-lists, not tuples.
    env = {"a": "1", "b": "2"}
    stored = json.loads(json.dumps(fingerprint(env)))
    assert is_valid(stored, env) is True


def test_dims_scopes_the_slice_to_exclude_noise() -> None:
    # the tuning knob: fingerprint only declared dims, so irrelevant churn does not trip it.
    env = {"db_version": "18", "ci_runner": "A"}
    fp = fingerprint(env, dims=("db_version",))
    noisy = {"db_version": "18", "ci_runner": "B"}
    assert is_valid(fp, noisy, dims=("db_version",)) is True


def test_decide_canary_reuse_and_drift() -> None:
    env = {"a": "1", "b": "2"}
    fp = fingerprint(env)
    assert decide_canary(fp, env).reuse is True
    assert decide_canary(fp, {"a": "1", "b": "9"}).reason == "drift"


def test_decide_tiered_reuses_noise_only_trip() -> None:
    # broad covers dep + noise; declared = [dep]. Only noise changed -> reuse, not re-derive.
    fp = fingerprint({"dep": "1", "noise": "A"})
    out = decide_tiered(fp, None, ["dep"], {"dep": "1", "noise": "A"},
                        {"dep": "1", "noise": "B"})
    assert out.reuse is True
    assert out.reason == "reused-noise"


def test_decide_tiered_rederives_on_declared_drift() -> None:
    fp = fingerprint({"dep": "1", "noise": "A"})
    out = decide_tiered(fp, None, ["dep"], {"dep": "1", "noise": "A"},
                        {"dep": "2", "noise": "A"})
    assert out.reuse is False
    assert out.reason == "drift"


def test_worth_reusing_gate() -> None:
    assert worth_reusing(None, 1) is True            # no cost spine -> gate off
    assert worth_reusing({}, 1) is True              # empty -> off
    assert worth_reusing({"derive": 5}, 1) is True   # deep derive: 5-1-1=3 > 0
    assert worth_reusing({"derive": 2}, 1) is False  # cheap derive: 2-1-1=0, not worth
    assert worth_reusing({"derive": 5}, 2) is True   # tiered (2 checks): 5-2-1=2 > 0
    assert worth_reusing({"derive": 3}, 2) is False  # 3-2-1=0, not worth


def test_decide_canary_cost_gate() -> None:
    env = {"a": "1"}
    fp = fingerprint(env)
    cheap = decide_canary(fp, env, None, cost={"derive": 2})
    assert cheap.reuse is False
    assert cheap.reason == "not-worth-reuse"
    assert decide_canary(fp, env, None, cost={"derive": 5}).reuse is True


def test_decide_tiered_cost_gate_on_noise_trip() -> None:
    # a noise-only trip would reuse, but a cheap derivation makes the 2-check reuse not worth it.
    fp = fingerprint({"dep": "1", "noise": "A"})
    out = decide_tiered(fp, None, ["dep"], {"dep": "1", "noise": "A"},
                        {"dep": "1", "noise": "B"}, cost={"derive": 3})
    assert out.reuse is False
    assert out.reason == "not-worth-reuse"


def test_not_expired_when_ttl_unset() -> None:
    # default None = off (back-compat): an outcome with no TTL never expires.
    created = datetime(2026, 1, 1, tzinfo=UTC)
    assert is_expired(created, None, created + timedelta(days=3650)) is False


def test_not_expired_within_ttl_window() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    assert is_expired(created, 3600, created + timedelta(seconds=10)) is False


def test_expired_past_ttl_window() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    assert is_expired(created, 3600, created + timedelta(seconds=7200)) is True


def test_not_expired_exactly_at_ttl_boundary() -> None:
    # boundary is inclusive of the window: age == ttl is still fresh (strict >).
    created = datetime(2026, 1, 1, tzinfo=UTC)
    assert is_expired(created, 3600, created + timedelta(seconds=3600)) is False


def test_fresh_when_source_hash_matches_within_ttl() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    stored = source_hash("def cards(): ...")
    now = created + timedelta(seconds=10)
    assert is_stale(stored, "def cards(): ...", created, 3600, now) is False


def test_stale_when_source_hash_differs() -> None:
    # observable drift: the file changed, so the context is stale regardless of TTL.
    created = datetime(2026, 1, 1, tzinfo=UTC)
    stored = source_hash("def cards(): ...")
    now = created + timedelta(seconds=10)
    assert is_stale(stored, "def cards(): CHANGED", created, 3600, now) is True


def test_stale_when_expired_even_if_hash_matches() -> None:
    # TTL is the backstop: trust nothing past the window even when bytes are identical.
    created = datetime(2026, 1, 1, tzinfo=UTC)
    stored = source_hash("x")
    now = created + timedelta(seconds=7200)
    assert is_stale(stored, "x", created, 3600, now) is True


def test_fresh_unverified_when_no_source_within_ttl() -> None:
    # caller passed no source: freshness rests on TTL alone (the unverified-source case).
    created = datetime(2026, 1, 1, tzinfo=UTC)
    now = created + timedelta(seconds=10)
    assert is_stale(source_hash("x"), None, created, 3600, now) is False


def test_no_stored_hash_falls_back_to_ttl() -> None:
    # context recorded without a source hash: cannot verify bytes, so TTL governs.
    created = datetime(2026, 1, 1, tzinfo=UTC)
    now = created + timedelta(seconds=10)
    assert is_stale(None, "anything", created, 3600, now) is False


def test_source_hash_is_stable_and_distinct() -> None:
    assert source_hash("abc") == source_hash("abc")
    assert source_hash("abc") != source_hash("abd")
