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

from benchmarks._versions import version_info, versions_md_line
from stele import PIIBlockedError, Stele
from stele.core.memory_record import MemoryQuery, MemoryScope
from stele.core.reference import parse_reference
from stele.interception.wrapper import stash_tool_result

# Feature flag: when "0" or "false" the temporal scenarios use raw artifact search
# (both old and new values are visible → forbidden substring check fails).
# When "1" (default) the temporal scenarios use memory.add(supersedes=...) so the
# old memory is hidden and only the new value is returned.
SUPERSESSION_ENABLED = os.environ.get("STELE_SUPERSESSION_ENABLED", "1") not in {
    "0",
    "false",
    "False",
}

ScenarioKind = Literal[
    "tool_output",
    "long_memory",
    "temporal",
    "pii",
    "retrieval",
    "performance",
]

# Each tuple: (pair_name, old_text, new_text, query, expected_new_sub, forbidden_old_sub)
#
# Queries are single distinctive terms that:
#   - appear in both old_text and new_text (so OFF-mode artifact search returns both)
#   - appear in both old_memory_text and new_memory_text (so ON-mode FTS/substring
#     search can find the active memory record)
# The forbidden_old_sub must NOT appear in new_text or new_memory_text.
# The expected_new_sub must NOT appear in old_text or old_memory_text.
_TEMPORAL_PAIRS: list[tuple[str, str, str, str, str, str]] = [
    (
        "temporal_title",
        "title: analyst",
        "title: director",
        "title",
        "director",
        "analyst",
    ),
    (
        "knowledge_update_address",
        "office: building A",
        "office: building C",
        "office",
        "building C",
        "building A",
    ),
    (
        "knowledge_update_preference",
        "editor: Helix",
        "editor: Zed",
        "editor",
        "Zed",
        "Helix",
    ),
    (
        "knowledge_update_role",
        "lead: Alex",
        "lead: Bren",
        "lead",
        "Bren",
        "Alex",
    ),
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
    # For temporal scenarios: old_text is the version that must be superseded.
    old_text: str | None = None
    # For temporal scenarios: new_text is the canonical new fact (used as memory text).
    new_text: str | None = None
    # The substring that must NOT appear in hits (proves supersession worked).
    forbidden_substring: str | None = None


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
    supersession_mode: str  # "enabled", "disabled", or "n/a"


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
    base: list[BenchmarkScenario] = [
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
        *_temporal_pair_scenarios(),
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


def _temporal_pair_scenarios() -> list[BenchmarkScenario]:
    """Build one BenchmarkScenario per temporal pair.

    The scenario content carries the NEW text (the answer we want returned).
    old_text is the stale version that must be superseded.
    expected_answer / forbidden_substring drive the pass/fail oracle.
    """
    scenarios: list[BenchmarkScenario] = []
    for pair_name, old_text, new_text, query, expected_new, forbidden_old in _TEMPORAL_PAIRS:
        content = _document(
            pair_name,
            f"Answer-bearing fact: {new_text}.",
            f"Audit note for {pair_name}: the current value must be retrievable.",
        )
        scenarios.append(
            BenchmarkScenario(
                name=pair_name,
                kind="temporal",
                content=content,
                query=query,
                expected_answer=expected_new,
                metadata={"scenario": pair_name, "kind": "temporal"},
                old_text=old_text,
                new_text=new_text,
                forbidden_substring=forbidden_old,
            )
        )
    return scenarios


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
        old_text=scenario.old_text,
        new_text=scenario.new_text,
        forbidden_substring=scenario.forbidden_substring,
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

    if scenario.kind == "temporal":
        return _run_temporal_scenario(
            run_id=run_id,
            iteration=iteration,
            backend_name=backend_name,
            stash=stash,
            scenario=scenario,
            namespace=namespace,
        )

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
        supersession_mode="n/a",
    )


def _run_temporal_scenario(
    *,
    run_id: str,
    iteration: int,
    backend_name: str,
    stash: Stele,
    scenario: BenchmarkScenario,
    namespace: str,
) -> ScenarioResult:
    """Run a temporal scenario with or without memory supersession.

    When SUPERSESSION_ENABLED=True:
      - Store old_text as an artifact, add it as a memory record.
      - Store new_text (scenario.content) as an artifact, add it as a memory
        record superseding the old one.
      - Search via stash.memory.search() — only the active (new) memory is
        returned.
      - Pass: new substring present AND old (forbidden) substring absent.

    When SUPERSESSION_ENABLED=False:
      - Store both old_text and new_text as plain artifacts (no memory layer).
      - Search via stash.query() — both artifacts are visible.
      - Fail: the forbidden (old) substring is present in the results.
    """
    assert scenario.old_text is not None, "temporal scenario must have old_text"
    assert scenario.forbidden_substring is not None, (
        "temporal scenario must have forbidden_substring"
    )
    assert scenario.expected_answer is not None, "temporal scenario must have expected_answer"

    # Use a unique namespace per scenario so runs don't cross-contaminate.
    temporal_ns = f"{namespace}_{scenario.name}"
    scope = MemoryScope(namespace=temporal_ns)

    # Build old_text document in the same shape as other scenarios.
    old_content = _document(
        scenario.name + "_old",
        f"Historical fact: {scenario.old_text}.",
        f"Audit note for {scenario.name}: this was the old value.",
    )

    intercept_ms = 0.0
    fetch_ms = 0.0
    search_ms = 0.0
    query_ms = 0.0
    hit_count = 0
    retrieved_answer = False
    recall_at_1 = 0.0
    mrr = 0.0

    if SUPERSESSION_ENABLED:
        # --- Supersession path ---
        # 1. Store old artifact and add to memory.
        t0 = time.perf_counter()
        old_stored = stash_tool_result(
            old_content,
            stash=stash,
            namespace=temporal_ns,
            session_id=scenario.session_id,
            tool_name=scenario.name + "_old",
            metadata={"scenario": scenario.name, "version": "old"},
            always_store=True,
        )
        old_ref = _reference_from_replacement(str(old_stored))
        old_memory = stash.memory.add(
            text=scenario.old_text,
            kind="fact",
            source_refs=[old_ref],
            scope=scope,
        )
        old_memory_id = old_memory.record.id

        # 2. Store new artifact and add as memory superseding the old.
        new_stored = stash_tool_result(
            scenario.content,
            stash=stash,
            namespace=temporal_ns,
            session_id=scenario.session_id,
            tool_name=scenario.name + "_new",
            metadata={"scenario": scenario.name, "version": "new"},
            always_store=True,
        )
        new_ref = _reference_from_replacement(str(new_stored))
        # New memory text: the full new_text phrase — searchable and free of forbidden term.
        assert scenario.new_text is not None, "temporal scenario must have new_text"
        stash.memory.add(
            text=scenario.new_text,
            kind="fact",
            source_refs=[new_ref],
            scope=scope,
            supersedes=[old_memory_id],
        )
        intercept_ms = _elapsed_ms(t0)

        # 3. Fetch via normal artifact path for exact_fetch_ok check.
        t1 = time.perf_counter()
        fetched = stash.fetch(new_ref, scrub=True)
        fetch_ms = _elapsed_ms(t1)
        stored_record = stash.storage.fetch(parse_reference(new_ref))
        exact_fetch_ok = fetched.digest_sha256 == stored_record.digest_sha256

        # 4. Search via memory API — superseded records are excluded by default.
        t2 = time.perf_counter()
        mem_hits = stash.memory.search(
            MemoryQuery(query=scenario.query, scope=scope, limit=5)
        )
        search_ms = _elapsed_ms(t2)
        query_ms = 0.0
        hit_count = len(mem_hits)

        # 5. Score: new substring present AND forbidden (old) substring absent.
        all_hit_text = " ".join(r.text for r in mem_hits).lower()
        new_present = scenario.expected_answer.lower() in all_hit_text
        old_absent = scenario.forbidden_substring.lower() not in all_hit_text
        retrieved_answer = new_present and old_absent
        recall_at_1 = 1.0 if retrieved_answer and hit_count >= 1 else 0.0
        mrr = 1.0 if retrieved_answer else 0.0

        # Metrics from new artifact.
        reference = new_ref
        input_bytes = len(scenario.content.encode("utf-8"))
        replacement_bytes = len(str(new_stored).encode("utf-8"))
        raw_fetch_blocked = _raw_fetch_is_blocked(stash, reference)
        pii_leak_count = 0
        supersession_mode = "enabled"

    else:
        # --- No-supersession path (keyword-coincidence baseline) ---
        # Store both old and new as plain artifacts in the same namespace.
        t0 = time.perf_counter()
        old_stored = stash_tool_result(
            old_content,
            stash=stash,
            namespace=temporal_ns,
            session_id=scenario.session_id,
            tool_name=scenario.name + "_old",
            metadata={"scenario": scenario.name, "version": "old"},
            always_store=True,
        )
        new_stored = stash_tool_result(
            scenario.content,
            stash=stash,
            namespace=temporal_ns,
            session_id=scenario.session_id,
            tool_name=scenario.name + "_new",
            metadata={"scenario": scenario.name, "version": "new"},
            always_store=True,
        )
        intercept_ms = _elapsed_ms(t0)

        new_ref = _reference_from_replacement(str(new_stored))

        t1 = time.perf_counter()
        fetched = stash.fetch(new_ref, scrub=True)
        fetch_ms = _elapsed_ms(t1)
        stored_record = stash.storage.fetch(parse_reference(new_ref))
        exact_fetch_ok = fetched.digest_sha256 == stored_record.digest_sha256

        t2 = time.perf_counter()
        hits = stash.query(temporal_ns, scenario.query, limit=5)
        search_ms = _elapsed_ms(t2)
        t3 = time.perf_counter()
        query_ms = _elapsed_ms(t3)
        hit_count = len(hits)

        # Score with the same oracle — forbidden substring will appear → fail.
        all_hit_text = " ".join(str(h.text) for h in hits).lower()
        new_present = scenario.expected_answer.lower() in all_hit_text
        old_absent = scenario.forbidden_substring.lower() not in all_hit_text
        retrieved_answer = new_present and old_absent
        recall_at_1 = 1.0 if retrieved_answer else 0.0
        mrr = 1.0 if retrieved_answer else 0.0

        reference = new_ref
        input_bytes = len(scenario.content.encode("utf-8"))
        replacement_bytes = len(str(new_stored).encode("utf-8"))
        raw_fetch_blocked = _raw_fetch_is_blocked(stash, reference)
        pii_leak_count = 0
        supersession_mode = "disabled"

    direct_context_answer = _contains_expected(scenario.content, scenario.expected_answer)
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
        hit_count=hit_count,
        supersession_mode=supersession_mode,
    )


def _build_stashes(backends: list[str], temp_dir: Path) -> list[tuple[str, Stele]]:
    stashes: list[tuple[str, Stele]] = []
    for backend in backends:
        config: dict[str, Any] = {
            "pii": {"enabled": True, "raw_fetch_enabled": False},
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
        "supersession_enabled": SUPERSESSION_ENABLED,
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
        "versions": version_info(),
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
    supersession_mode = "ENABLED" if summary.get("supersession_enabled") else "DISABLED"
    lines = [
        "# Stele Long-Run Benchmark",
        "",
        "This is the broad deterministic scenario lane. It is still local and deterministic; "
        "external datasets such as LongMemEval and RAGBench remain separate adapters.",
        "",
        f"**Supersession mode:** {supersession_mode} "
        "(set `STELE_SUPERSESSION_ENABLED=0` to run the no-supersession baseline)",
        "",
        f"**Package versions**: {versions_md_line()}",
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
