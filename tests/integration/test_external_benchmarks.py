"""External-benchmark harness gate.

Runs each real-dataset runner on a TINY slice and asserts the harness
produces well-formed, deterministic, PII-safe output. Skipped (not failed)
when the gitignored 280MB dataset cache is absent — so it never breaks a
clean checkout, but is a real gate where the data exists.
"""

from __future__ import annotations

import pytest

from benchmarks.external import harness, loaders

_CACHE = loaders.CACHE


@pytest.mark.skipif(
    not (_CACHE / "locomo10.json").exists(),
    reason="LoCoMo dataset not cached (benchmarks/.cache/locomo10.json)",
)
def test_locomo_harness_runs_and_is_pii_safe() -> None:
    r = harness.run_locomo(max_samples=1, k=10)
    assert r["samples"] == 1
    assert r["recall_depth_k"] == 10
    assert r["pii_leakage_count"] == 0
    assert 0.0 <= r["answer_span_recall_at_k_pct"] <= 100.0


@pytest.mark.skipif(
    not (_CACHE / "multihoprag_queries.json").exists(),
    reason="MultiHop-RAG dataset not cached",
)
def test_multihoprag_harness_runs() -> None:
    r = harness.run_multihoprag(max_queries=5, k=10)
    assert r["corpus_docs"] > 0
    assert r["pii_leakage_count"] == 0
    assert r["metric_kind"].startswith("retrieval-grade")


@pytest.mark.skipif(
    not (_CACHE / "longmemeval_s.json").exists(),
    reason="LongMemEval-S dataset not cached (280MB)",
)
def test_longmemeval_s_harness_runs() -> None:
    r = harness.run_longmemeval_s(max_questions=1, k=10)
    assert r["questions_run"] == 1
    assert r["pii_leakage_count"] == 0


def test_unavailable_datasets_are_honest_not_fabricated() -> None:
    for fn in (loaders.load_crag, loaders.load_agentlongmemeval):
        with pytest.raises(loaders.DatasetUnavailable):
            fn()
