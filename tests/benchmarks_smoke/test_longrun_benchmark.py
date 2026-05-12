from pathlib import Path

from benchmarks.longrun import build_scenarios, run_long_benchmark


def test_longrun_has_30_plus_scenarios() -> None:
    assert len(build_scenarios(content_multiplier=1)) >= 30


def test_longrun_memory_smoke(tmp_path: Path) -> None:
    report = run_long_benchmark(
        backends=["memory"],
        repeat=1,
        content_multiplier=1,
        output_root=tmp_path,
        append_jsonl=True,
    )

    summary = report["summary"]
    assert summary["scenario_count"] >= 30
    assert summary["backend_count"] == 1
    assert summary["total_runs"] == summary["scenario_count"]
    assert summary["exact_fetch_accuracy"] == 1.0
    assert summary["total_pii_leaks"] == 0
    assert Path(report["run_dir"], "results.jsonl").exists()
