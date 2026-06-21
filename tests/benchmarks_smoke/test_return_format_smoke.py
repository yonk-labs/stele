"""No-network smoke for the return-format experiment: the 2-turn verify loop,
reply parsing, and scoring, driven by stub LLMs (real-model runs are out of CI)."""

from __future__ import annotations

import re
from typing import cast

from benchmarks.return_format import FORMATS, run


def _formats(report: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", report["formats"])


def _stub_verify_then_truth(prompt: str) -> str:
    # Follow-up prompt echoes the authoritative value; commit it. Otherwise verify.
    m = re.search(r"verify\(\) returned:\s*(\S+)", prompt)
    if m:
        return f"ANSWER: {m.group(1)}"
    return "VERIFY"


def _stub_always_stale(_prompt: str) -> str:
    return "ANSWER: nonsense-value"


def test_verify_loop_reaches_truth() -> None:
    report = run(_stub_verify_then_truth)
    fmts = {r["format"]: r for r in _formats(report)}
    assert set(fmts) == set(FORMATS)
    # An agent that always verifies then commits the returned value is always correct.
    for fmt in FORMATS:
        assert fmts[fmt]["accuracy"] == 1.0
        assert fmts[fmt]["verify_rate"] == 1.0


def test_never_verify_wrong_answer_scores_zero() -> None:
    report = run(_stub_always_stale)
    for r in _formats(report):
        assert r["accuracy"] == 0.0
        assert r["verify_rate"] == 0.0
