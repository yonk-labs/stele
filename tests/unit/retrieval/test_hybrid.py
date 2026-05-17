"""Hybrid retrieval facade (SC-013, SC-022). No chunkshop import."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord, SearchHit
from stele.core.config import IndexingConfig
from stele.retrieval.hybrid import hybrid_search
from stele.storage.chunk_store.memory import InProcessChunkStore


def _artifact(text: str, aid: str) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=aid,
        reference=f"stele://default/{aid}",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=len(text.split()),
        summary=text[:80],
        digest_sha256="x" * 64,
        metadata={},
        created_at=datetime.now(UTC),
    )


def _store() -> InProcessChunkStore:
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("user prefers dark mode for the analytics dashboard", "aid_a"))
    store.write(_artifact("the database migration deadline is the end of june", "aid_b"))
    store.write(_artifact("dark mode also affects the migration report colors", "aid_c"))
    return store


def test_hybrid_rrf_default_merges_both_sources() -> None:
    hits = hybrid_search(_store(), "dark mode migration", limit=5)
    assert hits
    assert all(h.retrieval_mode == "hybrid" for h in hits)
    assert all(h.metadata.get("sources") == ["keyword", "vector"] for h in hits)
    # No duplicate (artifact_id, chunk_id) pairs.
    keys = [(h.artifact_id, h.chunk_id) for h in hits]
    assert len(keys) == len(set(keys))
    # Sorted descending by fused score.
    assert hits == sorted(hits, key=lambda h: h.score, reverse=True)


def test_hybrid_weighted_sum_method() -> None:
    hits = hybrid_search(
        _store(),
        "dark mode",
        limit=5,
        method="weighted_sum",
        weights={"keyword": 0.3, "vector": 0.7},
    )
    assert hits
    assert all(h.retrieval_mode == "hybrid" for h in hits)


def test_hybrid_degrades_when_vector_raises() -> None:
    store = _store()

    def _boom(*a: object, **k: object) -> list[SearchHit]:
        raise RuntimeError("vector backend down")

    store.vector_search = _boom  # type: ignore[method-assign]
    hits = hybrid_search(store, "migration", limit=5)
    assert hits, "should degrade to keyword-only, not return empty"
    assert all(h.metadata.get("hybrid_degraded") is True for h in hits)
    assert all(h.metadata.get("sources") == ["keyword"] for h in hits)


def test_hybrid_degrades_when_keyword_raises() -> None:
    store = _store()

    def _boom(*a: object, **k: object) -> list[SearchHit]:
        raise RuntimeError("keyword path down")

    store.keyword_search = _boom  # type: ignore[method-assign]
    hits = hybrid_search(store, "dark mode", limit=5)
    assert hits
    assert all(h.metadata.get("hybrid_degraded") is True for h in hits)
    assert all(h.metadata.get("sources") == ["vector"] for h in hits)


def test_hybrid_returns_empty_when_both_fail() -> None:
    store = _store()

    def _boom(*a: object, **k: object) -> list[SearchHit]:
        raise RuntimeError("down")

    store.vector_search = _boom  # type: ignore[method-assign]
    store.keyword_search = _boom  # type: ignore[method-assign]
    assert hybrid_search(store, "anything", limit=5) == []


def test_hybrid_reference_filter() -> None:
    hits = hybrid_search(_store(), "dark mode", limit=5, reference="stele://default/aid_a")
    assert hits
    assert {h.reference for h in hits} == {"stele://default/aid_a"}
