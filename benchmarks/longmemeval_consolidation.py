"""LongMemEval knowledge-update consolidation benchmark.

Measures whether stele's evolving-fact consolidation improves answer accuracy
on LongMemEval-S knowledge-update questions.

For each question (filtered to question_type == "knowledge-update", skipping
_abs variants), two arms are run:

  ON  — ExtractionConfig.consolidation_enabled = True  (default)
  OFF — ExtractionConfig.consolidation_enabled = False (pre-consolidation baseline)

Each arm gets a FRESH isolated SQLite Stele instance (no shared state). Every
session in haystack_sessions is ingested via Stele.extract.from_session with
the injected LLM callable (Qwen). The question is then answered by searching
the memory layer and calling the answerer (Qwen), then judged vs the gold
answer (Gemma).

Endpoints:
  answerer/extractor (Qwen): http://192.168.1.193:8000/v1
    model: Intel/Qwen3-Coder-Next-int4-AutoRound
  judge (Gemma): http://192.168.1.133:8000/v1
    model: cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit

Output: benchmarks/runs/<date>/longmemeval-consolidation-<timestamp>.json + .md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import JudgeVerdict, OpenAICompatAnswerer
from benchmarks.external.loaders import DatasetUnavailable, iter_longmemeval_s
from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

# --------------------------------------------------------------------------- #
# Defaults                                                                     #
# --------------------------------------------------------------------------- #

DEFAULT_ANSWER_URL = "http://192.168.1.193:8000/v1"
DEFAULT_ANSWER_MODEL = "Intel/Qwen3-Coder-Next-int4-AutoRound"
DEFAULT_JUDGE_URL = "http://192.168.1.133:8000/v1"
DEFAULT_JUDGE_MODEL = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"

MEMORY_SEARCH_LIMIT = 20
MAX_CONTEXT_CHARS = 12_000


# --------------------------------------------------------------------------- #
# Data classes                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class ArmResult:
    question_id: str
    arm: str  # "on" | "off"
    accepted_count: int
    superseded_count: int
    context_chars: int
    answer: str
    correct: bool
    sufficient: bool
    confidence: float
    rationale: str
    latency_ms: float


@dataclass
class RecordResult:
    question_id: str
    question: str
    gold_answer: str
    num_sessions: int
    on: ArmResult | None
    off: ArmResult | None


# --------------------------------------------------------------------------- #
# LLM callable builder                                                         #
# --------------------------------------------------------------------------- #

def _make_llm(answerer: OpenAICompatAnswerer, model: str) -> Any:
    """Build a Callable[[str], str] over OpenAICompatAnswerer._chat."""
    def llm(prompt: str) -> str:
        return str(
            answerer._chat(
                model=model,
                json_mode=False,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
        ).strip()
    return llm


# --------------------------------------------------------------------------- #
# Per-arm runner                                                               #
# --------------------------------------------------------------------------- #

def _run_arm(
    *,
    question_id: str,
    question: str,
    gold_answer: str,
    haystack_sessions: list[list[dict[str, str]]],
    arm: str,
    consolidation_enabled: bool,
    tmpdir: Path,
    answerer: OpenAICompatAnswerer,
    llm: Any,
) -> ArmResult:
    db_path = str(tmpdir / f"{question_id}_{arm}.db")
    config = StashConfig.model_validate({
        "backend": {"type": "sqlite", "path": db_path},
        "extraction": {
            "enabled": True,
            "consolidation_enabled": consolidation_enabled,
        },
        "indexing": {"mode": "skip", "provider": "none"},
    })
    stele = Stele(config=config)
    t0 = time.perf_counter()
    try:
        scope = MemoryScope(namespace=question_id)
        accepted_total = 0

        for sess_idx, session_turns in enumerate(haystack_sessions):
            if not session_turns:
                continue
            sess_scope = MemoryScope(
                namespace=question_id,
                session_id=str(sess_idx),
            )
            try:
                report = stele.extract.from_session(
                    transcript=session_turns,
                    scope=sess_scope,
                    llm=llm,
                    max_windows=3,
                )
                accepted_total += report.stats.accepted_count
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  [{arm}] session {sess_idx} extract failed: {exc!r:.80}",
                    file=sys.stderr,
                    flush=True,
                )

        # Count superseded memories to gauge consolidation activity
        all_mems = stele.memory.list(scope, limit=5000)
        superseded_count = sum(1 for m in all_mems if m.status == "superseded")
        active_mems = [m for m in all_mems if m.status == "active"]

        # Assemble context from active memory search
        hits = stele.memory.search_with_score(question, scope, limit=MEMORY_SEARCH_LIMIT)
        if hits:
            parts = [h.record.text for h in hits]
        else:
            parts = [m.text for m in active_mems[:MEMORY_SEARCH_LIMIT]]
        context = "\n\n".join(parts)[:MAX_CONTEXT_CHARS]
        context_chars = len(context)

        # Answer the question
        answer, _ = answerer.answer(
            question=question,
            context=context,
            expected_answer=gold_answer,
        )

        # Judge vs gold
        verdict: JudgeVerdict = answerer.judge(
            question=question,
            expected_answer=gold_answer,
            answer=answer,
            context=context,
        )

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return ArmResult(
            question_id=question_id,
            arm=arm,
            accepted_count=accepted_total,
            superseded_count=superseded_count,
            context_chars=context_chars,
            answer=answer,
            correct=verdict.correct,
            sufficient=verdict.sufficient,
            confidence=round(verdict.confidence, 4),
            rationale=verdict.rationale,
            latency_ms=latency_ms,
        )
    finally:
        stele.close()


# --------------------------------------------------------------------------- #
# Main runner                                                                  #
# --------------------------------------------------------------------------- #

def run_consolidation_benchmark(
    *,
    limit: int,
    arm: str,
    answer_url: str,
    answer_model: str,
    judge_url: str,
    judge_model: str,
    api_key: str,
    output_root: Path,
) -> dict[str, Any]:
    answerer = OpenAICompatAnswerer(
        answer_model=answer_model,
        judge_model=judge_model,
        base_url=answer_url,
        api_key=api_key,
        judge_base_url=judge_url,
        judge_api_key=api_key,
    )
    llm = _make_llm(answerer, answer_model)

    arms_to_run = {"on", "off"} if arm == "both" else {arm}

    records: list[RecordResult] = []
    raw_rows: list[dict[str, Any]] = []
    total_seen = 0

    with tempfile.TemporaryDirectory(prefix="stele_lme_cons_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        for rec in iter_longmemeval_s(10_000):
            qtype = rec.get("question_type", "")
            qid = str(rec.get("question_id", ""))
            if qtype != "knowledge-update" or qid.endswith("_abs"):
                continue
            question = str(rec.get("question", "")).strip()
            gold = str(rec.get("answer", "")).strip()
            sessions = rec.get("haystack_sessions", []) or []
            if not question or not gold:
                continue

            total_seen += 1
            if total_seen > limit:
                break

            print(
                f"\n[{total_seen}/{limit}] {qid}  sessions={len(sessions)}",
                flush=True,
            )

            on_result: ArmResult | None = None
            off_result: ArmResult | None = None

            if "on" in arms_to_run:
                print("  arm=ON  ...", flush=True)
                on_result = _run_arm(
                    question_id=qid,
                    question=question,
                    gold_answer=gold,
                    haystack_sessions=sessions,
                    arm="on",
                    consolidation_enabled=True,
                    tmpdir=tmpdir,
                    answerer=answerer,
                    llm=llm,
                )
                print(
                    f"  arm=ON  accepted={on_result.accepted_count} "
                    f"superseded={on_result.superseded_count} "
                    f"correct={on_result.correct} "
                    f"lat={on_result.latency_ms:.0f}ms",
                    flush=True,
                )

            if "off" in arms_to_run:
                print("  arm=OFF ...", flush=True)
                off_result = _run_arm(
                    question_id=qid,
                    question=question,
                    gold_answer=gold,
                    haystack_sessions=sessions,
                    arm="off",
                    consolidation_enabled=False,
                    tmpdir=tmpdir,
                    answerer=answerer,
                    llm=llm,
                )
                print(
                    f"  arm=OFF accepted={off_result.accepted_count} "
                    f"superseded={off_result.superseded_count} "
                    f"correct={off_result.correct} "
                    f"lat={off_result.latency_ms:.0f}ms",
                    flush=True,
                )

            rr = RecordResult(
                question_id=qid,
                question=question,
                gold_answer=gold,
                num_sessions=len(sessions),
                on=on_result,
                off=off_result,
            )
            records.append(rr)
            if on_result:
                raw_rows.append(asdict(on_result))
            if off_result:
                raw_rows.append(asdict(off_result))

    # Summarize
    on_rows = [r for r in raw_rows if r["arm"] == "on"]
    off_rows = [r for r in raw_rows if r["arm"] == "off"]

    def _acc(rows: list[dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        return round(sum(1 for r in rows if r["correct"]) / len(rows), 4)

    def _mean_float(rows: list[dict[str, Any]], key: str) -> float:
        if not rows:
            return 0.0
        return round(sum(r[key] for r in rows) / len(rows), 2)

    summary = {
        "questions_run": len(records),
        "arm": arm,
        "on_accuracy": _acc(on_rows),
        "off_accuracy": _acc(off_rows),
        "on_mean_accepted": _mean_float(on_rows, "accepted_count"),
        "off_mean_accepted": _mean_float(off_rows, "accepted_count"),
        "on_mean_superseded": _mean_float(on_rows, "superseded_count"),
        "off_mean_superseded": _mean_float(off_rows, "superseded_count"),
        "on_mean_latency_ms": _mean_float(on_rows, "latency_ms"),
        "off_mean_latency_ms": _mean_float(off_rows, "latency_ms"),
    }

    run_dir = output_root / datetime.now(UTC).strftime("%Y-%m-%d")
    run_dir.mkdir(parents=True, exist_ok=True)
    slug = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = run_dir / f"longmemeval-consolidation-{slug}"

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "benchmark": "longmemeval-consolidation",
        "config": {
            "limit": limit,
            "arm": arm,
            "answer_model": answer_model,
            "answer_url": answer_url,
            "judge_model": judge_model,
            "judge_url": judge_url,
        },
        "summary": summary,
        "rows": raw_rows,
    }
    base.with_suffix(".json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    base.with_suffix(".md").write_text(_markdown(report, records), encoding="utf-8")
    print(f"\nReport: {base}.json / .md", flush=True)
    return report


# --------------------------------------------------------------------------- #
# Markdown summary                                                             #
# --------------------------------------------------------------------------- #

def _markdown(report: dict[str, Any], records: list[RecordResult]) -> str:
    s = report["summary"]
    cfg = report["config"]
    lines = [
        "# LongMemEval Consolidation Benchmark",
        "",
        f"**Questions run**: {s['questions_run']}  ",
        f"**Arm**: `{cfg['arm']}`  ",
        f"**Answer model**: `{cfg['answer_model']}` @ `{cfg['answer_url']}`  ",
        f"**Judge model**: `{cfg['judge_model']}` @ `{cfg['judge_url']}`",
        "",
        "## Summary",
        "",
        "| Arm | Accuracy | Mean Accepted | Mean Superseded | Mean Latency ms |",
        "| --- | ---: | ---: | ---: | ---: |",
        (
            f"| ON  | {s['on_accuracy']} | {s['on_mean_accepted']}"
            f" | {s['on_mean_superseded']} | {s['on_mean_latency_ms']} |"
        ),
        (
            f"| OFF | {s['off_accuracy']} | {s['off_mean_accepted']}"
            f" | {s['off_mean_superseded']} | {s['off_mean_latency_ms']} |"
        ),
        "",
        "## Per-record",
        "",
        "| QID | Sessions | ON correct | OFF correct | ON superseded |",
        "| --- | ---: | :---: | :---: | ---: |",
    ]
    for rr in records:
        on_c = ("Y" if rr.on.correct else "N") if rr.on else "-"
        off_c = ("Y" if rr.off.correct else "N") if rr.off else "-"
        on_sup = str(rr.on.superseded_count) if rr.on else "-"
        lines.append(
            f"| {rr.question_id} | {rr.num_sessions} | {on_c} | {off_c} | {on_sup} |"
        )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(
        description="LongMemEval knowledge-update consolidation ON vs OFF benchmark"
    )
    ap.add_argument(
        "--limit", type=int, default=72,
        help="Number of knowledge-update questions to run (default: all 72)",
    )
    ap.add_argument(
        "--arm", choices=["both", "on", "off"], default="both",
        help="Which arm(s) to run",
    )
    ap.add_argument(
        "--answer-url",
        default=os.environ.get("LME_ANSWER_URL", DEFAULT_ANSWER_URL),
        help="OpenAI-compatible base URL for the answerer/extractor",
    )
    ap.add_argument(
        "--answer-model",
        default=os.environ.get("LME_ANSWER_MODEL", DEFAULT_ANSWER_MODEL),
        help="Model for answering and extraction",
    )
    ap.add_argument(
        "--judge-url",
        default=os.environ.get("LME_JUDGE_URL", DEFAULT_JUDGE_URL),
        help="OpenAI-compatible base URL for the judge",
    )
    ap.add_argument(
        "--judge-model",
        default=os.environ.get("LME_JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
        help="Model for judging",
    )
    ap.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY", "local"),
        help="API key (same for both endpoints unless overridden via env)",
    )
    ap.add_argument(
        "--output-root", type=Path, default=Path("benchmarks/runs"),
        help="Root directory for run output",
    )
    args = ap.parse_args()

    try:
        report = run_consolidation_benchmark(
            limit=args.limit,
            arm=args.arm,
            answer_url=args.answer_url,
            answer_model=args.answer_model,
            judge_url=args.judge_url,
            judge_model=args.judge_model,
            api_key=args.api_key,
            output_root=args.output_root,
        )
    except DatasetUnavailable as exc:
        print(f"DATASET UNAVAILABLE: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
