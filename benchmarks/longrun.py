"""Long-running benchmark matrix for Stele.

This is the claim-building lane, not the fast showcase. It runs 35 deterministic
scenario families across configured backends and writes incremental JSONL so a
multi-hour run still leaves inspectable evidence if interrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from stele import PIIBlockedError, Stele
from stele.core.reference import parse_reference
from stele.interception.wrapper import stash_tool_result

ScenarioKind = Literal[
    "tool_output",
    "long_memory",
    "temporal",
    "pii",
    "retrieval",
    "performance",
]


@dataclass(frozen=True)
class BenchmarkScenario:
    name: str
    kind: ScenarioKind
    content: str
    query: str
    expected_answer: str | None
    sensitive_literals: tuple[str, ...] = ()
    session_id: str = "session-a"
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class ScenarioResult:
    run_id: str
    iteration: int
    backend: str
    scenario: str
    kind: str
    input_bytes: int
    replacement_bytes: int
    payload_reduction_pct: float
    direct_context_answer: bool
    retrieved_answer: bool
    recall_at_1: float
    mrr: float
    pii_leak_count: int
    exact_fetch_ok: bool
    raw_fetch_blocked: bool
    intercept_ms: float
    fetch_ms: float
    search_ms: float
    query_ms: float
    hit_count: int


def run_long_benchmark(
    *,
    backends: list[str],
    repeat: int,
    content_multiplier: int,
    output_root: Path,
    append_jsonl: bool = True,
) -> dict[str, Any]:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = output_root / datetime.now(UTC).strftime("%Y-%m-%d") / f"longrun-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = run_dir / "results.jsonl"
    scenarios = build_scenarios(content_multiplier=content_multiplier)

    results: list[ScenarioResult] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for backend_name, stash in _build_stashes(backends, Path(temp_dir)):
            try:
                for iteration in range(repeat):
                    for scenario in scenarios:
                        result = _run_scenario(
                            run_id=run_id,
                            iteration=iteration,
                            backend_name=backend_name,
                            stash=stash,
                            scenario=scenario,
                        )
                        results.append(result)
                        if append_jsonl:
                            with jsonl_path.open("a", encoding="utf-8") as handle:
                                handle.write(json.dumps(asdict(result), sort_keys=True))
                                handle.write("\n")
            finally:
                stash.close()

    report = _summarize(
        run_id=run_id,
        scenarios=scenarios,
        backends=backends,
        repeat=repeat,
        content_multiplier=content_multiplier,
        results=results,
    )
    (run_dir / "LongRun.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "LongRun.md").write_text(_markdown(report), encoding="utf-8")
    latest = output_root / "latest-longrun.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps({"run_dir": str(run_dir), **report}, indent=2), encoding="utf-8")
    return {"run_dir": str(run_dir), **report}


def build_scenarios(*, content_multiplier: int = 1) -> list[BenchmarkScenario]:
    base = [
        _scenario("legal_termination", "tool_output", "termination cure notice is 30 days"),
        _scenario("legal_confidentiality", "tool_output", "confidential pricing is protected"),
        _scenario("sql_customer_status", "tool_output", "customer_0042 status is active"),
        _scenario("sql_revenue_anomaly", "tool_output", "revenue anomaly is account_0097"),
        _scenario("log_null_pointer", "tool_output", "root cause is nullable customer_id"),
        _scenario("log_slow_query", "tool_output", "slow query shard is shard 7"),
        _scenario("json_rate_limit", "tool_output", "endpoint_42 rate limit is 420"),
        _scenario("json_deprecation", "tool_output", "endpoint_13 is deprecated"),
        _scenario("code_security_fix", "tool_output", "security fix is sanitize_redirect"),
        _scenario("code_perf_fix", "tool_output", "performance fix is batch_fetch_orders"),
        _scenario("csv_inventory", "tool_output", "sku_884 has reorder threshold 17"),
        _scenario("html_policy", "tool_output", "policy section is data retention"),
        _scenario("markdown_runbook", "tool_output", "runbook restart order is api worker db"),
        _scenario("trace_latency", "tool_output", "slow span is payment_authorize"),
        _scenario("ticket_escalation", "tool_output", "escalation owner is platform-oncall"),
        _scenario("profile_pet_name", "long_memory", "the user's dog is named Miso"),
        _scenario("profile_food_pref", "long_memory", "the user avoids cilantro"),
        _scenario("project_decision", "long_memory", "project backend decision is postgres first"),
        _scenario("meeting_commitment", "long_memory", "commitment is deliver audit logs"),
        _scenario(
            "cross_session_synthesis",
            "long_memory",
            "Apollo uses MariaDB and Borealis uses ClickHouse",
        ),
        _scenario("temporal_old_title", "temporal", "in March the title was analyst"),
        _scenario("temporal_new_title", "temporal", "in April the title became director"),
        _scenario("knowledge_update_address", "temporal", "current office is building C"),
        _scenario("knowledge_update_preference", "temporal", "current editor is Helix"),
        _scenario("abstention_missing", "retrieval", None),
        _scenario(
            "multi_hop_owner",
            "retrieval",
            "incident owner is Riley because Riley owns payments",
        ),
        _scenario("multi_hop_dependency", "retrieval", "checkout depends on inventory and pricing"),
        _scenario("needle_early", "retrieval", "needle appears in the opening paragraph"),
        _scenario("needle_middle", "retrieval", "needle appears in the middle paragraph"),
        _scenario("needle_late", "retrieval", "needle appears in the closing paragraph"),
        _pii_scenario("pii_email", "email contact record", "alice@example.com"),
        _pii_scenario("pii_phone", "phone contact record", "212-555-0199"),
        _pii_scenario("pii_ssn", "tax identifier record", "123-45-6789"),
        _pii_scenario("pii_card", "card token record", "4111 1111 1111 1111"),
        _pii_scenario("pii_secret", "api secret record", "sk-test-1234567890abcdef"),
    ]
    return [_inflate_scenario(scenario, content_multiplier) for scenario in base]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the long benchmark matrix")
    parser.add_argument("--backends", default="auto", help="Comma list or 'auto'")
    parser.add_argument(
        "--repeat",
        type=int,
        default=int(os.environ.get("YMS_LONGRUN_REPEAT", "1")),
    )
    parser.add_argument(
        "--content-multiplier",
        type=int,
        default=int(os.environ.get("YMS_LONGRUN_CONTENT_MULTIPLIER", "8")),
    )
    parser.add_argument("--output-root", type=Path, default=Path("benchmarks/runs"))
    args = parser.parse_args()

    backends = _resolve_backends(args.backends)
    report = run_long_benchmark(
        backends=backends,
        repeat=args.repeat,
        content_multiplier=args.content_multiplier,
        output_root=args.output_root,
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(report["run_dir"])


def _scenario(
    name: str,
    kind: ScenarioKind,
    expected_answer: str | None,
    *,
    sensitive_literals: tuple[str, ...] = (),
) -> BenchmarkScenario:
    if expected_answer is None:
        query = "missing warranty exception"
        content = _document(
            name,
            "This record discusses onboarding preferences and routine project notes.",
            "The requested facts are absent and retrieval should return no answer-bearing hit.",
        )
    else:
        query = _query_for_expected(expected_answer)
        content = _document(
            name,
            f"Answer-bearing fact: {expected_answer}.",
            f"Audit note for {name}: the exact answer must remain retrievable.",
        )
    return BenchmarkScenario(
        name=name,
        kind=kind,
        content=content,
        query=query,
        expected_answer=expected_answer,
        sensitive_literals=sensitive_literals,
        metadata={"scenario": name, "kind": kind},
    )


def _pii_scenario(name: str, expected_answer: str, sensitive_literal: str) -> BenchmarkScenario:
    content = _document(
        name,
        f"Sensitive value: {sensitive_literal}. Retrieval-safe fact: {expected_answer}.",
        "The sensitive literal must not appear on model-visible surfaces.",
    )
    return BenchmarkScenario(
        name=name,
        kind="pii",
        content=content,
        query=_query_for_expected(expected_answer),
        expected_answer=expected_answer,
        sensitive_literals=(sensitive_literal,),
        metadata={"scenario": name, "kind": "pii"},
    )


def _query_for_expected(expected_answer: str) -> str:
    stop_words = {
        "the",
        "is",
        "in",
        "on",
        "at",
        "and",
        "or",
        "to",
        "a",
        "an",
        "was",
        "became",
        "because",
    }
    terms = [
        term.strip(".,:;").lower()
        for term in expected_answer.split()
        if term.strip(".,:;").lower() not in stop_words
    ]
    return " ".join(terms[:4])


def _inflate_scenario(scenario: BenchmarkScenario, multiplier: int) -> BenchmarkScenario:
    if multiplier <= 1:
        return scenario
    blocks = []
    for index in range(multiplier):
        filler = " ".join(f"neutral_filler_{index}_{word}" for word in range(180))
        if index == multiplier // 2:
            blocks.append(scenario.content)
        else:
            blocks.append(f"Filler block {index}. {filler}.")
    return BenchmarkScenario(
        name=scenario.name,
        kind=scenario.kind,
        content="\n\n".join(blocks),
        query=scenario.query,
        expected_answer=scenario.expected_answer,
        sensitive_literals=scenario.sensitive_literals,
        session_id=scenario.session_id,
        metadata=scenario.metadata,
    )


def _document(name: str, answer: str, note: str) -> str:
    del name
    intro = " ".join(f"intro_filler_{idx}" for idx in range(40))
    outro = " ".join(f"outro_filler_{idx}" for idx in range(40))
    return f"{intro}\n\n{answer}\n{note}\n\n{outro}"


def _run_scenario(
    *,
    run_id: str,
    iteration: int,
    backend_name: str,
    stash: Stele,
    scenario: BenchmarkScenario,
) -> ScenarioResult:
    namespace = f"longrun_{run_id}_{iteration}_{scenario.kind}"
    started = time.perf_counter()
    replacement = stash_tool_result(
        scenario.content,
        stash=stash,
        namespace=namespace,
        session_id=scenario.session_id,
        tool_name=scenario.name,
        metadata=scenario.metadata,
        always_store=True,
    )
    intercept_ms = _elapsed_ms(started)
    reference = _reference_from_replacement(str(replacement))

    started = time.perf_counter()
    fetched = stash.fetch(reference, scrub=True)
    fetch_ms = _elapsed_ms(started)
    stored_record = stash.storage.fetch(parse_reference(reference))
    exact_fetch_ok = fetched.digest_sha256 == stored_record.digest_sha256

    started = time.perf_counter()
    hits = stash.search(reference, scenario.query, limit=5)
    search_ms = _elapsed_ms(started)

    started = time.perf_counter()
    namespace_hits = stash.query(namespace, scenario.query, limit=5)
    query_ms = _elapsed_ms(started)

    direct_context_answer = _contains_expected(scenario.content, scenario.expected_answer)
    ranks = [
        idx
        for idx, hit in enumerate(hits, start=1)
        if _contains_expected(hit.text, scenario.expected_answer)
    ]
    rank = ranks[0] if ranks else 0
    if scenario.expected_answer is None:
        retrieved_answer = not hits and not namespace_hits
        recall_at_1 = 1.0 if retrieved_answer else 0.0
        mrr = 1.0 if retrieved_answer else 0.0
    else:
        retrieved_answer = rank > 0
        recall_at_1 = 1.0 if rank == 1 else 0.0
        mrr = (1.0 / rank) if rank else 0.0
    pii_leak_count = _pii_leak_count(str(replacement), fetched.content, hits, scenario)
    raw_fetch_blocked = _raw_fetch_is_blocked(stash, reference)
    input_bytes = len(scenario.content.encode("utf-8"))
    replacement_bytes = len(str(replacement).encode("utf-8"))
    return ScenarioResult(
        run_id=run_id,
        iteration=iteration,
        backend=backend_name,
        scenario=scenario.name,
        kind=scenario.kind,
        input_bytes=input_bytes,
        replacement_bytes=replacement_bytes,
        payload_reduction_pct=round(100 * (1 - replacement_bytes / input_bytes), 3),
        direct_context_answer=direct_context_answer,
        retrieved_answer=retrieved_answer,
        recall_at_1=recall_at_1,
        mrr=round(mrr, 3),
        pii_leak_count=pii_leak_count,
        exact_fetch_ok=exact_fetch_ok,
        raw_fetch_blocked=raw_fetch_blocked,
        intercept_ms=round(intercept_ms, 3),
        fetch_ms=round(fetch_ms, 3),
        search_ms=round(search_ms, 3),
        query_ms=round(query_ms, 3),
        hit_count=len(hits),
    )


def _build_stashes(backends: list[str], temp_dir: Path) -> list[tuple[str, Stele]]:
    stashes: list[tuple[str, Stele]] = []
    for backend in backends:
        config: dict[str, Any] = {
            "pii": {"raw_fetch_enabled": False},
            "interception": {
                "min_chars": 1,
                "min_estimated_tokens": 1,
                "max_replacement_chars": 1400,
            },
            "summary": {"max_chars": 900},
            "indexing": {
                "provider": "chunkshop",
                "mode": "sync",
                "chunk_words": 90,
                "chunk_overlap_words": 25,
            },
        }
        if backend == "memory":
            config["backend"] = {"type": "memory"}
        elif backend == "sqlite":
            config["backend"] = {"type": "sqlite", "path": str(temp_dir / "longrun.db")}
        elif backend == "postgres":
            config["backend"] = {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}
        elif backend == "mariadb":
            config["backend"] = {
                "type": "mariadb",
                "dsn": os.environ["STELE_MARIADB_DSN"],
            }
        elif backend == "clickhouse":
            config["backend"] = {
                "type": "clickhouse",
                "dsn": os.environ["STELE_CLICKHOUSE_DSN"],
            }
        else:
            raise ValueError(f"Unknown backend: {backend}")
        stashes.append((f"{backend.title()}Backend", Stele.from_config(config)))
    return stashes


def _resolve_backends(value: str) -> list[str]:
    if value != "auto":
        return [item.strip() for item in value.split(",") if item.strip()]
    backends = ["memory", "sqlite"]
    if os.environ.get("STELE_PG_DSN"):
        backends.append("postgres")
    if os.environ.get("STELE_MARIADB_DSN"):
        backends.append("mariadb")
    if os.environ.get("STELE_CLICKHOUSE_DSN"):
        backends.append("clickhouse")
    return backends


def _summarize(
    *,
    run_id: str,
    scenarios: list[BenchmarkScenario],
    backends: list[str],
    repeat: int,
    content_multiplier: int,
    results: list[ScenarioResult],
) -> dict[str, Any]:
    by_kind: dict[str, list[ScenarioResult]] = defaultdict(list)
    by_backend: dict[str, list[ScenarioResult]] = defaultdict(list)
    for result in results:
        by_kind[result.kind].append(result)
        by_backend[result.backend].append(result)
    summary = {
        "run_id": run_id,
        "scenario_count": len(scenarios),
        "backend_count": len(backends),
        "repeat": repeat,
        "content_multiplier": content_multiplier,
        "total_runs": len(results),
        "mean_payload_reduction_pct": _mean(r.payload_reduction_pct for r in results),
        "retrieval_answer_accuracy": _mean_bool(r.retrieved_answer for r in results),
        "direct_context_answer_accuracy": _mean_bool(r.direct_context_answer for r in results),
        "recall_at_1": _mean(r.recall_at_1 for r in results),
        "mrr": _mean(r.mrr for r in results),
        "total_pii_leaks": sum(r.pii_leak_count for r in results),
        "exact_fetch_accuracy": _mean_bool(r.exact_fetch_ok for r in results),
        "raw_fetch_block_rate": _mean_bool(r.raw_fetch_blocked for r in results),
        "mean_intercept_ms": _mean(r.intercept_ms for r in results),
        "mean_fetch_ms": _mean(r.fetch_ms for r in results),
        "mean_search_ms": _mean(r.search_ms for r in results),
        "mean_query_ms": _mean(r.query_ms for r in results),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "benchmark": "longrun",
        "summary": summary,
        "by_kind": {kind: _aggregate(group) for kind, group in sorted(by_kind.items())},
        "by_backend": {
            backend: _aggregate(group) for backend, group in sorted(by_backend.items())
        },
        "scenarios": [scenario.name for scenario in scenarios],
        "results": [asdict(result) for result in results],
    }


def _aggregate(results: list[ScenarioResult]) -> dict[str, Any]:
    return {
        "runs": len(results),
        "mean_payload_reduction_pct": _mean(r.payload_reduction_pct for r in results),
        "retrieval_answer_accuracy": _mean_bool(r.retrieved_answer for r in results),
        "recall_at_1": _mean(r.recall_at_1 for r in results),
        "mrr": _mean(r.mrr for r in results),
        "pii_leaks": sum(r.pii_leak_count for r in results),
        "exact_fetch_accuracy": _mean_bool(r.exact_fetch_ok for r in results),
        "mean_search_ms": _mean(r.search_ms for r in results),
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Stele Long-Run Benchmark",
        "",
        "This is the broad deterministic scenario lane. It is still local and deterministic; "
        "external datasets such as LongMemEval and RAGBench remain separate adapters.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## By Backend", "", "| Backend | Runs | Accuracy | R@1 | MRR | PII leaks |"])
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for backend, row in report["by_backend"].items():
        lines.append(
            f"| {backend} | {row['runs']} | {row['retrieval_answer_accuracy']} | "
            f"{row['recall_at_1']} | {row['mrr']} | {row['pii_leaks']} |"
        )
    lines.extend(
        ["", "## By Scenario Kind", "", "| Kind | Runs | Accuracy | R@1 | MRR | PII leaks |"]
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for kind, row in report["by_kind"].items():
        lines.append(
            f"| {kind} | {row['runs']} | {row['retrieval_answer_accuracy']} | "
            f"{row['recall_at_1']} | {row['mrr']} | {row['pii_leaks']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _reference_from_replacement(replacement: str) -> str:
    for line in replacement.splitlines():
        if line.startswith("reference: "):
            return line.removeprefix("reference: ").strip()
    raise ValueError("Replacement payload did not include a reference")


def _contains_expected(text: object, expected: str | None) -> bool:
    if expected is None:
        return True
    return expected.lower() in str(text).lower()


def _pii_leak_count(
    replacement: str,
    fetched_content: object,
    hits: list[Any],
    scenario: BenchmarkScenario,
) -> int:
    surfaces = [replacement, str(fetched_content), *(str(hit.text) for hit in hits)]
    leaks = 0
    for literal in scenario.sensitive_literals:
        leaks += sum(1 for surface in surfaces if literal in surface)
    return leaks


def _raw_fetch_is_blocked(stash: Stele, reference: str) -> bool:
    try:
        stash.fetch(reference, raw=True)
    except PIIBlockedError:
        return True
    return False


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _mean(values: Any) -> float:
    items = [float(value) for value in values]
    return round(statistics.mean(items), 4) if items else 0.0


def _mean_bool(values: Any) -> float:
    items = [1.0 if value else 0.0 for value in values]
    return round(statistics.mean(items), 4) if items else 0.0


if __name__ == "__main__":
    main()
