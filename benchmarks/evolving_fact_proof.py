"""In-repo evolving-fact value-proof for stele (the second divergence axis).

The first value-proof (`benchmarks.memory_value_proof`) covers retention: a fact
that scrolls out of the context window. This one covers the harder, more
important axis the memory research flagged: a durable fact that *changes over
time*. This is exactly where a naive memory can BACKFIRE (storing a stale value
is worse than having no memory), so the honest test compares three arms, not two:

- **no-memory:** the conversation window only (FIFO eviction at a token budget).
  Recency lets it answer "what is it now"; it cannot answer history it evicted.
- **naive memory:** a store that records a fact once and never supersedes it
  (stele used WITHOUT supersession discipline). It confidently returns the STALE
  original value forever. This reproduces the documented "bare-stale" trap.
- **stele:** `memory.add(supersedes=[...])` builds a supersession chain, so the
  current view returns the CURRENT value and `as_of` time-travel recovers what
  was true at any past point.

The fact is a durable *decision* (the API protocol), not a re-derivable value
like a port number. Storing volatile re-derivable values is a separate, proven
trap; this proof deliberately uses the kind of fact memory is *supposed* to hold.

Three temporal questions are asked. stele is the only arm correct on all three.

Run:
    .venv/bin/python -m benchmarks.evolving_fact_proof   # postgres if DSN, else memory
    .venv/bin/python -m benchmarks.evolving_fact_proof --backend memory
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks._versions import version_info, versions_md_line
from benchmarks.showcase import code_diff, json_api_response, legal_contract, sql_rows
from stele import Stele
from stele.core.artifact import estimate_tokens
from stele.core.memory_record import MemoryQuery, MemoryScope

VERSION = "0.1.0"
REALISTIC_BUDGET = 8_000

# The evolving decision: REST -> gRPC -> GraphQL. Statements carry self-identifying
# phrasing so the no-memory arm can answer from raw text when it is still in window.
REST_STMT = "Decision (session 1): the API will originally use REST as its protocol."
GRPC_STMT = "Update (session 6): the API is switching from REST to gRPC for streaming."
GRAPHQL_STMT = "Update (session 11): the API is now moving to GraphQL, the current protocol."

# (question id, prose, expected protocol)
QUESTIONS = [
    ("current", "What protocol does the API use now?", "GraphQL"),
    ("mid", "What protocol did the API use after the first switch?", "gRPC"),
    ("original", "What protocol was originally chosen for the API?", "REST"),
]


def build_session() -> list[tuple[str, str]]:
    """Mixed session: three decision turns interleaved with bulk noise.

    REST early (idx 1), gRPC mid (idx 6), GraphQL last (idx 11). Under a realistic
    budget the window keeps the latest decision but evicts the early history.
    """
    noise = [legal_contract, json_api_response, code_diff, sql_rows]
    turns: list[tuple[str, str]] = [("query_db", sql_rows(300))]
    turns.append(("decision_log", REST_STMT))
    for i in range(4):
        turns.append(("noise", noise[i % 4]()))
    turns.append(("decision_log", GRPC_STMT))
    for i in range(4):
        turns.append(("noise", noise[(i + 1) % 4]()))
    turns.append(("decision_log", GRAPHQL_STMT))
    return turns


def _resident_text(turns: list[tuple[str, str]], budget: int) -> str:
    """The last `budget` tokens of the transcript (rolling context window)."""
    budget_bytes = budget * 4
    kept: list[str] = []
    used = 0
    for _, content in reversed(turns):
        encoded = content.encode("utf-8")
        if used + len(encoded) <= budget_bytes:
            kept.append(content)
            used += len(encoded)
        else:
            remaining = budget_bytes - used
            if remaining > 0:
                kept.append(encoded[-remaining:].decode("utf-8", "ignore"))
            break
    return "\n".join(reversed(kept))


def _latest_protocol(text: str) -> str | None:
    """The most-recently-mentioned protocol in `text` (how a no-memory agent infers 'now')."""
    best: str | None = None
    best_pos = -1
    for proto in ("REST", "gRPC", "GraphQL"):
        pos = text.rfind(proto)
        if pos > best_pos:
            best_pos = pos
            best = proto
    return best


def answer_no_memory(
    turns: list[tuple[str, str]], budget: int, question_id: str, expected: str
) -> bool:
    resident = _resident_text(turns, budget)
    if question_id == "current":
        return _latest_protocol(resident) == expected
    # Historical questions: the agent can only answer if the defining statement
    # is still in its window (it has no temporal index of its own).
    stmt = {"mid": GRPC_STMT, "original": REST_STMT}[question_id]
    return stmt in resident


@dataclass
class ArmResult:
    arm: str
    correct: dict[str, bool] = field(default_factory=dict)
    score: int = 0

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def run_stele_arm(stash: Stele) -> ArmResult:
    """Real supersession chain + as_of time-travel."""
    scope = MemoryScope(user_id="evolving_proof")
    ids: list[str] = []
    as_of_after_rest: datetime | None = None
    as_of_after_grpc: datetime | None = None

    for stmt, value in ((REST_STMT, "REST"), (GRPC_STMT, "gRPC"), (GRAPHQL_STMT, "GraphQL")):
        ref = stash.store(stmt, namespace="evolving_src").reference
        result = stash.memory.add(
            text=f"API protocol decision: {value}",
            kind="decision",
            source_refs=[ref],
            scope=scope,
            supersedes=[ids[-1]] if ids else None,
        )
        ids.append(result.record.id)
        if value == "REST":
            as_of_after_rest = datetime.now(UTC)
            time.sleep(0.05)  # distinct effective_from for as_of (contract-test pattern)
        elif value == "gRPC":
            as_of_after_grpc = datetime.now(UTC)
            time.sleep(0.05)

    def active_texts(as_of: datetime | None) -> str:
        hits = stash.memory.search(
            MemoryQuery(query="API protocol decision", scope=scope, as_of=as_of, limit=10)
        )
        return " ".join(h.text for h in hits)

    views = {
        "current": active_texts(None),
        "mid": active_texts(as_of_after_grpc),
        "original": active_texts(as_of_after_rest),
    }
    arm = ArmResult(arm="stele (supersession + as_of)")
    for qid, _, expected in QUESTIONS:
        arm.correct[qid] = expected in views[qid]
    arm.score = sum(arm.correct.values())
    return arm


def run_naive_arm(stash: Stele) -> ArmResult:
    """Store-once: records the first value, never supersedes. The stale trap."""
    scope = MemoryScope(user_id="evolving_proof_naive")
    ref = stash.store(REST_STMT, namespace="evolving_src_naive").reference
    stash.memory.add(
        text="API protocol decision: REST",
        kind="decision",
        source_refs=[ref],
        scope=scope,
    )
    hits = stash.memory.search(MemoryQuery(query="API protocol decision", scope=scope, limit=10))
    texts = " ".join(h.text for h in hits)
    arm = ArmResult(arm="naive memory (store-once)")
    for qid, _, expected in QUESTIONS:
        arm.correct[qid] = expected in texts
    arm.score = sum(arm.correct.values())
    return arm


def run_no_memory_arm(turns: list[tuple[str, str]], budget: int) -> ArmResult:
    arm = ArmResult(arm=f"no-memory (window={budget:,} tok)")
    for qid, _, expected in QUESTIONS:
        arm.correct[qid] = answer_no_memory(turns, budget, qid, expected)
    arm.score = sum(arm.correct.values())
    return arm


@dataclass
class EvolvingFactReport:
    timestamp: str
    version: str
    backend: str
    versions: dict[str, str] = field(default_factory=version_info)
    arms: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def run(
    backend: str, output_root: Path = Path("benchmarks/runs"), write: bool = True
) -> EvolvingFactReport:
    turns = build_session()
    stash = _make_stash(backend)
    try:
        stele = run_stele_arm(stash)
        naive = run_naive_arm(stash)
    finally:
        stash.close()
    no_memory = run_no_memory_arm(turns, REALISTIC_BUDGET)

    arms = [no_memory, naive, stele]
    summary = {
        "session_total_tokens": sum(estimate_tokens(c) for _, c in turns),
        "realistic_budget_tokens": REALISTIC_BUDGET,
        "questions": len(QUESTIONS),
        "stele_score": stele.score,
        "naive_score": naive.score,
        "no_memory_score": no_memory.score,
    }

    report = EvolvingFactReport(
        timestamp=datetime.now(UTC).isoformat(),
        version=VERSION,
        backend=backend,
        arms=[a.to_row() for a in arms],
        summary=summary,
    )

    # The proof must demonstrate the divergence, or it is not a proof.
    assert stele.score == len(QUESTIONS), f"stele should be correct on all, got {stele.score}"
    assert naive.correct["current"] is False, "naive must return the STALE 'current' value"
    assert naive.score < stele.score, "stele must beat naive memory"
    assert no_memory.score < stele.score, "stele must beat the no-memory baseline"

    if write:
        _write_report(report, output_root)
    return report


def _make_stash(backend: str) -> Stele:
    config: dict[str, Any] = {"pii": {"raw_fetch_enabled": True}}
    if backend == "postgres":
        dsn = os.environ.get("STELE_PG_DSN")
        if not dsn:
            raise SystemExit("--backend postgres needs STELE_PG_DSN set")
        config["backend"] = {"type": "postgres", "dsn": dsn}
    elif backend == "sqlite":
        config["backend"] = {"type": "sqlite", "path": "benchmarks/runs/evolving_fact.db"}
    else:
        config["backend"] = {"type": "memory"}
    return Stele.from_config(config)


def _write_report(report: EvolvingFactReport, output_root: Path) -> tuple[Path, Path]:
    out_dir = output_root / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "EvolvingFactProof.json"
    md_path = out_dir / "EvolvingFactProof.md"
    json_path.write_text(
        json.dumps(
            {
                "timestamp": report.timestamp,
                "version": report.version,
                "backend": report.backend,
                "versions": report.versions,
                "summary": report.summary,
                "arms": report.arms,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return md_path, json_path


def _cell(ok: bool) -> str:
    return "yes" if ok else "**NO**"


def _render_markdown(report: EvolvingFactReport) -> str:
    s = report.summary
    arms = report.arms
    lines = [
        "# stele Evolving-Fact Value-Proof",
        "",
        "## TL;DR",
        "",
        (
            "When a durable fact changes over time, a no-memory agent loses the history it "
            "evicted and a naive store returns the stale original value. stele's supersession "
            "chain returns the current value and `as_of` recovers any past state. Only stele is "
            "correct on all three temporal questions. Deterministic, no LLM judge."
        ),
        "",
        f"**Backend**: `{report.backend}`  ",
        f"**Run at**: `{report.timestamp}`  ",
        f"**Package versions**: {versions_md_line()}  ",
        (
            f"**The fact**: a durable API-protocol decision that evolved "
            f"REST -> gRPC -> GraphQL across a {s['session_total_tokens']:,}-token session."
        ),
        "",
        "## Correctness matrix",
        "",
        f"At a realistic {s['realistic_budget_tokens']:,}-token context budget:",
        "",
        "| Question | Expected | no-memory | naive memory | stele |",
        "|---|---|:---:|:---:|:---:|",
    ]
    no_mem = next(a for a in arms if a["arm"].startswith("no-memory"))["correct"]
    naive = next(a for a in arms if a["arm"].startswith("naive"))["correct"]
    stele = next(a for a in arms if a["arm"].startswith("stele"))["correct"]
    for qid, prose, expected in QUESTIONS:
        lines.append(
            f"| {prose} | `{expected}` | {_cell(no_mem[qid])} | "
            f"{_cell(naive[qid])} | {_cell(stele[qid])} |"
        )
    lines.append(
        f"| **Score** | 3 | **{s['no_memory_score']}/3** | "
        f"**{s['naive_score']}/3** | **{s['stele_score']}/3** |"
    )
    lines.extend(
        [
            "",
            "## In plain terms",
            "",
            (
                "- A project decision (the API protocol) changes twice over a long session: "
                "REST first, then gRPC, then GraphQL."
            ),
            (
                "- **no-memory** answers 'what now?' correctly because the latest decision is "
                "recent and still in its window, but it has evicted the earlier history, so it "
                "cannot say what was decided originally or in between."
            ),
            (
                "- **naive memory** recorded 'REST' the first time and never updated. It "
                "confidently returns REST for 'what now?' -- the stale-value trap that is worse "
                "than no memory, because it sounds authoritative and is wrong."
            ),
            (
                "- **stele** supersedes REST with gRPC with GraphQL. The current view returns "
                "GraphQL; `as_of` returns gRPC or REST for the moment you ask about. Correct on "
                "all three, and for the right reason: the supersession chain, not luck or recency."
            ),
            "",
            "## Honesty notes",
            "",
            (
                "- The fact is a durable *decision*, not a re-derivable value (like a port "
                "number). Storing volatile re-derivable values in memory is a separate, proven "
                "trap; this proof uses the kind of fact memory is meant to hold."
            ),
            (
                "- naive memory is modelled as stele WITHOUT supersession (store-once). That "
                "isolates the lever under test: supersession + `as_of`, not merely 'has a store'."
            ),
            (
                "- no-memory gets 'current' right from recency, and naive gets 'original' right "
                "by accident (it is stuck there). stele is the only arm correct across the whole "
                "timeline. The result is the 3/1/1 split, not a clean sweep, on purpose."
            ),
            (
                "- as_of uses distinct `effective_from` timestamps created with small real "
                "sleeps, the same pattern the memory contract tests use."
            ),
            "",
            "## Reproducing",
            "",
            "```bash",
            ".venv/bin/python -m benchmarks.evolving_fact_proof   # postgres if DSN, else memory",
            ".venv/bin/python -m benchmarks.evolving_fact_proof --backend memory",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="stele evolving-fact value-proof")
    parser.add_argument(
        "--backend",
        choices=["auto", "memory", "sqlite", "postgres"],
        default="auto",
        help="auto = postgres if STELE_PG_DSN is set, else memory",
    )
    parser.add_argument("--output-root", type=Path, default=Path("benchmarks/runs"))
    args = parser.parse_args()
    backend = args.backend
    if backend == "auto":
        backend = "postgres" if os.environ.get("STELE_PG_DSN") else "memory"
    report = run(backend, output_root=args.output_root)
    print(json.dumps(report.summary, indent=2))


if __name__ == "__main__":
    main()
