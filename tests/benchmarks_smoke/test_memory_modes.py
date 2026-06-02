"""Unit tests for the memory-modes benchmark harness.

Covers the deterministic pieces that need no LLM, no Postgres, no store: the
Mode protocol conformance, corpus determinism, the pure detectors/classifiers,
the recall@K evidence parser, score() purity, and the runner's aggregation.
This turns the manual smokes into real coverage for the parts that can be tested
without standing anything up.
"""

from __future__ import annotations

from benchmarks.external.memory_modes import (
    fact_recall,
    guardrail_adherence,
    precedent_recall,
    resume_task_state,
    skill_adherence,
)
from benchmarks.external.memory_modes.base import Case, CaseResult, Mode
from benchmarks.external.memory_modes.registry import MODES
from benchmarks.external.memory_modes.run import _aggregate


def test_registry_has_six_modes_satisfying_protocol() -> None:
    assert len(MODES) == 6
    names = {m.name for m in MODES}
    assert names == {
        "guardrail_adherence", "skill_adherence", "best_practice",
        "precedent_recall", "fact_recall", "resume_task_state",
    }
    for m in MODES:
        assert isinstance(m, Mode)
        assert isinstance(m.name, str) and m.name
        assert isinstance(m.conditions, tuple) and m.conditions
        assert m.measured and m.not_measured  # honesty box is populated


def test_synthetic_corpus_nonempty_and_deterministic() -> None:
    for m in MODES:
        a = m.corpus("synthetic", 0, 0)
        b = m.corpus("synthetic", 0, 0)
        assert a, f"{m.name} produced no synthetic cases"
        assert all(isinstance(c, Case) for c in a)
        assert [c.case_id for c in a] == [c.case_id for c in b], f"{m.name} not deterministic"
        assert len({c.case_id for c in a}) == len(a), f"{m.name} has duplicate case ids"


def test_per_corpus_cap_is_honored() -> None:
    cases = precedent_recall.PrecedentRecall().corpus("synthetic", 5, 0)
    assert len(cases) == 5


def test_guardrail_detectors() -> None:
    assert guardrail_adherence._emdash("a — b") == 1          # em dash
    assert guardrail_adherence._emdash("a – b") == 1          # en dash
    assert guardrail_adherence._emdash("a -- b") == 1              # double hyphen
    assert guardrail_adherence._emdash("a, b: c (d)") == 0
    lev = guardrail_adherence._word(r"\bleverage\b")
    assert lev("we leverage scale") == 1
    assert lev("we use scale") == 0


def test_guardrail_score_is_pure_and_binary() -> None:
    g = guardrail_adherence.GuardrailAdherence()
    case = Case(case_id="x", question="q", gold="0", payload={"relevant": ("G-EMDASH",)})
    hit = CaseResult(output="a — b", metric={"violations": 2.0}, tokens_in=1,
                     tokens_out=1, deterministic=True)
    clean = CaseResult(output="a, b", metric={"violations": 0.0}, tokens_in=1,
                       tokens_out=1, deterministic=True)
    assert g.score(case, hit) == {"violation": 1.0, "violations": 2.0}
    assert g.score(case, clean) == {"violation": 0.0, "violations": 0.0}


def test_skill_detectors() -> None:
    assert skill_adherence._pnpm("run `pnpm add zod`") == 1
    assert skill_adherence._pnpm("run `npm install zod`") == 0
    assert skill_adherence._typehint("def f(x: int) -> int: return x") == 1
    assert skill_adherence._typehint("def f(x): return x") == 0


def test_resume_classify_text_and_corpus() -> None:
    c = resume_task_state._classify_text
    assert c("we shipped it to prod") == "done"
    assert c("we decided not to build it") == "abandoned"
    assert c("still in progress, not yet done") == "in_progress"
    assert c("there is no record of that") == "absent"
    # corpus mixes built (done/in_progress/abandoned) + absent
    golds = {c.gold for c in resume_task_state.ResumeTaskState().corpus("synthetic", 0, 0)}
    assert golds == {"done", "in_progress", "abandoned", "absent"}
    assert set(resume_task_state._NODE_STATUS.values()) == {"done", "active", "failed"}


def test_precedent_episodes_are_distinct() -> None:
    eps = precedent_recall._episodes()
    assert len(eps) == 40
    assert len({e["ep_id"] for e in eps}) == 40
    assert len({e["tool"] for e in eps}) == 40  # distinctive checkable tokens


def test_fact_norm_and_evidence_parser() -> None:
    assert fact_recall._norm("Hello,  World!") == "hello world"
    assert fact_recall._evidence({"evidence": "['D1:3']"}) == ["D1:3"]
    assert fact_recall._evidence({"evidence": ["D2:1", "D2:2"]}) == ["D2:1", "D2:2"]
    assert fact_recall._evidence({"evidence": "not-a-list"}) == []


def test_runner_aggregate_means_and_n() -> None:
    rows = [
        {"mode": "m", "source": "synthetic", "case": "c1", "conditions": {
            "memory_driven": {"recall_at_k": 1.0, "tokens_in": 10, "deterministic": True}}},
        {"mode": "m", "source": "synthetic", "case": "c2", "conditions": {
            "memory_driven": {"recall_at_k": 0.0, "tokens_in": 20, "deterministic": True}}},
    ]
    agg = _aggregate(rows)
    cell = agg["m"]["synthetic"]["memory_driven"]
    assert cell["recall_at_k"] == 0.5
    assert cell["tokens_in"] == 15.0
    assert cell["n"] == 2
    assert "deterministic" not in cell  # booleans are not averaged
