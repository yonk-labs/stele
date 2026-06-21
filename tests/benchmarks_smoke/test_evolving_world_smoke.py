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
        report = run(n_sessions=132, backend=backend)

    arms = _arms_by_name(report)
    assert set(arms) == set(ARMS)

    def metric(arm: str, key: str) -> float:
        return cast("float", arms[arm][key])

    assert metric("stele-full", "sessions") == report["sessions"] == 132

    # (c) clean current-state recall is no more token-heavy than ever-growing append.
    assert metric("stele-full", "tokens") <= metric("naive-append", "tokens")

    # (a) memory cuts re-exploration turns vs having no memory at all.
    assert metric("stele-full", "turns") <= metric("no-memory", "turns")

    # store-side (#72): the new machinery leaves no MORE active staleness than blind append.
    full_stale = metric("stele-full", "active_staleness_rate")
    naive_stale = metric("naive-append", "active_staleness_rate")
    assert full_stale <= naive_stale

    # precision gate: distinct entities must never be wrongly merged.
    assert metric("stele-full", "over_merge_rate") == 0.0

    # #72 localization: for stele-full, residual staleness lives in the value-named
    # class, not the stable-subject class the registry already resolves cleanly.
    sbc = cast("dict[str, float]", arms["stele-full"]["stale_by_class"])
    assert sbc.get("stable", 0.0) <= sbc.get("value", 0.0)
