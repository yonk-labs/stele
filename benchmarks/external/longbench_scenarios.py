"""LongBench → BenchmarkScenario adapter.

Turns LongBench multi-doc QA records into the scenario shape expected by
``benchmarks/answer_workflow.py``. The point: drive the same five
recall strategies (summary_only, summary_then_search, search_first,
adaptive, raw_fetch) against third-party data that did NOT ship with
stele, so the token-reduction × accuracy table cannot be accused of
shape-tuning against our own synthetic scenarios.

Maps a record::

  {
    "input": "Who founded ...",
    "context": "Passage 1: ...\\nPassage 2: ...",
    "answers": ["Alice", "Alice Smith"],
    "length": 12345,
    "dataset": "hotpotqa",
  }

to a :class:`BenchmarkScenario` with ``content=context``,
``query=input``, ``expected_answer=answers[0]``. ``kind`` stays
``tool_output`` — the interception wrapper treats every record as an
oversized tool result regardless of provenance.
"""

from __future__ import annotations

from benchmarks.external import loaders
from benchmarks.longrun import BenchmarkScenario

DEFAULT_TASKS = ("hotpotqa", "2wikimqa", "musique", "multifieldqa_en")


def build_longbench_scenarios(
    *,
    tasks: tuple[str, ...] = DEFAULT_TASKS,
    per_task: int = 8,
) -> list[BenchmarkScenario]:
    """Return per_task × len(tasks) LongBench scenarios."""
    scenarios: list[BenchmarkScenario] = []
    for task in tasks:
        try:
            recs = list(loaders.iter_longbench(task, limit=per_task))
        except loaders.DatasetUnavailable:
            continue
        for i, rec in enumerate(recs):
            answers = rec.get("answers") or []
            if not answers:
                continue
            scenarios.append(
                BenchmarkScenario(
                    name=f"longbench-{task}-{i}",
                    kind="tool_output",
                    content=str(rec.get("context", "")),
                    query=str(rec.get("input", "")),
                    expected_answer=str(answers[0]),
                    session_id=f"longbench-{task}",
                    metadata={
                        "source": "longbench",
                        "task": task,
                        "answers_all": " || ".join(str(a) for a in answers),
                    },
                )
            )
    return scenarios
