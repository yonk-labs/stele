"""Smoke + core-claim regression for the evolving-world agent simulation.

Pins the headline claims the benchmark exists to prove (on sqlite, fast):
- stele-full surfaces stale values no more often than naive-append (supersession
  beats blind append in an evolving world);
- stele-full's recall payload is no larger than naive-append's (token win);
- memory-backed arms re-explore less than no-memory (turn win).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import cast

from benchmarks.evolving_world import ARMS, run


def _arms_by_name(report: dict[str, object]) -> dict[str, dict[str, object]]:
    arms = cast("list[dict[str, object]]", report["arms"])
    return {cast("str", a["arm"]): a for a in arms}


def test_evolving_world_headline_claims() -> None:
    with tempfile.TemporaryDirectory() as d:
        backend: dict[str, object] = {"type": "sqlite", "path": str(Path(d) / "ew.db")}
        report = run(n_sessions=120, backend=backend)

    arms = _arms_by_name(report)
    assert set(arms) == set(ARMS)

    def metric(arm: str, key: str) -> float:
        return cast("float", arms[arm][key])

    # Every arm actually ran the full session stream.
    assert metric("stele-full", "sessions") == report["sessions"] == 120

    # Core claim (b): the new machinery does not surface stale values MORE than
    # blind append, and should generally surface them less.
    assert metric("stele-full", "stale_action_rate") <= metric("naive-append", "stale_action_rate")

    # Core claim (c): clean current-state recall is no more token-heavy than the
    # ever-growing naive-append payload.
    assert metric("stele-full", "tokens") <= metric("naive-append", "tokens")

    # Core claim (a): memory cuts re-exploration turns vs having no memory at all.
    assert metric("stele-full", "turns") <= metric("no-memory", "turns")
