"""SC-024: Phase 3 ArtifactSearchStrategy picks up vector/hybrid via
`retrieval.default_mode` with ZERO changes in src/stele/recall/.

The strategy calls stele.search/query with no explicit mode, so the
T21 internal dispatch auto-selects config.retrieval.default_mode.
strategy_used stays "artifact_search" — only the underlying retrieval
mode changes.
"""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.memory_record import MemoryScope


def _stash(default_mode: str) -> Stele:
    return Stele.from_config(
        {
            "backend": {"type": "memory"},
            "indexing": {"mode": "sync"},  # populate the chunk store
            "retrieval": {"default_mode": default_mode},
        }
    )


@pytest.mark.parametrize("default_mode", ["vector", "hybrid"])
def test_artifact_search_honors_default_mode(default_mode: str) -> None:
    stele = _stash(default_mode)
    stored = stele.store(
        "The database migration deadline is the end of June." * 5,
        namespace="default",
    )
    result = stele.recall.artifact_search(
        query="migration deadline",
        scope=MemoryScope(user_id="alice"),
        artifact_id=stored.artifact_id,
    )
    assert result.strategy_used == "artifact_search"
    for c in result.citations:
        assert c.reference == stored.reference
    stele.close()


@pytest.mark.parametrize("default_mode", ["vector", "hybrid"])
def test_artifact_search_global_honors_default_mode(default_mode: str) -> None:
    stele = _stash(default_mode)
    stele.store("semantic vector retrieval over indexed chunks " * 5, namespace="default")
    result = stele.recall.artifact_search(
        query="vector retrieval",
        scope=MemoryScope(user_id="bob"),
    )
    assert result.strategy_used == "artifact_search"
    assert result.stats.artifact_searches == 1
    stele.close()
