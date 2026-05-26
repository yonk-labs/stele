"""Deterministic recall and answer-preservation benchmark.

This benchmark separates prompt-payload reduction from task quality. It uses an
oracle direct-context baseline and checks whether retrieved chunks preserve the
answer-bearing span needed to answer each query.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from benchmarks._versions import version_info, versions_md_line
from stele import Stele


@dataclass(frozen=True)
class RecallCase:
    name: str
    query: str
    expected_answer: str
    content: str


@dataclass(frozen=True)
class RecallResult:
    name: str
    recall_at_1: float
    answer_accuracy: float
    reciprocal_rank: float
    top_hit_chars: int
    direct_context_answer_accuracy: float


def _distractor(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}_{idx}" for idx in range(count)) + " "


CASES = [
    RecallCase(
        name="ops_root_cause",
        query="database index root cause",
        expected_answer="missing composite index on tenant_id and created_at",
        content=(
            _distractor("ops", 70)
            + " Incident review: the database index root cause was a "
            "missing composite index on tenant_id and created_at. "
            + _distractor("latency", 70)
        ),
    ),
    RecallCase(
        name="customer_commitment",
        query="enterprise customer renewal commitment",
        expected_answer="deliver SSO audit logs by June 30",
        content=(
            _distractor("account", 60)
            + " Enterprise customer renewal commitment: deliver SSO audit logs by June 30. "
            + _distractor("crm", 60)
        ),
    ),
    RecallCase(
        name="pii_policy",
        query="pii policy raw fetch approval",
        expected_answer="raw fetch requires explicit approval",
        content=(
            _distractor("security", 60)
            + " PII policy decision: raw fetch requires explicit approval and scrubbed output "
            "is the default. "
            + _distractor("privacy", 60)
        ),
    ),
    RecallCase(
        name="backend_choice",
        query="postgres backend critical capability",
        expected_answer="Postgres must support exact fetch plus full text retrieval",
        content=(
            _distractor("storage", 60)
            + " Backend choice: Postgres must support exact fetch plus full text retrieval "
            "before graph retrieval is enabled. "
            + _distractor("database", 60)
        ),
    ),
    RecallCase(
        name="clickhouse_semantics",
        query="clickhouse delete semantics",
        expected_answer="ClickHouse delete is mutation based and can be eventually consistent",
        content=(
            _distractor("analytics", 60)
            + " ClickHouse delete semantics: ClickHouse delete is mutation based and can be "
            "eventually consistent. "
            + _distractor("warehouse", 60)
        ),
    ),
]


def run_recall_benchmark() -> dict[str, object]:
    stash = Stele.from_config(
        {
            "backend": {"type": "memory"},
            "indexing": {
                "provider": "chunkshop",
                "mode": "sync",
                "chunk_words": 80,
                "chunk_overlap_words": 20,
            },
        }
    )
    references: dict[str, str] = {}
    for case in CASES:
        references[case.name] = stash.store(case.content, namespace="recall").reference

    results: list[RecallResult] = []
    for case in CASES:
        hits = stash.search(references[case.name], case.query, mode="hybrid", limit=3)
        expected_lower = case.expected_answer.lower()
        ranks = [
            idx
            for idx, hit in enumerate(hits, start=1)
            if expected_lower in hit.text.lower()
        ]
        rank = ranks[0] if ranks else 0
        results.append(
            RecallResult(
                name=case.name,
                recall_at_1=1.0 if rank == 1 else 0.0,
                answer_accuracy=1.0 if rank > 0 else 0.0,
                reciprocal_rank=(1.0 / rank) if rank else 0.0,
                top_hit_chars=len(hits[0].text) if hits else 0,
                direct_context_answer_accuracy=(
                    1.0 if expected_lower in case.content.lower() else 0.0
                ),
            )
        )

    summary = {
        "case_count": len(results),
        "direct_context_answer_accuracy": _mean(
            result.direct_context_answer_accuracy for result in results
        ),
        "retrieval_answer_accuracy": _mean(result.answer_accuracy for result in results),
        "recall_at_1": _mean(result.recall_at_1 for result in results),
        "mrr": _mean(result.reciprocal_rank for result in results),
        "meets_90pct_accuracy_target": _mean(result.answer_accuracy for result in results) >= 0.9,
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "benchmark": "recall",
        "versions": version_info(),
        "summary": summary,
        "results": [asdict(result) for result in results],
    }


def write_report(report: dict[str, object], output_dir: Path | None = None) -> Path:
    date_dir = datetime.now(UTC).strftime("%Y-%m-%d")
    target_dir = output_dir or Path("benchmarks/runs") / date_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "Recall.json"
    md_path = target_dir / "Recall.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return md_path


def main() -> None:
    report = run_recall_benchmark()
    print(write_report(report))


def _markdown(report: dict[str, object]) -> str:
    summary = report["summary"]
    assert isinstance(summary, dict)
    rows = [
        "# Stele Recall Benchmark",
        "",
        "This report measures whether retrieval returns the answer-bearing span. "
        "It does not claim model answer quality beyond this deterministic fixture.",
        "",
        f"**Package versions**: {versions_md_line()}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in summary.items():
        rows.append(f"| {key} | {value} |")
    rows.extend(
        [
            "",
            "| Case | Recall@1 | Answer accuracy | MRR | Top hit chars |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    results = report["results"]
    assert isinstance(results, list)
    for item in results:
        assert isinstance(item, dict)
        rows.append(
            f"| `{item['name']}` | {item['recall_at_1']} | {item['answer_accuracy']} | "
            f"{item['reciprocal_rank']} | {item['top_hit_chars']} |"
        )
    rows.append("")
    return "\n".join(rows)


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


if __name__ == "__main__":
    main()
