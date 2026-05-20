"""Replay just the JUDGE step across stored judge-lane Report.json files.

Each row in a Report.json already carries (question, expected, answer,
context). The original judge verdict was produced by the SAME model that
wrote the answer — which conflates "is the answer right" with
"is this judge model strict about its own style."

This pass re-judges every stored row with a single FIXED neutral judge
(default: gpt-4o-mini). The Stele recall step is NOT re-run. Output:
sibling files Report-rejudged-<judge>.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = int(round((p / 100) * (len(s) - 1)))
    return s[k]


def _rejudge_file(report_path: Path, answerer: OpenAICompatAnswerer,
                  judge_label: str) -> Path:
    report = json.loads(report_path.read_text())
    rows = report["rows"]
    print(f"  rows: {len(rows)} ({sum(1 for r in rows if 'answer' in r)} answered)")
    new_rows: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        if "answer" not in r:
            new_rows.append(r)
            continue
        ctx = r.get("context", "")
        t0 = time.perf_counter()
        try:
            v = answerer.judge(
                question=r["question"], expected_answer=r["expected"],
                answer=r["answer"], context=ctx,
            )
            judge_ms = (time.perf_counter() - t0) * 1000
            new_rows.append({
                **r,
                "judge_ms": round(judge_ms, 1),
                "correct": bool(v.correct),
                "sufficient": bool(v.sufficient),
                "confidence": float(v.confidence),
                "rationale": str(v.rationale)[:500],
                "judged_by": judge_label,
            })
        except Exception as e:  # noqa: BLE001
            new_rows.append({**r, "rejudge_error": str(e)[:240],
                             "judged_by": judge_label})
        if (i + 1) % 10 == 0:
            print(f"    rejudged {i+1}/{len(rows)}")

    # Re-summarize per benchmark
    from collections import defaultdict
    by_b: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in new_rows:
        by_b[r["benchmark"]].append(r)
    per_bench: list[dict[str, Any]] = []
    for bench, rs in sorted(by_b.items()):
        scored = [r for r in rs if "correct" in r]
        if not scored:
            per_bench.append({"benchmark": bench, "n": 0})
            continue
        per_bench.append({
            "benchmark": bench,
            "n": len(scored),
            "accuracy_pct": round(
                100 * sum(1 for r in scored if r["correct"]) / len(scored), 1
            ),
            "recall_ms_p50": round(median(r["recall_ms"] for r in scored), 1),
            "recall_ms_p95": round(
                _percentile([r["recall_ms"] for r in scored], 95), 1
            ),
            "answer_ms_p50": round(median(r["answer_ms"] for r in scored), 1),
            "answer_ms_p95": round(
                _percentile([r["answer_ms"] for r in scored], 95), 1
            ),
            "judge_ms_p50": round(median(r["judge_ms"] for r in scored), 1),
            "total_tokens_mean": round(mean(r["total_tokens"] for r in scored), 0),
            "total_tokens_p95": round(
                _percentile([r["total_tokens"] for r in scored], 95), 0
            ),
            "recall_hits_mean": round(
                mean(r["recall_hits"] for r in scored), 1
            ),
        })

    new_report = {
        **{k: v for k, v in report.items() if k not in ("per_benchmark", "rows")},
        "rejudged_at": datetime.now(UTC).isoformat(),
        "judge": judge_label,
        "per_benchmark": per_bench,
        "rows": new_rows,
    }
    out_path = report_path.parent / f"Report-rejudged-{judge_label}.json"
    out_path.write_text(json.dumps(new_report, indent=2))
    print(f"  → {out_path}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", type=Path,
                    default=Path("benchmarks/runs/2026-05-20"))
    ap.add_argument("--judge-model", default="gpt-4o-mini")
    ap.add_argument("--openai-base-url",
                    default="https://api.openai.com/v1")
    ap.add_argument("--openai-api-key",
                    default=os.environ.get("OPENAI_API_KEY", ""))
    a = ap.parse_args()
    if not a.openai_api_key:
        raise SystemExit("OPENAI_API_KEY required (env or --openai-api-key)")

    answerer = OpenAICompatAnswerer(
        answer_model=a.judge_model, judge_model=a.judge_model,
        base_url=a.openai_base_url, api_key=a.openai_api_key,
    )

    judge_label = a.judge_model.split("/")[-1].lower()
    sources = sorted(p for p in a.runs_dir.glob("judge-lane-*")
                     if p.is_dir() and not p.name.endswith("-smoke"))
    print(f"Found {len(sources)} judge-lane directories")
    for src in sources:
        rep = src / "Report.json"
        if not rep.exists():
            print(f"  skip (no Report.json): {src.name}")
            continue
        print(f"REJUDGE {src.name}  (with {a.judge_model})")
        _rejudge_file(rep, answerer, judge_label)


if __name__ == "__main__":
    main()
