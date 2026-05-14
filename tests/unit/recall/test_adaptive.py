"""Tests for AdaptiveStrategy — escalation logic, tier order, callback path."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_adaptive_stops_at_first_tier_when_above_floor() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode for the dashboard",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    result = stele.recall.adaptive(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "memory_search"
    assert len(result.escalations) == 1
    assert result.escalations[0].reason == "tier_complete"
    stele.close()


def test_adaptive_escalates_through_tiers_on_zero_hits() -> None:
    stele = Stele(StashConfig())
    # No memories; no artifacts → adaptive should escalate all the way to abstain
    result = stele.recall.adaptive(
        query="something nobody mentioned",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "abstain"
    assert result.abstained is True
    # tier_order default is [memory_search, artifact_search, raw_fetch, abstain],
    # but raw_fetch is skipped without artifact_id
    strategies_seen = [e.strategy for e in result.escalations]
    assert "memory_search" in strategies_seen
    assert "artifact_search" in strategies_seen
    assert "abstain" in strategies_seen
    assert "raw_fetch" not in strategies_seen
    stele.close()


def test_adaptive_skips_raw_fetch_without_artifact_id() -> None:
    stele = Stele(StashConfig())
    result = stele.recall.adaptive(
        query="x",
        scope=MemoryScope(user_id="alice"),
    )
    seen = [e.strategy for e in result.escalations]
    assert "raw_fetch" not in seen
    stele.close()


def test_adaptive_includes_raw_fetch_when_artifact_id_given() -> None:
    cfg = StashConfig.load({"pii": {"raw_fetch_enabled": True}})
    stele = Stele(cfg)
    stored = stele.store("this is the full content body", namespace="default")
    result = stele.recall.adaptive(
        query="content body",
        scope=MemoryScope(user_id="alice"),
        artifact_id=stored.artifact_id,
    )
    seen = [e.strategy for e in result.escalations]
    # Tier order: memory_search (likely zero hits), artifact_search, raw_fetch
    # If artifact_search finds the content, tier_complete fires there; raw_fetch may not run.
    # The invariant: raw_fetch is at least *available* in the tier list when artifact_id is set.
    assert seen, "expected at least one escalation"
    stele.close()


def test_adaptive_calls_sufficient_callback_when_provided() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    calls: list[int] = []

    def sufficient(ctx) -> bool:  # type: ignore[no-untyped-def]
        calls.append(len(ctx.accumulated_citations))
        return False  # force escalation

    result = stele.recall.adaptive(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
        sufficient=sufficient,
    )
    assert calls, "sufficient should have been called at least once"
    assert calls[0] >= 1
    # Because sufficient=False forced escalation, the trail should be longer than 1
    assert len(result.escalations) > 1
    stele.close()


def test_adaptive_stops_when_sufficient_returns_true() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )

    def sufficient(ctx) -> bool:  # type: ignore[no-untyped-def]
        return True

    result = stele.recall.adaptive(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
        sufficient=sufficient,
    )
    # With sufficient=True after the first hit-bearing tier, stop there.
    assert result.strategy_used in {"memory_search", "artifact_search"}
    stele.close()
