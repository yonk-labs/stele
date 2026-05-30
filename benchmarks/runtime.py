"""Runtime-memory benchmark (T-RAM-011 / Spec-9).

Runs the runtime loop over the deterministic 100-doc corpus and emits
JSON + Markdown reports with: input-token reduction vs raw transcript,
added latency, answer-bearing ref recall, false-recall, PII leakage count,
resume success, and context-pack determinism. Deterministic — same numbers
every run (memory backend, fixed corpus). README/docs claims must cite the
generated report (the benchmark-evidence rule).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks._versions import version_info, versions_md_line
from benchmarks.corpus import sample_corpus
from stele.core.artifact import estimate_tokens
from stele.core.stash import Stele
from stele.runtime.demo import SteleAgentSession
from stele.workgraph.store import InProcessWorkGraphStore


def run_benchmark(n: int = 100) -> dict[str, Any]:
    corpus = sample_corpus(n)
    stele = Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"enabled": True}}
    )
    sess = SteleAgentSession(
        stele=stele, wg_store=InProcessWorkGraphStore(),
        namespace="bench", session_id="b1",
    )
    sess.start("runtime benchmark")

    raw_tokens = 0
    t0 = time.perf_counter()
    for d in corpus:
        raw_tokens += estimate_tokens(d.text)
        sess.observe_tool("Tool", d.text)
    capture_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    packed_tokens = 0
    answer_hits = 0
    false_recall = 0
    pii_leaks = 0
    pii_docs = [d for d in corpus if d.pii]
    for d in corpus:
        pack = sess.recall_and_pack(query=d.fact, budget_tokens=1500)
        packed_tokens += pack.token_estimate
        if any(tok in pack.dynamic_context for tok in d.fact.split() if len(tok) > 4):
            answer_hits += 1
        else:
            false_recall += 1
        for p in pii_docs:
            if p.pii and p.pii in pack.dynamic_context:
                pii_leaks += 1
    pack_ms = (time.perf_counter() - t1) * 1000

    # determinism: identical packed context across two runs for one query
    q = corpus[0].fact
    determinism = (
        sess.recall_and_pack(query=q).dynamic_context
        == sess.recall_and_pack(query=q).dynamic_context
    )
    resume = sess.resume()
    resume_ok = bool(resume) and "stele://" in resume
    avg_packed = packed_tokens / len(corpus)
    reduction = 1.0 - (avg_packed / raw_tokens) if raw_tokens else 0.0
    sess.end()
    stele.close()

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "versions": version_info(),
        "corpus_docs": len(corpus),
        "raw_transcript_tokens": raw_tokens,
        "avg_packed_context_tokens": round(avg_packed, 1),
        "input_token_reduction_pct": round(reduction * 100, 1),
        "capture_latency_ms": round(capture_ms, 1),
        "pack_latency_ms": round(pack_ms, 1),
        "answer_bearing_ref_recall_pct": round(100 * answer_hits / len(corpus), 1),
        "false_recall_count": false_recall,
        "pii_leakage_count": pii_leaks,
        "resume_success": resume_ok,
        "context_pack_deterministic": determinism,
    }


def _render_md(r: dict[str, Any]) -> str:
    lines = ["# Runtime-Memory Benchmark (T-RAM-011)", "",
             f"Generated: {r['timestamp']}  ·  corpus: {r['corpus_docs']} docs",
             f"Package versions: {versions_md_line()}",
             "", "| Metric | Value |", "| --- | --- |"]
    for k, v in r.items():
        if k in ("timestamp", "corpus_docs", "versions"):
            continue
        lines.append(f"| {k} | {v} |")
    lines += ["", "Fixture: `benchmarks.corpus.sample_corpus` (deterministic).",
              "PII leakage MUST be 0; context pack MUST be deterministic."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--output-root", type=Path, default=Path("benchmarks/runs"))
    args = parser.parse_args()
    report = run_benchmark(args.n)
    out_dir = args.output_root / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Runtime.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (out_dir / "Runtime.md").write_text(_render_md(report), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
