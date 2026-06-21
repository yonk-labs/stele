"""No-network smoke for the process-memory experiment: the investigate/decide loop,
reply parsing, and rework/consistency scoring, driven by stub LLMs."""

from __future__ import annotations

from typing import cast

from benchmarks.process_memory import ARMS, run


def _arms(report: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", report["arms"])


def _stub_always_rework(_prompt: str) -> str:
    # Picks every rejected/failed option at once -> rework on every scenario.
    return "DECIDE: use kafka and unittest and mongo and a global lock"


def _stub_investigate_then_consistent(prompt: str) -> str:
    # The follow-up prompt is the only one that STARTS with "After re-evaluating".
    if prompt.startswith("After re-evaluating"):
        return "DECIDE: redis streams, pytest, postgres, sharding"
    return "INVESTIGATE"


def test_rework_stub_scores_inconsistent() -> None:
    report = run(_stub_always_rework)
    for r in _arms(report):
        assert r["rework_rate"] == 1.0
        assert r["consistency_rate"] == 0.0


def test_consistent_stub_after_investigation() -> None:
    report = run(_stub_investigate_then_consistent)
    arms = {r["arm"]: r for r in _arms(report)}
    assert set(arms) == set(ARMS)
    for arm in ARMS:
        assert arms[arm]["consistency_rate"] == 1.0
        assert arms[arm]["rework_rate"] == 0.0
        assert arms[arm]["investigate_rate"] == 1.0
