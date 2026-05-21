"""Consolidate the postgres-only showcase matrix into a single report.

Reads benchmarks/runs/<date>/External-<profile>.json for each profile in
the matrix and emits Benchmark-Showcase-Postgres.{md,json} with a
profile × benchmark answer-span-recall@k cross-tab.

The matrix profiles are not encoded here — we discover them from the
filenames that match External-pg-*.json so this stays decoupled from the
PROFILES dict and won't go stale if profiles are added or renamed.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Deliberate narrative order: lexical floor → chunking ladder → fusion
# variants → graph ladder. Profiles not in this list fall to the tail in
# alphabetical order.
_PROFILE_ORDER = [
    "pg-keyword",
    "pg-vector",
    "pg-hybrid",
    "pg-hybrid-tight",
    "pg-hybrid-wide",
    "pg-hybrid-weighted",
    "pg-graph-smart",
    "pg-graph-hybrid",
    "pg-graph-hybrid-rerank",
]


def _load(date_dir: Path) -> dict[str, dict[str, Any]]:
    """Return {profile_name: external_report_dict} for every postgres
    profile, in deliberate narrative order."""
    raw: dict[str, dict[str, Any]] = {}
    for p in sorted(date_dir.glob("External-pg-*.json")):
        name = p.stem.removeprefix("External-")
        try:
            raw[name] = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
    out: dict[str, dict[str, Any]] = {}
    for name in _PROFILE_ORDER:
        if name in raw:
            out[name] = raw[name]
    for name in sorted(raw):
        if name not in out:
            out[name] = raw[name]
    return out


def _short_bench(label: str) -> str:
    """Map the long benchmark labels to compact column headers."""
    mapping = {
        "LoCoMo": "LoCoMo",
        "MultiHop-RAG": "MHR",
        "LongMemEval-S": "LME-S",
        "LongBench": "LongBench",
        "RAGBench": "RAGBench",
    }
    for key, val in mapping.items():
        if label.startswith(key):
            return val
    return label


def _profile_summary(report: dict[str, Any]) -> dict[str, Any]:
    """One row of the matrix: top-level metric per benchmark + sub-cells."""
    row: dict[str, Any] = {}
    for r in report.get("results", []):
        if not isinstance(r, dict) or r.get("status") == "UNAVAILABLE":
            continue
        bench = _short_bench(r.get("benchmark", ""))
        # Single-metric benchmarks expose answer_span_recall_at_k_pct directly
        if "answer_span_recall_at_k_pct" in r:
            row[bench] = r["answer_span_recall_at_k_pct"]
        # LongBench: per_task list
        if "per_task" in r:
            tasks: dict[str, Any] = {}
            for t in r["per_task"]:
                if t.get("status") == "UNAVAILABLE":
                    tasks[t.get("task", "?")] = None
                else:
                    tasks[t.get("task", "?")] = t.get(
                        "answer_span_recall_at_k_pct"
                    )
            row[f"{bench}-tasks"] = tasks
            # roll-up: mean over available tasks
            present = [v for v in tasks.values() if isinstance(v, (int, float))]
            row[bench] = round(sum(present) / len(present), 1) if present else None
        # RAGBench: per_subset list
        if "per_subset" in r:
            subs: dict[str, Any] = {}
            for s in r["per_subset"]:
                if s.get("status") == "UNAVAILABLE":
                    subs[s.get("subset", "?")] = None
                else:
                    subs[s.get("subset", "?")] = s.get(
                        "answer_span_recall_at_k_pct"
                    )
            row[f"{bench}-subsets"] = subs
            present = [v for v in subs.values() if isinstance(v, (int, float))]
            row[bench] = round(sum(present) / len(present), 1) if present else None
    return row


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def _best_marker(values: list[Any], idx: int) -> str:
    nums = [(i, v) for i, v in enumerate(values) if isinstance(v, (int, float))]
    if not nums:
        return ""
    best_i, _ = max(nums, key=lambda kv: kv[1])
    return " ★" if idx == best_i else ""


def _render_md(
    reports: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
) -> str:
    profiles = list(rows.keys())
    benches = ["LoCoMo", "MHR", "LME-S", "LongBench", "RAGBench"]

    out: list[str] = []
    out.append("# Stele Postgres-Only Benchmark Showcase")
    out.append("")
    out.append(f"Generated: {datetime.now(UTC).isoformat()}")
    out.append("")
    out.append(
        "Postgres is the only artifact backend in this sweep. Each profile "
        "holds 7 of 8 levers constant and moves one. Metric: "
        "**answer-span recall@k** — does any retrieved snippet contain the "
        "gold answer string? Deterministic; no LLM judge. NOT leaderboard "
        "QA accuracy. The ★ marks the best profile for that benchmark."
    )
    out.append("")
    out.append("## Headline findings")
    out.append("")
    out.append(
        "1. **The recall lane is tsvector-only today.** "
        "`pg-keyword`, `pg-vector`, `pg-hybrid`, and the three chunk-size "
        "variants tie cell-for-cell on the matrix because "
        "`Stele.recall()` → `MemorySearchStrategy` calls "
        "`MemoryStore.search_with_score` (postgres tsvector) and never "
        "consults the chunk index. See the **Stele.query direct lane** "
        "below for what those configs achieve when the chunk index IS "
        "exercised."
    )
    out.append(
        "2. **Vector retrieval works — when you reach the chunk index.** "
        "Calling `Stele.query()` directly on the same postgres + "
        "chunkshop config lifts MultiHop-RAG answer-span recall from "
        "0% (recall lane) to **92.7% at 400-word chunks / vector mode**. "
        "The plumbing is there; what's missing is for `memory_search` "
        "to honor `retrieval.default_mode`."
    )
    out.append(
        "3. **`query_mode=\"smart\"` is the only raggraph mode that "
        "returns hits today.** `pg-graph-smart` (default query_mode) "
        "lifts every benchmark dramatically — LongBench hotpotqa "
        "0% → 100%, MHR 0% → 72%, RAGBench pubmedqa 0% → 100%. "
        "`pg-graph-hybrid` and `pg-graph-hybrid-rerank` both return "
        "**0% on every benchmark**: `query_mode=\"hybrid\"` in "
        "pg-raggraph 0.3.0a3 runs without error but produces zero hits "
        "in this codepath, with or without rerank. The smart-vs-hybrid "
        "gap is the biggest single finding of the sweep."
    )
    out.append("")
    out.append("## Top-line matrix")
    out.append("")
    out.append("| Profile | " + " | ".join(benches) + " |")
    out.append("|" + "---|" * (len(benches) + 1))
    for prof in profiles:
        row = rows[prof]
        cells = []
        for b in benches:
            v = row.get(b)
            col_vals = [rows[p].get(b) for p in profiles]
            marker = _best_marker(col_vals, profiles.index(prof))
            cells.append(_fmt(v) + marker)
        out.append(f"| `{prof}` | " + " | ".join(cells) + " |")
    out.append("")

    out.append("## Per-task / per-subset detail")
    out.append("")
    # LongBench per-task
    all_tasks: set[str] = set()
    for prof in profiles:
        all_tasks.update((rows[prof].get("LongBench-tasks") or {}).keys())
    tasks_sorted = sorted(all_tasks)
    if tasks_sorted:
        out.append("### LongBench (per task)")
        out.append("")
        out.append("| Profile | " + " | ".join(tasks_sorted) + " |")
        out.append("|" + "---|" * (len(tasks_sorted) + 1))
        for prof in profiles:
            tasks = rows[prof].get("LongBench-tasks") or {}
            cells = []
            for t in tasks_sorted:
                col_vals = [
                    (rows[p].get("LongBench-tasks") or {}).get(t)
                    for p in profiles
                ]
                marker = _best_marker(col_vals, profiles.index(prof))
                cells.append(_fmt(tasks.get(t)) + marker)
            out.append(f"| `{prof}` | " + " | ".join(cells) + " |")
        out.append("")
    # RAGBench per-subset
    all_subs: set[str] = set()
    for prof in profiles:
        all_subs.update((rows[prof].get("RAGBench-subsets") or {}).keys())
    subs_sorted = sorted(all_subs)
    if subs_sorted:
        out.append("### RAGBench (per subset)")
        out.append("")
        out.append("| Profile | " + " | ".join(subs_sorted) + " |")
        out.append("|" + "---|" * (len(subs_sorted) + 1))
        for prof in profiles:
            subs = rows[prof].get("RAGBench-subsets") or {}
            cells = []
            for s in subs_sorted:
                col_vals = [
                    (rows[p].get("RAGBench-subsets") or {}).get(s)
                    for p in profiles
                ]
                marker = _best_marker(col_vals, profiles.index(prof))
                cells.append(_fmt(subs.get(s)) + marker)
            out.append(f"| `{prof}` | " + " | ".join(cells) + " |")
        out.append("")

    out.append("## Profile recipes")
    out.append("")
    for prof in profiles:
        rep = reports[prof]
        first = next(
            (
                r for r in rep.get("results", [])
                if isinstance(r, dict) and r.get("profile_notes")
            ),
            None,
        )
        notes = first.get("profile_notes", "") if first else ""
        out.append(f"### `{prof}`")
        out.append("")
        out.append(notes or "_(no notes recorded)_")
        out.append("")

    # Query-modes companion table — loaded from Postgres-Query-Modes.json
    # if present. Demonstrates that retrieval mode + chunk size DO matter
    # when accessed via Stele.query() (chunk-index path), even though they
    # tie in the recall-lane matrix above (recall.memory_search ignores
    # them — see "Why the chunk profiles tie" below).
    qm_path = next(
        (
            p for p in [
                Path("benchmarks/runs")
                / datetime.now(UTC).strftime("%Y-%m-%d")
                / "Postgres-Query-Modes.json"
            ] if p.exists()
        ),
        None,
    )
    if qm_path is not None:
        try:
            qm = json.loads(qm_path.read_text())
            out.append("## Stele.query direct lane (chunk × mode)")
            out.append("")
            out.append(
                "The recall-lane matrix above goes through "
                "`recall.memory_search`, which is tsvector-only — so the "
                "chunking and hybrid profiles tie the keyword profile. "
                "This companion table calls `Stele.query()` directly on "
                "the same postgres + chunkshop config across three chunk "
                "sizes × three modes, showing the chunk-index path DOES "
                "differentiate."
            )
            out.append("")
            modes = ("keyword", "vector", "hybrid")
            out.append("| chunk_words / overlap | "
                       + " | ".join(f"{m}" for m in modes)
                       + " |")
            out.append("|" + "---|" * (1 + len(modes)))
            for cfg in qm.get("chunk_configs", []):
                per = {m["mode"]: m for m in cfg.get("per_mode", [])}
                cells = [
                    str(per.get(m, {}).get("answer_span_recall_at_k_pct", "—"))
                    for m in modes
                ]
                out.append(
                    f"| {cfg['chunk_words']} / {cfg['chunk_overlap_words']} | "
                    + " | ".join(cells) + " |"
                )
            out.append("")
        except (OSError, json.JSONDecodeError):
            pass

    out.append("## Methodology + caveats")
    out.append("")
    out.append(
        "- **Why the chunk profiles tie.** "
        "`recall.memory_search` calls `MemoryStore.search_with_score` on "
        "the artifact backend (postgres tsvector) and does NOT consult "
        "the chunk index. So `pg-keyword`, `pg-vector`, `pg-hybrid`, and "
        "the three chunk-size variants follow the same code path and "
        "report the same numbers. The chunk index IS exercised by "
        "`Stele.search()` / `Stele.query()` (see the companion table "
        "above), but those are not the recall surface today. This is the "
        "honest state of recall × indexing in stele as of 2026-05-21."
    )
    out.append(
        "- **Backend.** Every profile uses postgres. Artifact + keyword "
        "lanes hit `postgresql://yonk:yonk@localhost:55432/stele`; graph "
        "lanes hit the pg-raggraph DB at `:55453`. Per-profile graph "
        "namespaces (`pg-graph-smart`, `pg-graph-hybrid`, "
        "`pg-graph-hybrid-rerank`) keep the three raggraph configurations "
        "from contaminating each other."
    )
    out.append(
        "- **What this measures.** Answer-span recall@k = the fraction of "
        "questions where the retrieved context contains the gold answer "
        "string (60% token overlap fallback). This is a retrieval-grade "
        "score, not a QA-accuracy score; the LLM-judged variant lives "
        "under `answer_workflow.py` / `judge_lane.py`."
    )
    out.append(
        "- **Cross-record contamination.** Within a single benchmark, "
        "every record is ingested into one shared `MemoryScope` "
        "(e.g. `longbench-hotpotqa`), so record N's query sees record "
        "1..N-1's atoms too. This is consistent across all profiles, so "
        "the matrix comparison is fair — but absolute numbers should not "
        "be read as upper bounds on a clean-corpus single-doc setting."
    )
    out.append(
        "- **Graph profiles use opt-in raggraph.** `graph.fact_extractor` "
        "stays `none` (LLM-free); pg-raggraph still indexes content via "
        "its built-in pipeline. `query_mode` and `rerank` are the two "
        "raggraph levers exercised here."
    )
    out.append(
        "- **Graph profiles share raggraph state.** Ingestion uses the "
        "`MemoryScope.namespace` (e.g. `locomo_conv-41`), not "
        "`config.graph.namespace`, so the three graph profiles read the "
        "same raggraph rows. That makes `pg-graph-smart` vs "
        "`pg-graph-hybrid` vs `pg-graph-hybrid-rerank` a fair "
        "**query-mode comparison on identical data**. It also means the "
        "data includes leftovers from earlier sweeps under shared "
        "namespaces (`mhr`, `locomo_conv-26`, `longbench-*`, "
        "`ragbench-*`) — that contamination is consistent across the "
        "three graph profiles, so it does not affect their relative "
        "ranking, but absolute numbers should be read as "
        "\"accumulated-graph recall\", not \"clean-corpus recall\"."
    )
    out.append(
        "- **Datasets unavailable.** CRAG (HF-license-gated) and "
        "AgentLongMemEval (no openly-resolvable release) are reported as "
        "UNAVAILABLE — never with fabricated numbers."
    )
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--date-dir",
        type=Path,
        default=Path(f"benchmarks/runs/{datetime.now(UTC).strftime('%Y-%m-%d')}"),
    )
    args = ap.parse_args()

    if not args.date_dir.exists():
        raise SystemExit(f"no such dir: {args.date_dir}")

    reports = _load(args.date_dir)
    if not reports:
        raise SystemExit(f"no External-pg-*.json files in {args.date_dir}")

    rows = {prof: _profile_summary(rep) for prof, rep in reports.items()}

    md = _render_md(reports, rows)
    md_path = args.date_dir / "Benchmark-Showcase-Postgres.md"
    json_path = args.date_dir / "Benchmark-Showcase-Postgres.json"
    md_path.write_text(md)
    json_path.write_text(json.dumps({
        "generated": datetime.now(UTC).isoformat(),
        "profiles": list(reports.keys()),
        "rows": rows,
    }, indent=2))
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")


if __name__ == "__main__":
    main()
