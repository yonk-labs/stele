"""Tests for AbstainStrategy."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_abstain_returns_empty_result_with_default_reason() -> None:
    stele = Stele(StashConfig())
    result = stele.recall.abstain(
        query="anything",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "abstain"
    assert result.context == ""
    assert result.citations == []
    assert result.abstained is True
    assert result.abstain_reason == "no_sufficient_context"
    stele.close()


def test_abstain_carries_explicit_reason() -> None:
    stele = Stele(StashConfig())
    result = stele.recall.abstain(
        query="anything",
        scope=MemoryScope(user_id="alice"),
        reason="user_requested_explicit_abstention",
    )
    assert result.abstain_reason == "user_requested_explicit_abstention"
    stele.close()


def test_abstain_never_raises_on_empty_inputs() -> None:
    stele = Stele(StashConfig())
    result = stele.recall.abstain(
        query="",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.abstained is True
    stele.close()
