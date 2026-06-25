"""Smoke + core-claim regression for the evolving-world agent simulation.

Pins the headline claims and the issue #72 gates (on sqlite, fast):
- stele-full's recall payload is no larger than naive-append's (token win);
- memory-backed arms re-explore less than no-memory (turn win);
- store-side: stele-full leaves no MORE active staleness than naive-append, and
  the residual staleness is concentrated in the value-named (#72) class, not the
  stable-subject class the registry already handles;
- precision gate: stele-full never over-merges distinct entities (rate == 0).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import cast

from benchmarks.evolving_world import ARMS, run


def _arms_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    arms = cast("list[dict[str, object]]", report["arms"])
    return {cast("str", a["arm"]): a for a in arms}


def test_evolving_world_headline_and_72_gates() -> None:
    with tempfile.TemporaryDirectory() as d:
        backend: dict[str, object] = {"type": "sqlite", "path": str(Path(d) / "ew.db")}
        report = run(n_sessions=132, backend=backend, with_role_fix=True)

    arms = _arms_by_name(report)
    assert set(ARMS) | {"stele-role"} == set(arms)

    def metric(arm: str, key: str) -> float:
        return cast("float", arms[arm][key])

    def by_class(arm: str) -> dict[str, float]:
        return cast("dict[str, float]", arms[arm]["stale_by_class"])

    assert metric("stele-full", "sessions") == report["sessions"] == 132

    # (c) clean current-state recall is no more token-heavy than ever-growing append.
    assert metric("stele-full", "tokens") <= metric("naive-append", "tokens")

    # (a) memory cuts re-exploration turns vs having no memory at all.
    assert metric("stele-full", "turns") <= metric("no-memory", "turns")

    # store-side (#72): the new machinery leaves no MORE active staleness than blind append.
    full_stale = metric("stele-full", "active_staleness_rate")
    assert full_stale <= metric("naive-append", "active_staleness_rate")

    # precision gate: distinct entities must never be wrongly merged, fix on or off.
    assert metric("stele-full", "over_merge_rate") == 0.0
    assert metric("stele-role", "over_merge_rate") == 0.0

    # #72 localization: for stele-full, residual staleness lives in the value-named
    # class, not the stable-subject class the registry already resolves cleanly.
    assert by_class("stele-full").get("stable", 0.0) <= by_class("stele-full").get("value", 0.0)

    # the role-anchor fix collapses value-named staleness without regressing the
    # stable class (and over-merge stays 0, asserted above).
    assert by_class("stele-role").get("value", 1.0) <= by_class("stele-full").get("value", 1.0)
    role_stale = metric("stele-role", "active_staleness_rate")
    assert role_stale <= metric("stele-full", "active_staleness_rate")


def test_evolving_world_ledger_arm() -> None:
    """The memory-value thesis arm: store the verification METHOD, not the value.
    Pins the honest claims - 0 staleness by construction and never returning a
    stale value (the win), AND the cost: it pays re-derivation turns the
    value-caching arms skip (correctness is not free)."""
    with tempfile.TemporaryDirectory() as d:
        backend: dict[str, object] = {"type": "sqlite", "path": str(Path(d) / "ew.db")}
        report = run(n_sessions=132, backend=backend, with_ledger=True)

    arms = _arms_by_name(report)
    assert "stele-ledger" in arms

    def metric(arm: str, key: str) -> float:
        return cast("float", arms[arm][key])

    led_by_class = cast("dict[str, float]", arms["stele-ledger"]["stale_by_class"])
    # The win: no asserted value can go stale, so #72 value-class staleness is 0,
    # and the agent never returns a stale value.
    assert metric("stele-ledger", "active_staleness_rate") == 0.0
    assert led_by_class.get("value", 1.0) == 0.0
    assert led_by_class.get("stable", 1.0) == 0.0
    assert metric("stele-ledger", "stale_action_rate") == 0.0
    # Precision gate: distinct coexisting entities keep their methods (no merge).
    assert metric("stele-ledger", "over_merge_rate") == 0.0
    # At least as correct as the safe re-deriving baseline (no-memory).
    assert metric("stele-ledger", "accuracy") >= metric("no-memory", "accuracy")
    # The honest cost: re-derivation turns the value-caching arms skip for free.
    assert metric("stele-ledger", "turns") >= metric("naive-append", "turns")


def test_evolving_world_silent_changes_and_ttl_frontier() -> None:
    """Silent (unannounced) changes + the freshness-policy frontier. Pins the
    robust signals only (ttl3-vs-ttl10 ordering is small-sample noise):
    - a value-cache that never re-derives goes permanently stale on a silent change;
    - the method-only ledger re-derives every read and stays 0-stale;
    - a bounded TTL reuses within the window, cutting turns vs always re-deriving;
    - trust-forever (ttl=inf) breaks exactly like the naive cache."""
    with tempfile.TemporaryDirectory() as d:
        backend: dict[str, object] = {"type": "sqlite", "path": str(Path(d) / "ew.db")}
        # 350 sessions reaches past the day-22 silent change; ttl 10 vs inf is the
        # cleanest contrast (bounded window recovers, trust-forever does not).
        report = run(n_sessions=350, backend=backend, with_silent=True, ttl_sweep=[10, None])

    arms = _arms_by_name(report)
    assert {"no-memory", "naive-append", "stele-ledger",
            "stele-ledger-ttl10", "stele-ledger-ttlinf"} <= set(arms)

    def metric(arm: str, key: str) -> float:
        return cast("float", arms[arm][key])

    def silent_stale(arm: str) -> float:
        return cast("dict[str, float]", arms[arm]["stale_by_class"]).get("silent", 0.0)

    # The naive value-cache never learns a silent change -> permanently stale.
    assert silent_stale("naive-append") == 1.0
    # The method-only ledger re-derives every read -> never stale on silent changes.
    assert silent_stale("stele-ledger") == 0.0
    # Trust-forever reuse (ttl=inf) breaks exactly like the naive cache.
    assert silent_stale("stele-ledger-ttlinf") == 1.0
    # A bounded freshness window cuts turns vs always re-deriving (reuse pays off)...
    assert metric("stele-ledger-ttl10", "turns") < metric("stele-ledger", "turns")
    # ...while recovering from the silent change the trust-forever arm misses.
    assert silent_stale("stele-ledger-ttl10") < silent_stale("stele-ledger-ttlinf")
    # Precision gate holds for every ledger variant.
    for arm in ("stele-ledger", "stele-ledger-ttl10", "stele-ledger-ttlinf"):
        assert metric(arm, "over_merge_rate") == 0.0
