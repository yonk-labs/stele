"""Smoke: the memory value-proof actually demonstrates its divergence.

Guards the claim itself, not just that the script runs: stele must recall the
needle at every budget, and the no-memory baseline must fail at a realistic one.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.memory_value_proof import run


def test_value_proof_demonstrates_divergence(tmp_path: Path) -> None:
    report = run("memory", output_root=tmp_path, write=True)

    # stele answers correctly regardless of context budget.
    assert report.stele_row["correct_without_refetch"] is True

    # The baseline only keeps the early needle when the window holds the whole
    # session; at realistic budgets it loses it.
    assert report.summary["baseline_correct_count"] < report.summary["baseline_total"]
    assert report.summary["realistic_baseline_correct"] is False

    # The whole point: stele costs fewer tokens to be correct at the realistic budget.
    assert report.summary["realistic_total_reduction_pct"] > 0

    # Report was written where asked.
    assert list(tmp_path.glob("*/MemoryValueProof.md"))
