"""Runtime benchmark gate: the T-RAM-011 invariants must hold every run."""

from __future__ import annotations

from benchmarks.runtime import run_benchmark


def test_benchmark_invariants_hold() -> None:
    r = run_benchmark(n=50)
    assert r["corpus_docs"] == 50
    assert r["pii_leakage_count"] == 0          # hard invariant
    assert r["context_pack_deterministic"] is True
    assert r["resume_success"] is True
    assert r["input_token_reduction_pct"] > 0   # packing actually compresses
    assert r["answer_bearing_ref_recall_pct"] >= 0


def test_benchmark_is_deterministic() -> None:
    a = run_benchmark(n=30)
    b = run_benchmark(n=30)
    # numeric metrics stable across runs (fixed corpus, memory backend)
    for k in (
        "raw_transcript_tokens", "avg_packed_context_tokens",
        "input_token_reduction_pct", "answer_bearing_ref_recall_pct",
        "false_recall_count", "pii_leakage_count",
    ):
        assert a[k] == b[k], f"{k} not deterministic: {a[k]} != {b[k]}"
