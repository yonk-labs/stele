"""Real third-party benchmark runner.

Usage: python -m benchmarks.external [--locomo-samples N] [--mhr-queries N]
       [--lme-questions N] [--output-root DIR]

Emits benchmarks/runs/<date>/External.{json,md}. Datasets that cannot be
fetched here (CRAG, AgentLongMemEval) are reported as unavailable WITH the
reason — never with fabricated numbers.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.external import harness, loaders


def _safe(fn: Any, **kw: Any) -> dict[str, Any]:
    try:
        result: dict[str, Any] = fn(**kw)
        return result
    except loaders.DatasetUnavailable as e:
        return {"benchmark": fn.__name__, "status": "UNAVAILABLE",
                "reason": str(e), "numbers": "NOT FABRICATED"}


def run_all(locomo_samples: int | None, mhr_queries: int,
            lme_questions: int, *, longbench_per_task: int = 40,
            ragbench_per_subset: int = 60,
            profile: str = "default-keyword") -> dict[str, Any]:
    spec = harness.PROFILES[profile]
    cfg = spec["config"]
    k = spec["k"]
    # locomo-best is LoCoMo-only — it stacks extract+retain on top of the
    # hybrid config and uses a deeper k. Other benchmarks are skipped (run
    # them via --profile hybrid-best in a separate invocation).
    if profile == "locomo-best":
        results = [
            _safe(harness.run_locomo, max_samples=locomo_samples,
                  k=k, config=cfg,
                  use_stele_extract=True,
                  retain_message_text=spec.get("retain_message_text", True)),
        ]
    else:
        results = [
            _safe(harness.run_locomo, max_samples=locomo_samples,
                  k=k, config=cfg),
            _safe(harness.run_multihoprag, max_queries=mhr_queries,
                  k=k, config=cfg),
            _safe(harness.run_longmemeval_s, max_questions=lme_questions,
                  k=k, config=cfg),
            _safe(harness.run_longbench, max_per_task=longbench_per_task,
                  k=k, config=cfg),
            _safe(harness.run_ragbench, max_per_subset=ragbench_per_subset,
                  k=k, config=cfg),
        ]
    for r in results:
        if isinstance(r, dict) and "benchmark" in r and "status" not in r:
            r["profile"] = profile
            r["profile_notes"] = spec.get("notes", "")
    # honest unavailable entries (loaders raise; recorded, not faked)
    for name, fn in (("CRAG", loaders.load_crag),
                     ("AgentLongMemEval", loaders.load_agentlongmemeval)):
        try:
            fn()
        except loaders.DatasetUnavailable as e:
            results.append({"benchmark": name, "status": "UNAVAILABLE",
                            "reason": str(e), "numbers": "NOT FABRICATED"})
    return {"timestamp": datetime.now(UTC).isoformat(), "results": results}


def _md(report: dict[str, Any]) -> str:
    out = ["# Real Third-Party Benchmarks (retrieval-grade)", "",
           f"Generated: {report['timestamp']}", "",
           "Metric is **evidence/answer-span retrieval recall**, deterministic,"
           " no LLM. NOT leaderboard QA accuracy (needs an answer model).", ""]
    for r in report["results"]:
        out.append(f"## {r.get('benchmark')}")
        if r.get("status") == "UNAVAILABLE":
            out += ["**UNAVAILABLE** — numbers NOT fabricated.",
                    f"> {r['reason']}", ""]
            continue
        for k, v in r.items():
            if k == "benchmark":
                continue
            out.append(f"- {k}: {v}")
        out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--locomo-samples", type=int, default=None)
    ap.add_argument("--mhr-queries", type=int, default=200)
    ap.add_argument("--lme-questions", type=int, default=30)
    ap.add_argument("--longbench-per-task", type=int, default=40)
    ap.add_argument("--ragbench-per-subset", type=int, default=60)
    ap.add_argument("--profile", default="default-keyword",
                    choices=sorted(harness.PROFILES.keys()),
                    help="Named per-shape recipe. See harness.PROFILES.")
    ap.add_argument("--output-root", type=Path, default=Path("benchmarks/runs"))
    a = ap.parse_args()
    report = run_all(
        a.locomo_samples, a.mhr_queries, a.lme_questions,
        longbench_per_task=a.longbench_per_task,
        ragbench_per_subset=a.ragbench_per_subset,
        profile=a.profile,
    )
    report["profile"] = a.profile
    out_dir = a.output_root / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"-{a.profile}" if a.profile != "default-keyword" else ""
    (out_dir / f"External{suffix}.json").write_text(json.dumps(report, indent=2))
    (out_dir / f"External{suffix}.md").write_text(_md(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
