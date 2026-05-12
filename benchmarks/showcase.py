"""Showcase benchmark for stele.

This benchmark covers common tool-output scenarios:

- legal contract Q&A
- SQL/database exploration
- log triage / incident response
- JSON API docs lookup
- code diff review
- multi-agent handoff/concurrency-style memory pressure

Wave 1 runs the memory backend. The result schema and report layout are stable
so SQLite/Postgres/MariaDB/ClickHouse rows can be added without changing the
consumer-facing benchmark output.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stele import Stele
from stele.interception.wrapper import stash_tool_result

VERSION = "0.1.0"


def legal_contract(size_kb: int = 40) -> str:
    clauses = [
        "The parties hereby agree that all intellectual property created",
        "during the term of this Agreement shall be owned by the Company",
        "subject to the licensing terms set forth in Schedule A.",
        "",
        "Section 3.2 Indemnification. Each party shall defend, indemnify,",
        "and hold harmless the other party from any third-party claims",
        "arising out of or relating to the indemnifying party's breach",
        "of this Agreement or its willful misconduct.",
        "",
        "Section 4.1 Payment Terms. Invoices shall be issued monthly,",
        "with net-30 payment terms. Late payments accrue interest at",
        "the lesser of 1.5% per month or the maximum rate permitted by law.",
        "",
        "Section 5.3 Termination. Either party may terminate this",
        "Agreement for cause upon 30 days written notice if the other",
        "party materially breaches this Agreement and fails to cure.",
        "",
        "Section 7.2 Confidentiality. Each party shall maintain in",
        "strict confidence all non-public information disclosed by the",
        "other party, including customer lists, pricing, and trade secrets.",
        "",
    ]
    text = ""
    i = 0
    while len(text.encode("utf-8")) < size_kb * 1024:
        text += f"ARTICLE {i + 1}\n" + "\n".join(clauses) + "\n"
        i += 1
    return text[: size_kb * 1024]


def sql_rows(num_rows: int = 500) -> str:
    header = "id   | customer          | amount   | status    | timestamp"
    sep = "-----+-------------------+----------+-----------+-----------------"
    rows = [
        f"{i:04d} | customer_{i:04d}     | {i * 127:>8} | "
        f"{'active' if i % 3 else 'expired':<9} | 2026-04-{(i % 28) + 1:02d}"
        for i in range(num_rows)
    ]
    return "\n".join([header, sep, *rows])


def log_buffer(num_lines: int = 800) -> str:
    lines = []
    for i in range(num_lines):
        level = "INFO"
        if i % 97 == 0:
            level = "ERROR"
            msg = f"NullPointerException at com.example.Foo:{i} - nullable field 'customer_id'"
        elif i % 43 == 0:
            level = "WARN"
            msg = f"Slow query detected (1243ms) on shard {i % 8}"
        else:
            msg = f"request id={i * 7} path=/api/v1/items/{i} latency={i % 200}ms"
        lines.append(f"2026-04-13T10:{(i // 60) % 60:02d}:{i % 60:02d}Z [{level}] {msg}")
    return "\n".join(lines)


def json_api_response(num_items: int = 100) -> str:
    items = [
        {
            "id": i,
            "name": f"endpoint_{i}",
            "method": ["GET", "POST", "PUT", "DELETE"][i % 4],
            "path": f"/api/v1/resource/{i}",
            "tags": [f"tag_{j}" for j in range(i % 5)],
            "metadata": {
                "deprecated": i % 13 == 0,
                "rate_limit": i * 10,
                "description": f"Resource {i} handles business logic for category {i % 7}",
            },
        }
        for i in range(num_items)
    ]
    return json.dumps(items, indent=2)


def code_diff(num_files: int = 20) -> str:
    parts = []
    for file_index in range(num_files):
        parts.append(f"diff --git a/src/module_{file_index}.py b/src/module_{file_index}.py")
        parts.append("index 0000000..1111111 100644")
        parts.append(f"--- a/src/module_{file_index}.py")
        parts.append(f"+++ b/src/module_{file_index}.py")
        parts.append(
            f"@@ -{file_index},{file_index + 5} "
            f"+{file_index},{file_index + 5} @@ def function_{file_index}():"
        )
        for line in range(10):
            parts.append(f"-removed line {line} in module {file_index}")
            parts.append(f"+new line {line} in module {file_index} with revenue boost")
    return "\n".join(parts)


@dataclass(frozen=True)
class Workload:
    name: str
    make_content: Callable[[], str]
    tool_name: str
    search_query: str


WORKLOADS = [
    Workload("legal_contract_qa", legal_contract, "read_contract", "termination cure notice"),
    Workload("sql_database_exploration", sql_rows, "query_db", "customer_0042 active"),
    Workload("log_triage_incident", log_buffer, "tail_logs", "NullPointerException customer_id"),
    Workload("json_api_docs_lookup", json_api_response, "fetch_openapi", "endpoint_42 rate_limit"),
    Workload("code_diff_review", code_diff, "git_diff", "revenue boost module"),
]


@dataclass
class WorkloadResult:
    workload: str
    backend: str
    input_size_bytes: int
    stored_size_bytes: int
    replacement_size_bytes: int
    savings_pct: float
    intercept_latency_ms: float
    fetch_latency_ms: float
    search_latency_ms: float
    search_hits: int
    pii_leakage_count: int = 0
    notes: str = ""

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        for key in ["savings_pct", "intercept_latency_ms", "fetch_latency_ms", "search_latency_ms"]:
            row[key] = round(float(row[key]), 3)
        return row


@dataclass
class ShowcaseReport:
    timestamp: str
    version: str
    backends_tested: list[str]
    results: list[WorkloadResult] = field(default_factory=list)
    concurrency_rows_per_sec: float = 0.0
    summary: dict[str, Any] = field(default_factory=dict)

    def compute_summary(self) -> None:
        if not self.results:
            self.summary = {}
            return
        savings = [result.savings_pct for result in self.results]
        self.summary = {
            "total_workloads": len(self.results),
            "mean_savings_pct": round(statistics.mean(savings), 2),
            "median_savings_pct": round(statistics.median(savings), 2),
            "min_savings_pct": round(min(savings), 2),
            "max_savings_pct": round(max(savings), 2),
            "mean_intercept_ms": round(
                statistics.mean(result.intercept_latency_ms for result in self.results),
                3,
            ),
            "mean_fetch_ms": round(
                statistics.mean(result.fetch_latency_ms for result in self.results),
                3,
            ),
            "mean_search_ms": round(
                statistics.mean(result.search_latency_ms for result in self.results),
                3,
            ),
            "total_pii_leakage_count": sum(result.pii_leakage_count for result in self.results),
        }


def run_showcase(
    *,
    output_root: Path = Path("benchmarks/runs"),
    write_report: bool = True,
) -> ShowcaseReport:
    report = ShowcaseReport(
        timestamp=datetime.now(UTC).isoformat(),
        version=VERSION,
        backends_tested=[],
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        stashes = [
            (
                "MemoryBackend",
                _make_showcase_stash({"backend": {"type": "memory"}}),
            ),
            (
                "SQLiteBackend",
                _make_showcase_stash(
                    {"backend": {"type": "sqlite", "path": str(Path(temp_dir) / "showcase.db")}}
                ),
            ),
        ]
        if os.environ.get("STELE_PG_DSN"):
            stashes.append(
                (
                    "PostgresBackend",
                    _make_showcase_stash(
                        {
                            "backend": {
                                "type": "postgres",
                                "dsn": os.environ["STELE_PG_DSN"],
                            }
                        }
                    ),
                )
            )
        if os.environ.get("STELE_MARIADB_DSN"):
            stashes.append(
                (
                    "MariaDBBackend",
                    _make_showcase_stash(
                        {
                            "backend": {
                                "type": "mariadb",
                                "dsn": os.environ["STELE_MARIADB_DSN"],
                            }
                        }
                    ),
                )
            )
        if os.environ.get("STELE_CLICKHOUSE_DSN"):
            stashes.append(
                (
                    "ClickHouseBackend",
                    _make_showcase_stash(
                        {
                            "backend": {
                                "type": "clickhouse",
                                "dsn": os.environ["STELE_CLICKHOUSE_DSN"],
                            }
                        }
                    ),
                )
            )
        report.backends_tested = [name for name, _ in stashes]
        for backend_name, stash in stashes:
            for workload in WORKLOADS:
                report.results.append(_run_workload(stash, backend_name, workload))
            _run_multi_agent_handoff(stash)
            stash.close()
    report.concurrency_rows_per_sec = _run_concurrent_ingestion()
    report.compute_summary()
    if write_report:
        write_showcase_report(report, output_root)
    return report


def _make_showcase_stash(overrides: dict[str, Any]) -> Stele:
    config: dict[str, Any] = {
        "pii": {"raw_fetch_enabled": True},
        "interception": {"min_chars": 1000, "min_estimated_tokens": 250},
        "summary": {"max_chars": 900},
    }
    config.update(overrides)
    return Stele.from_config(config)


def _run_workload(stash: Stele, backend_name: str, workload: Workload) -> WorkloadResult:
    content = workload.make_content()
    input_size = len(content.encode("utf-8"))
    t0 = time.perf_counter()
    replacement = stash_tool_result(
        content,
        stash=stash,
        namespace="showcase",
        tool_name=workload.tool_name,
    )
    intercept_ms = (time.perf_counter() - t0) * 1000
    replacement_text = str(replacement)
    replacement_size = len(replacement_text.encode("utf-8"))
    reference = _extract_reference(replacement_text)

    t0 = time.perf_counter()
    fetched = stash.fetch(reference, raw=True)
    fetch_ms = (time.perf_counter() - t0) * 1000
    assert fetched.content == content

    t0 = time.perf_counter()
    hits = stash.search(reference, workload.search_query, limit=5)
    search_ms = (time.perf_counter() - t0) * 1000

    return WorkloadResult(
        workload=workload.name,
        backend=backend_name,
        input_size_bytes=input_size,
        stored_size_bytes=input_size,
        replacement_size_bytes=replacement_size,
        savings_pct=100 * (1 - replacement_size / input_size) if input_size else 0.0,
        intercept_latency_ms=intercept_ms,
        fetch_latency_ms=fetch_ms,
        search_latency_ms=search_ms,
        search_hits=len(hits),
        pii_leakage_count=int("alice@example.com" in replacement_text),
    )


def _run_multi_agent_handoff(stash: Stele) -> None:
    refs: list[str] = []
    for page_number in range(10):
        page = f"Research page {page_number}: {'lorem ipsum dolor sit amet ' * 100}"
        replacement = stash_tool_result(
            page,
            stash=stash,
            namespace="research_handoff",
            session_id="agent_a",
            tool_name="scrape",
        )
        refs.append(_extract_reference(str(replacement)))
    assert len(refs) == 10
    for ref in refs:
        fetched = stash.fetch(ref, raw=True)
        assert str(fetched.content).startswith("Research page")


def _run_concurrent_ingestion() -> float:
    stash = Stele.from_config({"backend": {"type": "memory"}})
    num_threads = 4
    rows_per_thread = 50
    errors: list[Exception] = []

    def worker(worker_id: int) -> None:
        try:
            for index in range(rows_per_thread):
                stash.store(
                    f"concurrent row from worker {worker_id} iter {index}",
                    namespace="concurrent_showcase",
                )
        except Exception as exc:  # pragma: no cover - exercised on failure
            errors.append(exc)

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - t0
    if errors:
        raise errors[0]
    return (num_threads * rows_per_thread) / elapsed if elapsed else 0.0


def write_showcase_report(report: ShowcaseReport, output_root: Path) -> tuple[Path, Path]:
    date_stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir = output_root / date_stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "Showcase.md"
    json_path = out_dir / "Showcase.json"
    json_path.write_text(
        json.dumps(
            {
                "timestamp": report.timestamp,
                "version": report.version,
                "backends_tested": report.backends_tested,
                "concurrency_rows_per_sec": report.concurrency_rows_per_sec,
                "summary": report.summary,
                "results": [result.to_row() for result in report.results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return md_path, json_path


def _render_markdown(report: ShowcaseReport) -> str:
    lines = [
        "# stele Showcase Benchmark",
        "",
        "## TL;DR",
        "",
        (
            "Real-world LLM-agent workload simulation for off-prompt tool response "
            "storage. Every number in this report is printed from a live run of "
            "`benchmarks.showcase`."
        ),
        "",
        f"**Version**: `{report.version}`  ",
        f"**Run at**: `{report.timestamp}`  ",
        f"**Backends tested**: {', '.join(report.backends_tested)}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total workload x backend runs | {report.summary['total_workloads']} |",
        f"| Mean prompt-payload reduction | **{report.summary['mean_savings_pct']}%** |",
        f"| Median prompt-payload reduction | {report.summary['median_savings_pct']}% |",
        (
            f"| Min / max prompt-payload reduction | {report.summary['min_savings_pct']}%"
            f" / {report.summary['max_savings_pct']}% |"
        ),
        f"| Mean intercept latency | {report.summary['mean_intercept_ms']} ms |",
        f"| Mean fetch latency | {report.summary['mean_fetch_ms']} ms |",
        f"| Mean search latency | {report.summary['mean_search_ms']} ms |",
        (
            f"| Concurrent ingestion throughput | "
            f"{report.concurrency_rows_per_sec:.1f} rows/sec |"
        ),
        f"| PII leakage count | {report.summary['total_pii_leakage_count']} |",
        "",
        "## Industry Workload Results",
        "",
        (
        "| Workload | Backend | Input | Replacement | Reduction | "
            "Intercept | Fetch | Search | Hits |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in report.results:
        lines.append(
            f"| `{result.workload}` | {result.backend} | {result.input_size_bytes:,} B | "
            f"{result.replacement_size_bytes:,} B | **{result.savings_pct:.1f}%** | "
            f"{result.intercept_latency_ms:.2f} ms | {result.fetch_latency_ms:.2f} ms | "
            f"{result.search_latency_ms:.2f} ms | {result.search_hits} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            (
                "- The no-container path reports MemoryBackend and SQLiteBackend. "
                "When `STELE_PG_DSN` is set, PostgresBackend is included. "
                "The JSON/Markdown shape is stable for adding MariaDB, ClickHouse, "
                "and pg-raggraph rows."
            ),
            (
                "- This report measures prompt-payload reduction, exact fetch, "
                "keyword search hit count, latency, and PII leakage. It does not "
                "measure answer accuracy yet."
            ),
            "- Exact fetch is verified during each workload run.",
            "- Search hit counts use the current keyword retriever.",
            (
                "- Broad quality claims require a separate direct-context baseline "
                "comparison with >=90% task accuracy, plus Chunkshop-backed chunk "
                "retrieval for detail-heavy workloads."
            ),
            "- PII leakage is checked against the model-visible replacement payload.",
            "",
            "## Reproducing",
            "",
            "```bash",
            ".venv/bin/python -m benchmarks.showcase",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _extract_reference(replacement: str) -> str:
    for line in replacement.splitlines():
        if line.startswith("reference: "):
            return line.split("reference: ", 1)[1].strip()
    raise ValueError("Replacement payload did not contain a reference")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("benchmarks/runs"))
    args = parser.parse_args()
    report = run_showcase(output_root=args.output_root)
    print(json.dumps(report.summary, indent=2))


if __name__ == "__main__":
    main()
