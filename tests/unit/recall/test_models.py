"""Tests for recall models — field validation, defaults, immutability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.core.memory_record import MemoryScope
from stele.recall.models import (
    Citation,
    Escalation,
    RecallContext,
    RecallRequest,
    RecallResult,
    RecallStats,
)


def test_citation_required_fields() -> None:
    c = Citation(
        kind="memory",
        id="mem_abc",
        reference="stele://default/art_xyz",
        score=0.75,
        snippet="user prefers dark mode",
    )
    assert c.kind == "memory"
    assert c.score == 0.75


def test_citation_rejects_unknown_kind() -> None:
    with pytest.raises(PydanticValidationError):
        Citation(
            kind="bogus",  # type: ignore[arg-type]
            id="x",
            reference="stele://default/art",
            score=0.5,
            snippet="x",
        )


def test_escalation_with_top_score_none() -> None:
    e = Escalation(
        strategy="memory_search",
        hit_count=0,
        top_score=None,
        reason="zero_hits",
    )
    assert e.top_score is None
    assert e.reason == "zero_hits"


def test_recall_stats_defaults_to_zero() -> None:
    s = RecallStats()
    assert s.memory_searches == 0
    assert s.artifact_searches == 0
    assert s.fetches == 0
    assert s.estimated_context_tokens == 0
    assert s.latency_ms == 0.0


def test_recall_request_defaults() -> None:
    req = RecallRequest(
        query="what does the user prefer",
        scope=MemoryScope(user_id="alice"),
    )
    assert req.strategy == "adaptive"
    assert req.artifact_id is None
    assert req.sufficient is None
    assert req.max_memory_hits == 5
    assert req.confidence_floor is None


def test_recall_result_minimal() -> None:
    r = RecallResult(
        strategy_used="abstain",
        context="",
        citations=[],
        escalations=[
            Escalation(
                strategy="abstain",
                hit_count=0,
                top_score=None,
                reason="exhausted",
            )
        ],
        pii_flags=[],
        source_refs=[],
        stats=RecallStats(),
        abstained=True,
        abstain_reason="no_sufficient_context",
    )
    assert r.abstained is True
    assert r.strategy_used == "abstain"


def test_recall_context_frozen() -> None:
    from dataclasses import FrozenInstanceError

    ctx = RecallContext(
        query="x",
        scope=MemoryScope(user_id="alice"),
        accumulated_citations=[],
        accumulated_text="",
    )
    with pytest.raises(FrozenInstanceError):
        ctx.query = "y"  # type: ignore[misc]
