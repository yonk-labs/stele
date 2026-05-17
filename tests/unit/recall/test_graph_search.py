"""GraphSearchStrategy capability honesty (SC-P5-07): with the default
config (memory backend, graph disabled) the Revisor is inactive, so
graph_search raises CapabilityError — exactly as before Phase 5, just with
an accurate message pointing at the real requirement."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope


def test_graph_search_raises_capability_error() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(CapabilityError, match="graph_search requires"):
        stele.recall.graph_search(
            query="anything",
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()


def test_graph_search_via_canonical_entry_raises_capability_error() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(CapabilityError, match="graph_search requires"):
        stele.recall(
            query="anything",
            scope=MemoryScope(user_id="alice"),
            strategy="graph_search",
        )
    stele.close()
