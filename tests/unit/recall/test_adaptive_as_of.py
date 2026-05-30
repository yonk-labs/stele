from datetime import UTC, datetime

import pytest

from stele import Stele
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope


def _stele():
    # no graph, no chunk store: these tests exercise adaptive strategy fallback
    # when only the artifact/memory backends exist. Skip indexing explicitly now
    # that sync+hybrid is the default.
    return Stele.from_config(
        {"backend": {"type": "memory"}, "indexing": {"mode": "skip"}}
    )


def test_adaptive_without_as_of_uses_a_non_graph_strategy():
    s = _stele()
    scope = MemoryScope(namespace="bug3")
    art = s.store("Acme uses kafka for event streaming.", namespace="bug3")
    s.memory.add(text="kafka streaming", kind="fact",
                 source_refs=[art.reference], scope=scope)
    r = s.recall(query="streaming", scope=scope)
    assert r.strategy_used in ("memory_search", "artifact_search", "summary_only")
    s.close()


def test_adaptive_with_as_of_does_not_silently_use_artifact_search():
    s = _stele()
    scope = MemoryScope(namespace="bug3")
    art = s.store("Acme uses kafka for event streaming.", namespace="bug3")
    s.memory.add(text="kafka streaming", kind="fact",
                 source_refs=[art.reference], scope=scope)
    # as_of set + no graph backend: the only temporal-aware strategy
    # (graph_search) is unavailable -> CapabilityError (loud, correct),
    # NOT a silently-wrong artifact_search result.
    with pytest.raises(CapabilityError):
        s.recall(query="streaming", scope=scope,
                 as_of=datetime(2099, 1, 1, tzinfo=UTC))
    s.close()
