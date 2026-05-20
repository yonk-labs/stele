from datetime import UTC, datetime

from stele.revisor.base import GraphHit, NoOpRevisor


def test_graphhit_defaults() -> None:
    h = GraphHit(stele_ref="stele://ns/mem-1", text="t", score=0.5)
    assert h.retracted is False
    assert h.chunk_id is None and h.version_label is None
    assert h.superseded_by_id is None


def test_noop_revisor_is_inactive_and_inert() -> None:
    r = NoOpRevisor()
    assert r.active is False
    r.ingest_evidence(stele_ref="stele://ns/m", text="x", namespace="ns")
    assert r.supersede(old_ref="a", new_ref="b") == 0
    assert r.retract(stele_ref="a") == 0
    assert r.search_current("q", namespace="ns", limit=5,
                            retracted_behavior="surface_both",
                            version_filter=None) == []
    assert r.search_as_of("q", namespace="ns", limit=5,
                          as_of=datetime.now(UTC),
                          retracted_behavior="hide",
                          version_filter=None) == []
    assert r.purge_namespace("ns") == 0
    r.close()
