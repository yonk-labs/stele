"""Top-level consolidator for the full end-to-end showcase.

Reads every sub-report under a run's date dir and emits one defensible
``FULL-SHOWCASE-REPORT.md`` covering:

- token reduction + performance + PII leakage   (Showcase.json, all engines)
- long-term recall + supersession + as_of       (Recall.json, LongRun.json)
- LLM-judged answer accuracy vs raw-context      (answer-workflow-*/AnswerWorkflow.json)

Every number is read from a committed JSON artifact, so the report is
reproducible from the raw run. Missing sub-reports are skipped with a note
rather than failing — a partial run still produces a partial report.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return None


def _provenance(reports: list[dict[str, Any] | None]) -> dict[str, str]:
    for r in reports:
        if r and isinstance(r.get("versions"), dict):
            return {str(k): str(v) for k, v in r["versions"].items()}
    return {}


def _showcase_section(date_dir: Path) -> list[str]:
    data = _load(date_dir / "Showcase.json")
    if not data:
        return ["## Token reduction · performance · PII", "", "_Showcase.json missing._", ""]
    s = data.get("summary", {})
    lines = [
        "## Token reduction · performance · PII",
        "",
        f"Engines tested: {', '.join(data.get('backends_tested', [])) or 'n/a'}  ·  "
        f"workload×engine runs: {s.get('total_workloads', '?')}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Mean prompt-payload reduction | **{s.get('mean_savings_pct', '?')}%** |",
        f"| Median / min / max reduction | {s.get('median_savings_pct','?')}% / "
        f"{s.get('min_savings_pct','?')}% / {s.get('max_savings_pct','?')}% |",
        f"| Mean intercept latency | {s.get('mean_intercept_ms','?')} ms |",
        f"| Mean fetch latency | {s.get('mean_fetch_ms','?')} ms |",
        f"| Mean search latency | {s.get('mean_search_ms','?')} ms |",
        f"| Concurrency throughput | {data.get('concurrency_rows_per_sec','?')} rows/s |",
        f"| **Total PII leakage** | **{s.get('total_pii_leakage_count','?')}** (must be 0) |",
        "",
    ]
    return lines


def _recall_section(date_dir: Path) -> list[str]:
    lines = ["## Long-term recall", ""]
    recall = _load(date_dir / "Recall.json")
    if recall:
        s = recall.get("summary", {})
        lines += [
            "**Recall benchmark** (answer-bearing span retrieval):",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Retrieval answer accuracy | {s.get('retrieval_answer_accuracy','?')} |",
            f"| Recall@1 | {s.get('recall_at_1','?')} |",
            f"| MRR | {s.get('mrr','?')} |",
            f"| Cases | {s.get('case_count','?')} |",
            "",
        ]
    else:
        lines += ["_Recall.json missing._", ""]

    longrun = None
    for d in sorted(date_dir.glob("longrun-*")):
        longrun = _load(d / "LongRun.json") or longrun
    if longrun:
        s = longrun.get("summary", {})
        lines += [
            "**Long-run matrix** (supersession / as_of / temporal / PII, all engines):",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Total runs | {s.get('total_runs','?')} |",
            f"| Retrieval answer accuracy | {s.get('retrieval_answer_accuracy','?')} |",
            f"| Recall@1 | {s.get('recall_at_1','?')} |",
            f"| Exact-fetch accuracy | {s.get('exact_fetch_accuracy','?')} |",
            f"| Raw-fetch block rate | {s.get('raw_fetch_block_rate','?')} |",
            f"| Mean payload reduction | {s.get('mean_payload_reduction_pct','?')}% |",
            f"| **Total PII leaks** | **{s.get('total_pii_leaks','?')}** (must be 0) |",
            "",
        ]
    else:
        lines += ["_LongRun.json missing._", ""]
    return lines


def _accuracy_section(date_dir: Path) -> list[str]:
    # Group answer-workflow runs by scenarios_source from each report's config.
    by_source: dict[str, dict[str, Any]] = {}
    judge_cfg: dict[str, Any] = {}
    for run in sorted(date_dir.glob("answer-workflow-*")):
        data = _load(run / "AnswerWorkflow.json")
        if not data:
            continue
        cfg = data.get("config", {})
        if cfg.get("judge_mode") != "openai":
            continue
        source = cfg.get("scenarios_source", "unknown")
        by_source[source] = data.get("by_strategy", {})
        judge_cfg = cfg or judge_cfg

    lines = ["## LLM-judged answer accuracy vs raw context", ""]
    if not by_source:
        return lines + ["_No openai-judged answer-workflow runs found._", ""]

    a_model = judge_cfg.get("answer_model", "?")
    a_url = judge_cfg.get("answer_base_url", "?")
    j_model = judge_cfg.get("judge_model", "?")
    j_url = judge_cfg.get("judge_base_url", "?")
    lines += [
        f"Answerer: `{a_model}` @ `{a_url}`  ",
        f"Judge: `{j_model}` @ `{j_url}`  ",
        "",
        "Accuracy and mean tokens per strategy. `digest` = lede summary + facts + "
        "top-5 chunks; `raw_fetch` = full-context baseline.",
        "",
    ]
    order = ["search_first", "summary_only", "summary_then_search",
             "adaptive", "iterative", "digest", "raw_fetch"]
    for source in ["synthetic", "longbench", "ragbench", "longmemeval", "locomo"]:
        strat = by_source.get(source)
        if not strat:
            continue
        lines += [f"### {source}", "", "| Strategy | Accuracy | Mean tokens |",
                  "| --- | ---: | ---: |"]
        for name in order:
            row = strat.get(name)
            if not row:
                continue
            acc = row.get("accuracy", "?")
            tok = row.get("mean_total_tokens", "?")
            mark = " ⭐" if name == "digest" else ""
            lines.append(f"| {name}{mark} | {acc} | {tok} |")
        lines.append("")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--date-dir",
        type=Path,
        default=Path(f"benchmarks/runs/{datetime.now(UTC).strftime('%Y-%m-%d')}"),
    )
    args = ap.parse_args()
    date_dir: Path = args.date_dir

    prov = _provenance([
        _load(date_dir / "Showcase.json"),
        _load(date_dir / "Recall.json"),
    ])
    lines = [
        "# Stele — Full End-to-End Showcase",
        "",
        f"Generated: `{datetime.now(UTC).isoformat()}`  ",
        f"Run dir: `{date_dir}`  ",
        "",
        "**Package versions**: "
        + ("  ·  ".join(f"{k} `{v}`" for k, v in prov.items()) or "n/a"),
        "",
        "Every number below is read from a JSON artifact in this run dir; re-run "
        "`scripts/run-full-showcase.sh` to reproduce. Deterministic lanes (showcase, "
        "recall, long-run) are byte-stable; the LLM-judged lane uses an independent "
        "judge model (no self-grading).",
        "",
    ]
    lines += _showcase_section(date_dir)
    lines += _recall_section(date_dir)
    lines += _accuracy_section(date_dir)

    out = date_dir / "FULL-SHOWCASE-REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
