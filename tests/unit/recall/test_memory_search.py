"""Tests for MemorySearchStrategy."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_memory_search_returns_citations() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode for the dashboard",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    result = stele.recall.memory_search(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "memory_search"
    assert result.citations
    assert result.citations[0].kind == "memory"
    assert result.stats.memory_searches == 1
    stele.close()


def test_memory_search_forced_scope_filters_by_artifact() -> None:
    stele = Stele(StashConfig())
    # Store two artifacts; use their references as source_refs
    artifact_a = stele.store(content="placeholder a", namespace="default")
    artifact_b = stele.store(content="placeholder b", namespace="default")
    stele.memory.add(
        text="dark mode preference",
        kind="preference",
        source_refs=[artifact_a.reference],
        scope=MemoryScope(user_id="alice"),
    )
    stele.memory.add(
        text="dark mode preference",
        kind="preference",
        source_refs=[artifact_b.reference],
        scope=MemoryScope(user_id="alice"),
    )
    # Force scope to artifact_a — should only return that memory.
    result = stele.recall.memory_search(
        query="dark",
        scope=MemoryScope(user_id="alice"),
        artifact_id=artifact_a.artifact_id,
    )
    assert len(result.citations) == 1
    assert result.citations[0].reference == artifact_a.reference
    stele.close()
