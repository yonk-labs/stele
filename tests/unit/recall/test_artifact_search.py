"""Tests for ArtifactSearchStrategy."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_artifact_search_global() -> None:
    stele = Stele(StashConfig())
    stele.store(content="The migration deadline is 2026-06-30." * 5, namespace="default")
    result = stele.recall.artifact_search(
        query="migration deadline",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "artifact_search"
    assert result.stats.artifact_searches == 1
    stele.close()


def test_artifact_search_forced_scope() -> None:
    stele = Stele(StashConfig())
    stored = stele.store(
        content="The migration deadline is 2026-06-30. " * 10,
        namespace="default",
    )
    result = stele.recall.artifact_search(
        query="migration",
        scope=MemoryScope(user_id="alice"),
        artifact_id=stored.artifact_id,
    )
    assert result.strategy_used == "artifact_search"
    for c in result.citations:
        assert c.reference == stored.reference
    stele.close()
