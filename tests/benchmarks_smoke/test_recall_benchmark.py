from benchmarks.recall import run_recall_benchmark


def test_recall_benchmark_meets_fixture_accuracy_target() -> None:
    report = run_recall_benchmark()
    summary = report["summary"]

    assert isinstance(summary, dict)
    assert summary["direct_context_answer_accuracy"] == 1.0
    assert summary["retrieval_answer_accuracy"] >= 0.9
    assert summary["meets_90pct_accuracy_target"] is True
