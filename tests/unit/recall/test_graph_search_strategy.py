from datetime import UTC, datetime

import pytest

from stele.core.config import RecallConfig
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele
from stele.pii.scrubber import DisabledPIIScrubber
from stele.recall.facade import Recall
from stele.revisor.base import GraphHit, NoOpRevisor, RetractedBehavior


class FakeRevisor(NoOpRevisor):
    active = True

    def search_current(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        return [
            GraphHit(
                stele_ref="stele://n/mem-1",
                text="hello world",
                score=0.9,
                chunk_id="c1",
            )
        ]

    def search_as_of(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        as_of: datetime,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        return [GraphHit(stele_ref="stele://n/mem-old", text="old value", score=0.7)]


def _recall(stele: Stele) -> Recall:
    return Recall(
        stele=stele,
        memory=stele.memory,
        scrubber=DisabledPIIScrubber(),
        config=RecallConfig(),
    )


def test_graph_search_capability_error_when_revisor_inactive() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    with pytest.raises(CapabilityError):
        _recall(s).graph_search(query="q", scope=MemoryScope(namespace="n"))
    s.close()


def test_graph_search_returns_hits_and_cites_stele_ref() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    s._revisor = FakeRevisor()
    res = _recall(s).graph_search(query="hello", scope=MemoryScope(namespace="n"))
    assert res.strategy_used == "graph_search"
    assert res.citations and res.citations[0].reference == "stele://n/mem-1"
    assert res.source_refs == ["stele://n/mem-1"]
    s.close()


def test_graph_search_as_of_path() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    s._revisor = FakeRevisor()
    res = _recall(s).graph_search(
        query="x", scope=MemoryScope(namespace="n"), as_of=datetime.now(UTC)
    )
    assert res.citations[0].reference == "stele://n/mem-old"
    s.close()
