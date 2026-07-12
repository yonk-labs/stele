"""Smoke: the codeview cross-file value-proof runs and is internally coherent.

Guards the proof that informs the codeintel un-freeze decision: codeview's in-file
bounded view shows 0% of cross-file callees; the real GraphResolver recovers them.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.codeview_crossfile_proof import run


def test_crossfile_proof_runs(tmp_path: Path) -> None:
    report = run(output_root=tmp_path, write=True)
    s = report.summary

    # The call breakdown must partition the total exactly.
    assert (
        s["calls_in_file"] + s["calls_cross_file_internal"] + s["calls_external"]
        == s["total_calls"]
    )
    # Baseline (in-file only) shows no cross-file deps; treatment recovers most.
    assert s["baseline_coverage"] == 0.0
    assert s["treatment_coverage"] > 0.5
    assert 0.0 <= s["task_prevalence"] <= 1.0
    assert 0.0 <= s["cross_file_call_share"] <= 1.0
    assert report.verdict
    assert list(tmp_path.glob("*/CodeviewCrossfileProof.md"))
