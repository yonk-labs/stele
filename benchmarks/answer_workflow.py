"""Answer workflow benchmark with token, round-trip, and judge accounting.

This benchmark asks a different question than the fast showcase:

What is the cheapest retrieval path that gives an LLM enough context to answer
correctly?

It supports two judge modes:

- deterministic: CI-safe containment judge for regression only.
- openai: answer generation plus JSON LLM judge through an OpenAI-compatible server.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from benchmarks.longrun import BenchmarkScenario, build_scenarios
from stele import Stele
from stele.core.artifact import estimate_tokens
from stele.interception.wrapper import stash_tool_result

Strategy = Literal["summary_only", "summary_then_search", "search_first", "adaptive", "raw_fetch"]
JudgeMode = Literal["deterministic", "openai"]


@dataclass(frozen=True)
class AnswerAttempt:
    answer: str
    prompt_tokens: int
    completion_tokens: int
    llm_round_trips: int
    stash_search_calls: int
    stash_fetch_calls: int
    context_bytes: int
    path: str


@dataclass(frozen=True)
class WorkflowResult:
    scenario: str
    kind: str
    strategy: str
    judge_mode: str
    correct: bool
    sufficient: bool
    confidence: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    llm_round_trips: int
    stash_search_calls: int
    stash_fetch_calls: int
    context_bytes: int
    latency_ms: float
    answer: str
    rationale: str


class JudgeVerdict(BaseModel):
    correct: bool
    sufficient: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class BatchJudgeItem(BaseModel):
    index: int
    correct: bool
    sufficient: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class BatchJudgeVerdicts(BaseModel):
    verdicts: list[BatchJudgeItem]


@dataclass(frozen=True)
class PendingAttempt:
    scenario: BenchmarkScenario
    strategy: Strategy
    attempt: AnswerAttempt
    latency_ms: float


class Answerer(Protocol):
    mode: str

    def answer(
        self,
        *,
        question: str,
        context: str,
        expected_answer: str | None,
    ) -> tuple[str, int]: ...

    def judge(
        self,
        *,
        question: str,
        expected_answer: str | None,
        answer: str,
        context: str,
    ) -> JudgeVerdict: ...

    def judge_batch(self, pending: list[PendingAttempt]) -> list[JudgeVerdict]: ...


class DeterministicAnswerer:
    mode = "deterministic"

    def answer(
        self,
        *,
        question: str,
        context: str,
        expected_answer: str | None,
    ) -> tuple[str, int]:
        del question
        if expected_answer is None:
            return ("I do not have enough information to answer.", 11)
        if expected_answer.lower() in context.lower():
            return (expected_answer, estimate_tokens(expected_answer))
        return ("I do not have enough information to answer.", 11)

    def judge(
        self,
        *,
        question: str,
        expected_answer: str | None,
        answer: str,
        context: str,
    ) -> JudgeVerdict:
        del question
        if expected_answer is None:
            correct = "not have enough information" in answer.lower()
            return JudgeVerdict(
                correct=correct,
                sufficient=correct,
                confidence=1.0 if correct else 0.0,
                rationale="Correct abstention" if correct else "Failed to abstain",
            )
        correct = expected_answer.lower() in answer.lower()
        sufficient = expected_answer.lower() in context.lower()
        return JudgeVerdict(
            correct=correct,
            sufficient=sufficient,
            confidence=1.0 if correct else 0.0,
            rationale="Expected answer matched" if correct else "Expected answer missing",
        )

    def judge_batch(self, pending: list[PendingAttempt]) -> list[JudgeVerdict]:
        return [
            self.judge(
                question=item.scenario.query,
                expected_answer=item.scenario.expected_answer,
                answer=item.attempt.answer,
                context=item.attempt.path,
            )
            for item in pending
        ]


class OpenAICompatAnswerer:
    mode = "openai"

    def __init__(
        self,
        *,
        answer_model: str,
        judge_model: str,
        base_url: str,
        api_key: str,
    ) -> None:
        self.answer_model = answer_model
        self.judge_model = judge_model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def answer(
        self,
        *,
        question: str,
        context: str,
        expected_answer: str | None,
    ) -> tuple[str, int]:
        del expected_answer
        content = self._chat(
            model=self.answer_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer using only the provided context. If the context is insufficient, "
                        "say exactly: I do not have enough information to answer."
                    ),
                },
                {"role": "user", "content": f"Question:\n{question}\n\nContext:\n{context}"},
            ],
        )
        return content, estimate_tokens(content)

    def judge(
        self,
        *,
        question: str,
        expected_answer: str | None,
        answer: str,
        context: str,
    ) -> JudgeVerdict:
        expected = expected_answer or "The correct behavior is to abstain."
        content = self._chat(
            model=self.judge_model,
            json_mode=True,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict benchmark judge. Evaluate whether the answer is "
                        "correct for the question and whether the provided context was "
                        "sufficient. Return JSON only with keys: correct, sufficient, "
                        "confidence, rationale."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\nExpected answer or behavior:\n{expected}\n\n"
                        f"Candidate answer:\n{answer}\n\nContext used:\n{context}"
                    ),
                },
            ],
        )
        return JudgeVerdict.model_validate(_extract_json(content))

    def judge_batch(self, pending: list[PendingAttempt]) -> list[JudgeVerdict]:
        payload = [
            {
                "index": index,
                "question": item.scenario.query,
                "expected_answer_or_behavior": item.scenario.expected_answer
                or "The correct behavior is to abstain.",
                "candidate_answer": item.attempt.answer,
                "context_used": item.attempt.path,
            }
            for index, item in enumerate(pending)
        ]
        content = self._chat(
            model=self.judge_model,
            json_mode=True,
            max_tokens=4096,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict benchmark judge. For each item, evaluate whether "
                        "the answer is correct and whether the context was sufficient. Return "
                        "JSON only: {\"verdicts\":[{\"index\":0,\"correct\":true,"
                        "\"sufficient\":true,\"confidence\":1.0,\"rationale\":\"...\"}]}."
                    ),
                },
                {"role": "user", "content": json.dumps({"items": payload})},
            ],
        )
        parsed = BatchJudgeVerdicts.model_validate(_extract_json(content))
        by_index = {item.index: item for item in parsed.verdicts}
        verdicts: list[JudgeVerdict] = []
        for index in range(len(pending)):
            item = by_index.get(index)
            if item is None:
                verdicts.append(
                    JudgeVerdict(
                        correct=False,
                        sufficient=False,
                        confidence=0.0,
                        rationale="missing batch verdict",
                    )
                )
            else:
                verdicts.append(
                    JudgeVerdict(
                        correct=item.correct,
                        sufficient=item.sufficient,
                        confidence=item.confidence,
                        rationale=item.rationale,
                    )
                )
        return verdicts

    def _chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        max_tokens: int = 512,
    ) -> str:
        # GPT-5 family uses max_completion_tokens + doesn't accept
        # arbitrary temperature, and burns most of the budget on hidden
        # reasoning — raise the cap to 32K so the visible JSON output
        # always fits regardless of how much the model "thinks."
        is_gpt5 = model.lower().startswith("gpt-5")
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if is_gpt5:
            payload["max_completion_tokens"] = max(max_tokens, 32768)
        else:
            payload["temperature"] = 0
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:  # pragma: no cover - network failure path
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI-compatible server error {exc.code}: {detail}") from exc
        return str(body["choices"][0]["message"]["content"])


def run_answer_workflow_benchmark(
    *,
    judge_mode: JudgeMode,
    strategies: list[Strategy],
    scenario_limit: int | None,
    output_root: Path,
    answer_model: str = "gpt-4o-mini",
    judge_model: str = "gpt-4o-mini",
    openai_base_url: str = "http://192.168.1.193:8000/v1",
    openai_api_key: str = "",
    judge_batch_size: int = 10,
    backend: dict[str, Any] | None = None,
    scenarios_source: str = "synthetic",
    longbench_per_task: int = 8,
) -> dict[str, Any]:
    if judge_mode == "openai":
        answerer: Answerer = OpenAICompatAnswerer(
            answer_model=answer_model,
            judge_model=judge_model,
            base_url=openai_base_url,
            api_key=openai_api_key,
        )
    else:
        answerer = DeterministicAnswerer()

    if scenarios_source == "longbench":
        from benchmarks.external.longbench_scenarios import build_longbench_scenarios
        scenarios = build_longbench_scenarios(per_task=longbench_per_task)
    elif scenarios_source == "synthetic":
        scenarios = build_scenarios(content_multiplier=10)
    else:
        raise ValueError(f"Unknown scenarios_source: {scenarios_source!r}")
    if scenario_limit is not None:
        scenarios = scenarios[:scenario_limit]
    run_dir = output_root / datetime.now(UTC).strftime("%Y-%m-%d") / (
        "answer-workflow-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = run_dir / "results.jsonl"
    stash = Stele.from_config(
        {
            "backend": backend or {"type": "memory"},
            "pii": {"raw_fetch_enabled": True},
            "interception": {
                "min_chars": 1,
                "min_estimated_tokens": 1,
                "max_replacement_chars": 1400,
            },
            "indexing": {
                "provider": "chunkshop",
                "mode": "sync",
                "chunk_words": 90,
                "chunk_overlap_words": 25,
            },
        }
    )
    try:
        results: list[WorkflowResult] = []
        pending: list[PendingAttempt] = []
        for scenario in scenarios:
            replacement = stash_tool_result(
                scenario.content,
                stash=stash,
                namespace=f"answer_workflow_{scenario.kind}",
                session_id=scenario.session_id,
                tool_name=scenario.name,
                metadata=scenario.metadata,
                always_store=True,
            )
            reference = _reference_from_replacement(str(replacement))
            for strategy in strategies:
                started = time.perf_counter()
                attempt = _run_strategy(
                    stash=stash,
                    scenario=scenario,
                    reference=reference,
                    replacement=str(replacement),
                    strategy=strategy,
                    answerer=answerer,
                )
                pending.append(
                    PendingAttempt(
                        scenario=scenario,
                        strategy=strategy,
                        attempt=attempt,
                        latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    )
                )
                if len(pending) >= judge_batch_size:
                    _flush_judge_batch(
                        answerer=answerer,
                        pending=pending,
                        results=results,
                        jsonl_path=jsonl_path,
                    )
                    pending.clear()
        if pending:
            _flush_judge_batch(
                answerer=answerer,
                pending=pending,
                results=results,
                jsonl_path=jsonl_path,
            )
    finally:
        stash.close()

    report = _summarize(results=results, scenarios=scenarios, strategies=strategies)
    (run_dir / "AnswerWorkflow.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "AnswerWorkflow.md").write_text(_markdown(report), encoding="utf-8")
    return {"run_dir": str(run_dir), **report}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run answer workflow benchmark")
    parser.add_argument("--judge", choices=["deterministic", "openai"], default="deterministic")
    parser.add_argument(
        "--strategies",
        default="summary_only,summary_then_search,search_first,adaptive,raw_fetch",
    )
    parser.add_argument("--scenario-limit", type=int, default=None)
    default_model = "Intel/Qwen3-Coder-Next-int4-AutoRound"
    parser.add_argument("--answer-model", default=os.environ.get("YMS_ANSWER_MODEL", default_model))
    parser.add_argument("--judge-model", default=os.environ.get("YMS_JUDGE_MODEL", default_model))
    parser.add_argument(
        "--openai-base-url",
        default=os.environ.get("OPENAI_BASE_URL", "http://192.168.1.193:8000/v1"),
    )
    parser.add_argument("--openai-api-key", default=os.environ.get("OPENAI_API_KEY", "local"))
    parser.add_argument(
        "--judge-batch-size",
        type=int,
        default=int(os.environ.get("YMS_JUDGE_BATCH_SIZE", "10")),
    )
    parser.add_argument("--output-root", type=Path, default=Path("benchmarks/runs"))
    parser.add_argument(
        "--backend",
        choices=["memory", "sqlite", "postgres", "mariadb", "clickhouse"],
        default="memory",
        help="Stele storage backend. Postgres etc. require the matching "
             "DSN env var (STELE_PG_DSN / STELE_MARIADB_DSN / STELE_CLICKHOUSE_DSN).",
    )
    parser.add_argument(
        "--scenarios",
        choices=["synthetic", "longbench"],
        default="synthetic",
        help="Scenario source. 'synthetic' uses benchmarks/longrun.py's "
             "built-in scenarios (shipped with stele). 'longbench' pulls "
             "real third-party QA records from THUDM/LongBench so the "
             "token+accuracy measurement is on data we did not author.",
    )
    parser.add_argument(
        "--longbench-per-task",
        type=int, default=8,
        help="Records per LongBench task (only used with --scenarios longbench).",
    )
    args = parser.parse_args()
    backend_cfg: dict[str, Any] = {"type": args.backend}
    if args.backend == "postgres":
        dsn = os.environ.get("STELE_PG_DSN")
        if not dsn:
            parser.error("--backend postgres requires STELE_PG_DSN env var")
        backend_cfg["dsn"] = dsn
    elif args.backend == "mariadb":
        dsn = os.environ.get("STELE_MARIADB_DSN")
        if not dsn:
            parser.error("--backend mariadb requires STELE_MARIADB_DSN env var")
        backend_cfg["dsn"] = dsn
    elif args.backend == "clickhouse":
        dsn = os.environ.get("STELE_CLICKHOUSE_DSN")
        if not dsn:
            parser.error("--backend clickhouse requires STELE_CLICKHOUSE_DSN env var")
        backend_cfg["dsn"] = dsn
    strategies = [item.strip() for item in args.strategies.split(",") if item.strip()]
    report = run_answer_workflow_benchmark(
        judge_mode=args.judge,
        strategies=strategies,
        scenario_limit=args.scenario_limit,
        output_root=args.output_root,
        answer_model=args.answer_model,
        judge_model=args.judge_model,
        openai_base_url=args.openai_base_url,
        openai_api_key=args.openai_api_key,
        judge_batch_size=args.judge_batch_size,
        backend=backend_cfg,
        scenarios_source=args.scenarios,
        longbench_per_task=args.longbench_per_task,
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    print(report["run_dir"])


def _run_strategy(
    *,
    stash: Stele,
    scenario: BenchmarkScenario,
    reference: str,
    replacement: str,
    strategy: Strategy,
    answerer: Answerer,
) -> AnswerAttempt:
    """Run a recall strategy, then ask the answerer with the assembled context.

    Phase 3 migration: this function now delegates to `stash.recall(...)`.
    The mapping from the old benchmark strategy names to the new StrategyName:
      - summary_only        → "summary_only" (uses replacement summary directly)
      - search_first        → "artifact_search"
      - summary_then_search → "adaptive" (truncated to 2 tiers: summary_only synthesized
                             from `replacement`, then artifact_search)
      - adaptive            → "adaptive" with all tiers
      - raw_fetch           → "raw_fetch"
    """
    from stele.core.memory_record import MemoryScope
    from stele.core.reference import parse_reference

    ref_parsed = parse_reference(reference)
    scope = MemoryScope(namespace=ref_parsed.namespace)
    artifact_id = ref_parsed.artifact_id

    # summary_only and summary_then_search use the benchmark's pre-built `replacement`
    # string (the artifact's summary at stash time) directly. The Phase 3 strategy
    # SummaryOnlyStrategy resolves the summary via fetch, which may differ. Use
    # replacement here for behavior preservation.
    if strategy == "summary_only":
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement)],
            search_calls=0,
            fetch_calls=0,
            llm_round_trips=1,
        )

    if strategy == "search_first":
        result = stash.recall(
            query=scenario.query,
            scope=scope,
            strategy="artifact_search",
            artifact_id=artifact_id,
            max_artifact_hits=3,
        )
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("search", result.context)],
            search_calls=result.stats.artifact_searches,
            fetch_calls=result.stats.fetches,
            llm_round_trips=1,
        )

    if strategy == "summary_then_search":
        first = _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement)],
            search_calls=0,
            fetch_calls=0,
            llm_round_trips=1,
        )
        if _answer_is_sufficient(first.answer, scenario.expected_answer):
            return first
        result = stash.recall(
            query=scenario.query,
            scope=scope,
            strategy="artifact_search",
            artifact_id=artifact_id,
            max_artifact_hits=3,
        )
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement), ("search", result.context)],
            search_calls=result.stats.artifact_searches,
            fetch_calls=result.stats.fetches,
            llm_round_trips=2,
        )

    if strategy == "adaptive":
        # Phase 3 adaptive uses hit-count + confidence floor — no oracle.
        # Cost ceiling here matches the old behavior: cap at 3 LLM round trips.
        result = stash.recall(
            query=scenario.query,
            scope=scope,
            strategy="adaptive",
            artifact_id=artifact_id,
        )
        # The benchmark previously did up to 3 LLM calls inside adaptive
        # (summary, summary+search, summary+search+raw). Phase 3's adaptive
        # never calls an LLM; we issue one final answerer call with the
        # accumulated context for benchmark behavior parity.
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement), ("recall", result.context)],
            search_calls=result.stats.artifact_searches,
            fetch_calls=result.stats.fetches,
            llm_round_trips=1,
        )

    if strategy == "raw_fetch":
        # Preserve the old benchmark behavior: pii.raw_fetch_enabled must be on.
        result = stash.recall(
            query=scenario.query,
            scope=scope,
            strategy="raw_fetch",
            artifact_id=artifact_id,
        )
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement), ("raw", result.context)],
            search_calls=0,
            fetch_calls=result.stats.fetches,
            llm_round_trips=1,
        )

    raise ValueError(f"Unknown strategy: {strategy}")


def _flush_judge_batch(
    *,
    answerer: Answerer,
    pending: list[PendingAttempt],
    results: list[WorkflowResult],
    jsonl_path: Path,
) -> None:
    try:
        verdicts = answerer.judge_batch(pending)
    except Exception as exc:
        verdicts = [
            JudgeVerdict(
                correct=False,
                sufficient=False,
                confidence=0.0,
                rationale=f"batch_judge_failed: {exc}",
            )
            for _ in pending
        ]
    with jsonl_path.open("a", encoding="utf-8") as handle:
        for item, verdict in zip(pending, verdicts, strict=True):
            attempt = item.attempt
            result = WorkflowResult(
                scenario=item.scenario.name,
                kind=item.scenario.kind,
                strategy=item.strategy,
                judge_mode=answerer.mode,
                correct=verdict.correct,
                sufficient=verdict.sufficient,
                confidence=round(verdict.confidence, 4),
                prompt_tokens=attempt.prompt_tokens,
                completion_tokens=attempt.completion_tokens,
                total_tokens=attempt.prompt_tokens + attempt.completion_tokens,
                llm_round_trips=attempt.llm_round_trips,
                stash_search_calls=attempt.stash_search_calls,
                stash_fetch_calls=attempt.stash_fetch_calls,
                context_bytes=attempt.context_bytes,
                latency_ms=item.latency_ms,
                answer=attempt.answer,
                rationale=verdict.rationale,
            )
            results.append(result)
            handle.write(json.dumps(asdict(result), sort_keys=True))
            handle.write("\n")


def _answer_with_context(
    answerer: Answerer,
    *,
    scenario: BenchmarkScenario,
    contexts: list[tuple[str, str]],
    search_calls: int,
    fetch_calls: int,
    llm_round_trips: int,
) -> AnswerAttempt:
    context = "\n\n".join(f"[{name}]\n{text}" for name, text in contexts)
    prompt = f"Question:\n{scenario.query}\n\nContext:\n{context}"
    answer, completion_tokens = answerer.answer(
        question=scenario.query,
        context=context,
        expected_answer=scenario.expected_answer,
    )
    return AnswerAttempt(
        answer=answer,
        prompt_tokens=estimate_tokens(prompt),
        completion_tokens=completion_tokens,
        llm_round_trips=llm_round_trips,
        stash_search_calls=search_calls,
        stash_fetch_calls=fetch_calls,
        context_bytes=len(context.encode("utf-8")),
        path=context,
    )


def _summarize(
    *,
    results: list[WorkflowResult],
    scenarios: list[BenchmarkScenario],
    strategies: list[Strategy],
) -> dict[str, Any]:
    by_strategy: dict[str, list[WorkflowResult]] = {
        strategy: [result for result in results if result.strategy == strategy]
        for strategy in strategies
    }
    strategy_rows = {
        strategy: {
            "runs": len(rows),
            "accuracy": _mean_bool(row.correct for row in rows),
            "mean_total_tokens": _mean(row.total_tokens for row in rows),
            "mean_prompt_tokens": _mean(row.prompt_tokens for row in rows),
            "mean_llm_round_trips": _mean(row.llm_round_trips for row in rows),
            "mean_search_calls": _mean(row.stash_search_calls for row in rows),
            "mean_fetch_calls": _mean(row.stash_fetch_calls for row in rows),
            "mean_latency_ms": _mean(row.latency_ms for row in rows),
        }
        for strategy, rows in by_strategy.items()
    }
    accurate = [row for row in results if row.correct]
    cheapest_accurate = min(accurate, key=lambda row: row.total_tokens, default=None)
    summary = {
        "scenario_count": len(scenarios),
        "strategy_count": len(strategies),
        "total_runs": len(results),
        "overall_accuracy": _mean_bool(row.correct for row in results),
        "best_accuracy": max((row["accuracy"] for row in strategy_rows.values()), default=0.0),
        "lowest_mean_tokens": min(
            (row["mean_total_tokens"] for row in strategy_rows.values()),
            default=0.0,
        ),
        "cheapest_accurate_strategy": cheapest_accurate.strategy if cheapest_accurate else None,
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "benchmark": "answer_workflow",
        "summary": summary,
        "by_strategy": strategy_rows,
        "results": [asdict(result) for result in results],
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Answer Workflow Benchmark",
        "",
        "Measures answer correctness, estimated tokens, LLM round trips, search calls, "
        "and fetch calls by retrieval strategy.",
        "",
        "| Strategy | Runs | Accuracy | Mean Tokens | Round Trips | Search Calls | Fetch Calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for strategy, row in report["by_strategy"].items():
        lines.append(
            f"| {strategy} | {row['runs']} | {row['accuracy']} | {row['mean_total_tokens']} | "
            f"{row['mean_llm_round_trips']} | {row['mean_search_calls']} | "
            f"{row['mean_fetch_calls']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _answer_is_sufficient(answer: str, expected_answer: str | None) -> bool:
    if expected_answer is None:
        return "not have enough information" in answer.lower()
    return expected_answer.lower() in answer.lower()


def _reference_from_replacement(replacement: str) -> str:
    for line in replacement.splitlines():
        if line.startswith("reference: "):
            return line.removeprefix("reference: ").strip()
    raise ValueError("Replacement payload did not include a reference")


def _extract_json(value: str) -> dict[str, Any]:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        stripped = stripped[start : end + 1]
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("Judge did not return a JSON object")
    return parsed


def _mean(values: Any) -> float:
    items = [float(value) for value in values]
    return round(statistics.mean(items), 4) if items else 0.0


def _mean_bool(values: Any) -> float:
    items = [1.0 if value else 0.0 for value in values]
    return round(statistics.mean(items), 4) if items else 0.0


if __name__ == "__main__":
    main()
