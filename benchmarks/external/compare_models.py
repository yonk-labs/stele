"""Stitch Qwen / gpt-5-mini / gpt-5.5 judge-lane reports into one table.

Reads per-model Report.json files written by `benchmarks.external.judge_lane`
and emits a side-by-side comparison: accuracy + token-cost + latency per
benchmark, per model. Output: Comparison.md + Comparison.json next to the
input reports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_RUNS = Path("benchmarks/runs/2026-05-20")


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def _per_bench_map(report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not report:
        return {}
    return {row["benchmark"]: row for row in report["per_benchmark"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    ap.add_argument("--rejudged-by",
                    help="If set, read Report-rejudged-<this>.json instead of "
                    "Report.json. e.g. 'gpt-4o-mini'.")
    a = ap.parse_args()
    report_name = (f"Report-rejudged-{a.rejudged_by}.json"
                   if a.rejudged_by else "Report.json")

    # Per-model (qwen | gpt-5-mini | gpt-5.5) × per-profile (hybrid | locomo)
    sources = {
        "qwen": {
            "hybrid-best": a.runs_dir / "judge-lane-hybrid-best" / report_name,
            "locomo-best": a.runs_dir / "judge-lane-locomo-best" / report_name,
        },
        "gpt-5-mini": {
            "hybrid-best": a.runs_dir / "judge-lane-hybrid-best-gpt-5-mini" / report_name,
            "locomo-best": a.runs_dir / "judge-lane-locomo-best-gpt-5-mini" / report_name,
        },
        "gpt-5.5": {
            "hybrid-best": a.runs_dir / "judge-lane-hybrid-best-gpt-5.5" / report_name,
            "locomo-best": a.runs_dir / "judge-lane-locomo-best-gpt-5.5" / report_name,
        },
    }

    loaded: dict[str, dict[str, dict[str, Any]]] = {}
    for model, profs in sources.items():
        loaded[model] = {}
        for prof, p in profs.items():
            loaded[model][prof] = _per_bench_map(_load(p))

    # Union of benchmarks across all reports
    benchmarks: list[str] = []
    seen: set[str] = set()
    # canonical order: locomo first, then hybrid-best ones
    for prof in ("locomo-best", "hybrid-best"):
        for model in ("qwen", "gpt-5-mini", "gpt-5.5"):
            for b in loaded.get(model, {}).get(prof, {}):
                if b not in seen:
                    seen.add(b)
                    benchmarks.append(b)

    def cell(b: str, model: str) -> dict[str, Any]:
        for prof in ("hybrid-best", "locomo-best"):
            row = loaded.get(model, {}).get(prof, {}).get(b)
            if row and "accuracy_pct" in row:
                out: dict[str, Any] = row
                return out
        return {}

    rows: list[dict[str, Any]] = []
    for b in benchmarks:
        rows.append({
            "benchmark": b,
            "qwen": cell(b, "qwen"),
            "gpt-5-mini": cell(b, "gpt-5-mini"),
            "gpt-5.5": cell(b, "gpt-5.5"),
        })

    out_dir = a.runs_dir
    suffix = f"-rejudged-{a.rejudged_by}" if a.rejudged_by else ""
    (out_dir / f"Comparison{suffix}.json").write_text(json.dumps(rows, indent=2))

    title_suffix = (f" (rejudged by {a.rejudged_by})"
                    if a.rejudged_by else " (self-judged per row)")
    md = [f"# LLM-judged QA Accuracy — Qwen3-Coder vs gpt-5-mini vs gpt-5.5{title_suffix}",
          "",
          "Same Stele context per query; only the answer model differs."
          + (f" Judge is fixed: **{a.rejudged_by}** across all rows."
             if a.rejudged_by
             else " WARNING: each row's judge model equals its answer model — "
             "self-judge strictness drift inflates penalties for terser models."),
          "",
          ("| Benchmark | n | Qwen3-Coder | gpt-5-mini | gpt-5.5 | "
           "qwen→mini Δ | mini→5.5 Δ |"),
          "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        q = r["qwen"]
        m = r["gpt-5-mini"]
        g = r["gpt-5.5"]
        n = q.get("n") or m.get("n") or g.get("n") or "—"
        qa = q.get("accuracy_pct")
        ma = m.get("accuracy_pct")
        ga = g.get("accuracy_pct")

        def fmt(v: Any) -> str:
            return f"{v:.1f}%" if isinstance(v, (int, float)) else "—"

        def delta(a: Any, b: Any) -> str:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                d = b - a
                sign = "+" if d >= 0 else ""
                return f"{sign}{d:.1f}"
            return "—"
        md.append(
            f"| {r['benchmark']} | {n} | {fmt(qa)} | {fmt(ma)} | {fmt(ga)} | "
            f"{delta(qa, ma)} | {delta(ma, ga)} |"
        )

    md += ["", "## Token cost per query (mean prompt+completion estimate)", "",
           "| Benchmark | Qwen3-Coder | gpt-5-mini | gpt-5.5 |",
           "|---|---:|---:|---:|"]
    for r in rows:
        def tok(d: dict[str, Any]) -> str:
            t = d.get("total_tokens_mean")
            return f"{int(t):,}" if t else "—"
        md.append(
            f"| {r['benchmark']} | {tok(r['qwen'])} | "
            f"{tok(r['gpt-5-mini'])} | {tok(r['gpt-5.5'])} |"
        )

    md += ["", "## Answer-stage latency p50 (ms)", "",
           "| Benchmark | Qwen3-Coder | gpt-5-mini | gpt-5.5 |",
           "|---|---:|---:|---:|"]
    for r in rows:
        def lat(d: dict[str, Any]) -> str:
            v = d.get("answer_ms_p50")
            return f"{int(v):,}" if v else "—"
        md.append(
            f"| {r['benchmark']} | {lat(r['qwen'])} | "
            f"{lat(r['gpt-5-mini'])} | {lat(r['gpt-5.5'])} |"
        )

    md.append("")
    (out_dir / f"Comparison{suffix}.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
