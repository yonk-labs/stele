"""Third-party benchmark → BenchmarkScenario adapters.

LongBench has its own module (``longbench_scenarios.py``). This module
adds RAGBench, LongMemEval-S, and LoCoMo so the answer-workflow runner
can drive the same five recall strategies against four independent
third-party benchmarks — none of which ship with stele.

Each adapter maps the benchmark's natural shape to a
:class:`BenchmarkScenario` with:

- ``content`` — the long context the model would otherwise see in full
- ``query`` — the question to answer
- ``expected_answer`` — the gold answer string used by the judge
- ``metadata`` — provenance (source benchmark, task/subset, gold variants)

LoCoMo and LongMemEval contain *very* large contexts (whole multi-day
conversations or 60+ session haystacks). Each adapter accepts a
``max_chars`` limit so the API cost stays bounded; the limit is
truncation-from-the-end since the answer is often in later turns
(documented in the per-adapter docstring).
"""

from __future__ import annotations

from typing import Any

from benchmarks.external import loaders
from benchmarks.longrun import BenchmarkScenario

# -----------------------------------------------------------------------------
# RAGBench
# -----------------------------------------------------------------------------

DEFAULT_RAGBENCH_SUBSETS = (
    "hotpotqa", "msmarco", "covidqa", "pubmedqa", "techqa", "hagrid",
)


def build_ragbench_scenarios(
    *,
    subsets: tuple[str, ...] = DEFAULT_RAGBENCH_SUBSETS,
    per_subset: int = 6,
    max_chars: int = 24_000,
) -> list[BenchmarkScenario]:
    """RAGBench: one scenario per record, context = concat of documents."""
    scenarios: list[BenchmarkScenario] = []
    for subset in subsets:
        try:
            recs = loaders.load_ragbench(subset, split="test", limit=per_subset)
        except loaders.DatasetUnavailable:
            continue
        for i, rec in enumerate(recs):
            docs = rec.get("documents") or []
            response = str(rec.get("response", "") or "").strip()
            question = str(rec.get("question", "") or "").strip()
            if not response or not question or not docs:
                continue
            context = "\n\n".join(str(d) for d in docs)[:max_chars]
            scenarios.append(
                BenchmarkScenario(
                    name=f"ragbench-{subset}-{i}",
                    kind="tool_output",
                    content=context,
                    query=question,
                    expected_answer=response,
                    session_id=f"ragbench-{subset}",
                    metadata={
                        "source": "ragbench",
                        "subset": subset,
                        "doc_count": str(len(docs)),
                    },
                )
            )
    return scenarios


# -----------------------------------------------------------------------------
# LongMemEval-S
# -----------------------------------------------------------------------------

def build_longmemeval_scenarios(
    *,
    max_questions: int = 12,
    max_chars: int = 60_000,
) -> list[BenchmarkScenario]:
    """LongMemEval-S: one scenario per question, context = haystack sessions.

    The haystack can be 200K+ tokens in raw form; we truncate to
    ``max_chars`` because the model context for the answer model is
    bounded and the synthetic answerer also caps context. Tail-truncation
    keeps the most-recent sessions (where the answer span typically
    lives per the LongMemEval paper).
    """
    scenarios: list[BenchmarkScenario] = []
    for rec in loaders.iter_longmemeval_s(max_questions):
        question = str(rec.get("question", "") or "").strip()
        answer = str(rec.get("answer", "") or "").strip()
        qid = str(rec.get("question_id", ""))
        # Skip abstention questions — the runner's accuracy oracle is
        # answer-string containment, not abstention recall.
        if qid.endswith("_abs") or not question or not answer:
            continue
        parts: list[str] = []
        for sess in rec.get("haystack_sessions", []) or []:
            for turn in sess:
                if not isinstance(turn, dict):
                    continue
                role = turn.get("role", "?")
                content = turn.get("content", "")
                parts.append(f"[{role}] {content}")
        context_full = "\n".join(parts)
        # Tail-truncate: keep the last max_chars characters.
        context = context_full[-max_chars:] if len(context_full) > max_chars else context_full
        scenarios.append(
            BenchmarkScenario(
                name=f"lme-{qid or len(scenarios)}",
                kind="long_memory",
                content=context,
                query=question,
                expected_answer=answer,
                session_id="lme",
                metadata={
                    "source": "longmemeval-s",
                    "question_id": qid,
                    "context_chars_original": str(len(context_full)),
                    "context_chars_used": str(len(context)),
                },
            )
        )
    return scenarios


# -----------------------------------------------------------------------------
# LoCoMo
# -----------------------------------------------------------------------------

def build_locomo_scenarios(
    *,
    max_samples: int = 3,
    qas_per_sample: int = 6,
    max_chars: int = 40_000,
) -> list[BenchmarkScenario]:
    """LoCoMo: one scenario per (sample, qa). Context = sample's
    conversation sessions concatenated; truncated to max_chars.

    Skips ``category == 5`` (adversarial / abstention) since the
    runner's oracle is answer-string containment.
    """
    samples = loaders.load_locomo()[:max_samples]
    scenarios: list[BenchmarkScenario] = []
    for sample in samples:
        sid = sample.get("sample_id", "?")
        conv = sample.get("conversation", {}) or {}
        # Concatenate every session_X list of turns in order, PREFIXED with
        # that session's date-time header. LoCoMo dialogue only ever uses
        # RELATIVE dates ("last Friday"); the absolute date a temporal
        # question needs lives in the `session_N_date_time` string, not the
        # turns. Dropping it (the old behaviour) made category-2 temporal
        # questions unanswerable from context. We inject it so any lane can
        # resolve "last Friday" against "8 May 2023".
        parts: list[str] = []
        for key in sorted(conv.keys()):
            if not key.startswith("session_"):
                continue
            val = conv.get(key)
            if not isinstance(val, list):
                continue
            dt = conv.get(f"{key}_date_time")
            if isinstance(dt, str) and dt:
                parts.append(f"[Session date: {dt}]")
            for turn in val:
                if not isinstance(turn, dict):
                    continue
                speaker = turn.get("speaker", "?")
                text = turn.get("text", "")
                if text:
                    parts.append(f"[{speaker}] {text}")
        context_full = "\n".join(parts)
        context = context_full[-max_chars:] if len(context_full) > max_chars else context_full
        n_taken = 0
        for qa in sample.get("qa", []) or []:
            if n_taken >= qas_per_sample:
                break
            if qa.get("category") == 5:
                continue
            question = str(qa.get("question", "") or "").strip()
            answer = str(qa.get("answer", "") or "").strip()
            if not question or not answer:
                continue
            scenarios.append(
                BenchmarkScenario(
                    name=f"locomo-{sid}-{n_taken}",
                    kind="long_memory",
                    content=context,
                    query=question,
                    expected_answer=answer,
                    session_id=f"locomo-{sid}",
                    metadata={
                        "source": "locomo",
                        "sample_id": str(sid),
                        "category": str(qa.get("category", "")),
                    },
                )
            )
            n_taken += 1
    return scenarios


# -----------------------------------------------------------------------------
# Builder registry — used by answer_workflow.py
# -----------------------------------------------------------------------------

def build_scenarios_for(source: str, **kwargs: Any) -> list[BenchmarkScenario]:
    if source == "ragbench":
        return build_ragbench_scenarios(**kwargs)
    if source == "longmemeval":
        return build_longmemeval_scenarios(**kwargs)
    if source == "locomo":
        return build_locomo_scenarios(**kwargs)
    raise ValueError(f"Unknown third-party source: {source!r}")
