from benchmarks.mvp_smoke import run


def test_mvp_smoke_report(tmp_path) -> None:  # type: ignore[no-untyped-def]
    report = run(tmp_path)

    assert report["pass"] is True
    assert report["pii_leakage_count"] == 0
    assert isinstance(report["token_savings_pct"], float)
    assert report["token_savings_pct"] > 0.5
    assert (tmp_path / "report.json").exists()
