"""In-repo memory value-proof for stele.

The showcase benchmark measures payload reduction but says so itself: it "does
not measure answer accuracy yet" and "broad quality claims require a separate
direct-context baseline comparison." This script is that comparison.

It answers the one question that justifies the whole memory thesis: does keeping
exact bytes off-prompt and recalling them on demand change an *outcome* an agent
would otherwise get wrong? No LLM judge, fully deterministic.

The scenario: a single agent session runs many tools. One early, large tool
output hides a needle fact (a production database port). Later outputs push it
out of any realistic context window. At the end the agent must answer using only
what it still has.

- **No-memory baseline:** keeps raw tool outputs in a rolling context window
  (FIFO eviction once the token budget is exceeded, the normal agent behaviour).
  When the needle is evicted, the answer is gone unless the agent re-runs the
  tool and re-pays the full payload.
- **stele:** routes each oversized output through `stash_tool_result` (exact
  bytes stored off-prompt, a compact summary left in context), then recalls the
  needle with `query` + a bounded `fetch` at question time.

We sweep the context budget so the result is a regime, not a cherry-picked
point. stele decouples correctness from the budget; the baseline does not.

Run:
    .venv/bin/python -m benchmarks.memory_value_proof   # postgres if DSN set, else memory
    .venv/bin/python -m benchmarks.memory_value_proof --backend memory
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks._versions import version_info, versions_md_line
from benchmarks.showcase import (
    code_diff,
    json_api_response,
    legal_contract,
    log_buffer,
    sql_rows,
)
from stele import Stele
from stele.core.artifact import estimate_tokens
from stele.interception.wrapper import stash_tool_result

VERSION = "0.1.0"
NAMESPACE = "value_proof"

# Context budgets in tokens. Spans "tiny agent scratch" to "whole 128k window".
BUDGETS = [2_000, 8_000, 32_000, 131_072]

NEEDLE_ANSWER = "55432"
NEEDLE_LINE = (
    "2026-04-13T10:00:00Z [NOTE] deploy config: the production database listens "
    "on port 55432 in region us-west-2; rotate secrets before 2026-09-01."
)
QUESTION = "What port does the production database listen on?"
RECALL_QUERY = "production database port deploy config"


def build_session() -> tuple[list[tuple[str, str]], int]:
    """A realistic mixed tool session. Returns (turns, needle_turn_index).

    The needle is hidden inside an early log-tail output (turn 1); everything
    after it is unrelated bulk that evicts it under any realistic budget.
    """
    turns: list[tuple[str, str]] = [("query_db", sql_rows(300))]
    turns.append(("tail_logs", log_buffer(400) + "\n" + NEEDLE_LINE))
    needle_idx = 1
    gens = [legal_contract, json_api_response, code_diff, sql_rows, log_buffer]
    tools = ["read_contract", "fetch_openapi", "git_diff", "query_db", "tail_logs"]
    for i in range(10):
        turns.append((tools[i % 5], gens[i % 5]()))
    return turns, needle_idx


def _bounded_window(content: str, answer: str, radius: int = 240) -> str:
    """The slice an agent would read around a hit: answer +/- a little context."""
    idx = content.find(answer)
    if idx < 0:
        return ""
    return content[max(0, idx - radius) : idx + len(answer) + radius]


@dataclass
class StrategyResult:
    budget_tokens: int
    strategy: str
    resident_tokens: int  # tokens occupying context at question time
    acquisition_tokens: int  # extra tokens spent to recover the answer
    total_tokens: int
    correct_without_refetch: bool  # did the agent still have the fact, no tool re-run?
    recovered_via: str

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def run_baseline(turns: list[tuple[str, str]], needle_idx: int, budget: int) -> StrategyResult:
    """No-memory agent: raw outputs in a rolling context window of `budget` tokens.

    Fills newest-first with whole messages, truncating the boundary message to
    its most-recent bytes (how a real context window behaves: the latest output
    is kept even if it alone exceeds the budget, older content scrolls off).
    """
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
    resident_text = "\n".join(reversed(kept))
    total = estimate_tokens(resident_text)
    if NEEDLE_ANSWER in resident_text:
        return StrategyResult(budget, "no-memory baseline", total, 0, total, True, "in-context")
    # Evicted. The honest agent re-runs the tool that produced it, re-paying the
    # full payload. It then gets the right answer, but at full re-fetch cost.
    refetch = estimate_tokens(turns[needle_idx][1])
    return StrategyResult(
        budget, "no-memory baseline", total, refetch, total + refetch, False, "forced tool re-run"
    )


def run_stele(stash: Stele, turns: list[tuple[str, str]]) -> StrategyResult:
    """stele agent. Budget-independent: it never relies on the context window.

    Returns one StrategyResult (budget recorded as 0 = "any"). Ingests once.
    """
    summaries: list[str] = []
    for tool, content in turns:
        replacement = str(
            stash_tool_result(content, stash=stash, namespace=NAMESPACE, tool_name=tool)
        )
        summaries.append(replacement)
    resident = sum(estimate_tokens(s) for s in summaries)

    hits = stash.query(NAMESPACE, RECALL_QUERY, limit=5)
    recall_text = "\n".join(hit.text for hit in hits)
    acquisition = sum(estimate_tokens(hit.text) for hit in hits)
    recovered = "recall (search snippet)"
    correct = NEEDLE_ANSWER in recall_text

    if not correct:
        # Snippet didn't carry the answer; do the bounded fetch an agent would.
        for hit in hits:
            content = str(stash.fetch(hit.reference, raw=True).content)
            if NEEDLE_ANSWER in content:
                snippet = _bounded_window(content, NEEDLE_ANSWER)
                acquisition += estimate_tokens(snippet)
                correct = True
                recovered = "recall (search + bounded fetch)"
                break

    return StrategyResult(
        0, "stele", resident, acquisition, resident + acquisition, correct, recovered
    )


@dataclass
class ValueProofReport:
    timestamp: str
    version: str
    backend: str
    question: str
    needle_answer: str
    versions: dict[str, str] = field(default_factory=version_info)
    stele_row: dict[str, Any] = field(default_factory=dict)
    baseline_rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def run(
    backend: str, output_root: Path = Path("benchmarks/runs"), write: bool = True
) -> ValueProofReport:
    turns, needle_idx = build_session()
    stash = _make_stash(backend)
    try:
        stele = run_stele(stash, turns)
    finally:
        stash.close()
    baselines = [run_baseline(turns, needle_idx, b) for b in BUDGETS]

    # Realistic operating point: an 8k working budget (the second sweep value).
    realistic = next(b for b in baselines if b.budget_tokens == 8_000)
    summary = {
        "session_turns": len(turns),
        "session_total_tokens": sum(estimate_tokens(c) for _, c in turns),
        "budgets_swept": BUDGETS,
        "stele_correct_all_budgets": stele.correct_without_refetch,
        "baseline_correct_count": sum(b.correct_without_refetch for b in baselines),
        "baseline_total": len(baselines),
        "realistic_budget_tokens": realistic.budget_tokens,
        "realistic_baseline_correct": realistic.correct_without_refetch,
        "realistic_resident_reduction_pct": _pct(realistic.resident_tokens, stele.resident_tokens),
        "realistic_total_reduction_pct": _pct(realistic.total_tokens, stele.total_tokens),
    }

    report = ValueProofReport(
        timestamp=datetime.now(UTC).isoformat(),
        version=VERSION,
        backend=backend,
        question=QUESTION,
        needle_answer=NEEDLE_ANSWER,
        stele_row=stele.to_row(),
        baseline_rows=[b.to_row() for b in baselines],
        summary=summary,
    )

    # The proof must actually demonstrate divergence, or it is not a proof.
    assert stele.correct_without_refetch, "stele failed to recall the needle"
    assert not realistic.correct_without_refetch, (
        "baseline kept the needle at a realistic budget; raise session size or lower budget"
    )

    if write:
        _write_report(report, output_root)
    return report


def _pct(baseline: int, stele: int) -> float:
    return round(100 * (1 - stele / baseline), 1) if baseline else 0.0


def _make_stash(backend: str) -> Stele:
    config: dict[str, Any] = {
        "pii": {"raw_fetch_enabled": True},
        "interception": {"min_chars": 1000, "min_estimated_tokens": 250},
        "summary": {"max_chars": 900},
    }
    if backend == "postgres":
        dsn = os.environ.get("STELE_PG_DSN")
        if not dsn:
            raise SystemExit("--backend postgres needs STELE_PG_DSN set")
        config["backend"] = {"type": "postgres", "dsn": dsn}
    elif backend == "sqlite":
        config["backend"] = {"type": "sqlite", "path": "benchmarks/runs/value_proof.db"}
    else:
        config["backend"] = {"type": "memory"}
    return Stele.from_config(config)


def _write_report(report: ValueProofReport, output_root: Path) -> tuple[Path, Path]:
    out_dir = output_root / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "MemoryValueProof.json"
    md_path = out_dir / "MemoryValueProof.md"
    json_path.write_text(
        json.dumps(
            {
                "timestamp": report.timestamp,
                "version": report.version,
                "backend": report.backend,
                "versions": report.versions,
                "question": report.question,
                "needle_answer": report.needle_answer,
                "summary": report.summary,
                "stele": report.stele_row,
                "baselines": report.baseline_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return md_path, json_path


def _render_markdown(report: ValueProofReport) -> str:
    s = report.summary
    stele = report.stele_row
    lines = [
        "# stele Memory Value-Proof",
        "",
        "## TL;DR",
        "",
        (
            "A no-memory agent loses a fact buried in an early tool output once the "
            "context window fills; stele recalls it correctly at a fraction of the "
            "tokens, at every budget. Every number is printed from a live run of "
            "`benchmarks.memory_value_proof` (deterministic, no LLM judge)."
        ),
        "",
        f"**Backend**: `{report.backend}`  ",
        f"**Run at**: `{report.timestamp}`  ",
        f"**Package versions**: {versions_md_line()}  ",
        f"**Question asked at end of session**: {report.question}  ",
        f"**Correct answer (the needle)**: `{report.needle_answer}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Session turns / total tokens | {s['session_turns']} / {s['session_total_tokens']:,} |",
        f"| Budgets swept (tokens) | {', '.join(f'{b:,}' for b in s['budgets_swept'])} |",
        f"| stele correct at all budgets | **{s['stele_correct_all_budgets']}** |",
        (
            f"| Baseline correct (no tool re-run) | "
            f"{s['baseline_correct_count']} / {s['baseline_total']} budgets |"
        ),
        (
            f"| At a realistic {s['realistic_budget_tokens']:,}-token budget, baseline correct | "
            f"**{s['realistic_baseline_correct']}** |"
        ),
        (
            f"| stele resident-token reduction (realistic budget) | "
            f"**{s['realistic_resident_reduction_pct']}%** |"
        ),
        (
            f"| stele total-token reduction (realistic budget) | "
            f"**{s['realistic_total_reduction_pct']}%** |"
        ),
        "",
        "## Per-budget detail",
        "",
        (
            "| Budget (tok) | Strategy | Resident | Acquire | Total "
            "| Correct, no re-run | Recovered via |"
        ),
        "|---:|---|---:|---:|---:|:---:|---|",
    ]
    for b in report.baseline_rows:
        lines.append(
            f"| {b['budget_tokens']:,} | {b['strategy']} | {b['resident_tokens']:,} | "
            f"{b['acquisition_tokens']:,} | {b['total_tokens']:,} | "
            f"{'yes' if b['correct_without_refetch'] else 'NO'} | {b['recovered_via']} |"
        )
    lines.append(
        f"| any | **{stele['strategy']}** | {stele['resident_tokens']:,} | "
        f"{stele['acquisition_tokens']:,} | {stele['total_tokens']:,} | "
        f"{'yes' if stele['correct_without_refetch'] else 'NO'} | {stele['recovered_via']} |"
    )
    lines.extend(
        [
            "",
            "## In plain terms",
            "",
            (
                "- The agent reads a big log early on. Buried in it is the one fact it "
                "will be asked about later (a database port)."
            ),
            (
                "- The no-memory agent keeps raw outputs in its context window. Once the "
                "window fills with later work, that early log is evicted and the fact is "
                "gone. To answer, it must re-run the tool and re-read the whole payload."
            ),
            (
                "- stele stashed the exact bytes off-prompt and kept only a small summary "
                "in context. When asked, it searches its store and reads a bounded slice "
                "back. It answers correctly no matter how small the context budget is."
            ),
            (
                "- This is the off-prompt-memory lever, not a model-quality trick: the win "
                "is that correctness stops depending on what still fits in the window."
            ),
            "",
            "## Honesty notes",
            "",
            (
                "- The baseline is given the benefit of the doubt: when it loses the fact "
                "it is allowed to re-run the exact tool (it is not scored as a permanent "
                "failure). stele still wins on tokens because the re-run re-pays the full "
                "payload while stele pays a bounded recall. The `Correct, no re-run` "
                "column is the honest test of whether memory was retained."
            ),
            (
                "- Token counts use stele's own `estimate_tokens` (bytes / 4), the same "
                "estimator its interception thresholds use. Deterministic across runs."
            ),
            (
                "- This proves the retention/recall lever. It does not claim answer-quality "
                "gains on tasks where the fact already fits in context."
            ),
            "",
            "## Reproducing",
            "",
            "```bash",
            ".venv/bin/python -m benchmarks.memory_value_proof  # postgres if DSN, else memory",
            ".venv/bin/python -m benchmarks.memory_value_proof --backend memory",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="stele in-repo memory value-proof")
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
