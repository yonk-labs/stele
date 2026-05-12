import os

from benchmarks.showcase import WORKLOADS, run_showcase, write_showcase_report


def test_showcase_replication_memory_backend(tmp_path) -> None:  # type: ignore[no-untyped-def]
    report = run_showcase(output_root=tmp_path)

    expected_backends = ["MemoryBackend", "SQLiteBackend"]
    if os.environ.get("STELE_PG_DSN"):
        expected_backends.append("PostgresBackend")
    if os.environ.get("STELE_MARIADB_DSN"):
        expected_backends.append("MariaDBBackend")
    if os.environ.get("STELE_CLICKHOUSE_DSN"):
        expected_backends.append("ClickHouseBackend")
    assert report.backends_tested == expected_backends
    assert len(report.results) == len(WORKLOADS) * len(expected_backends)
    assert report.summary["total_workloads"] == len(WORKLOADS) * len(expected_backends)
    assert report.summary["mean_savings_pct"] > 90
    assert report.summary["min_savings_pct"] > 75
    assert report.summary["total_pii_leakage_count"] == 0
    assert report.concurrency_rows_per_sec > 10
    for result in report.results:
        assert result.replacement_size_bytes < result.input_size_bytes
        assert result.fetch_latency_ms >= 0
        assert result.search_latency_ms >= 0
        assert result.search_hits >= 0


def test_showcase_report_files_match_original_shape(tmp_path) -> None:  # type: ignore[no-untyped-def]
    report = run_showcase(output_root=tmp_path, write_report=False)
    md_path, json_path = write_showcase_report(report, tmp_path)

    markdown = md_path.read_text(encoding="utf-8")
    payload = json_path.read_text(encoding="utf-8")

    assert "Showcase Benchmark" in markdown
    assert "Mean prompt-payload reduction" in markdown
    assert "Industry Workload Results" in markdown
    assert '"summary"' in payload
    assert '"results"' in payload
