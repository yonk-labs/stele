"""Smoke: the evolving-fact proof shows stele's temporal-correctness divergence.

Guards the claim: stele (supersession + as_of) is correct on all temporal
questions; naive store-once memory returns the STALE value; both baselines lose.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.evolving_fact_proof import run


def test_evolving_fact_divergence(tmp_path: Path) -> None:
    report = run("memory", output_root=tmp_path, write=True)

    assert report.summary["stele_score"] == report.summary["questions"]
    assert report.summary["naive_score"] < report.summary["stele_score"]
    assert report.summary["no_memory_score"] < report.summary["stele_score"]

    # The stale trap specifically: naive memory must be wrong on "current".
    naive = next(a for a in report.arms if a["arm"].startswith("naive"))
    assert naive["correct"]["current"] is False

    assert list(tmp_path.glob("*/EvolvingFactProof.md"))
