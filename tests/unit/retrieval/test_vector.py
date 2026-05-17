"""Vector retrieval facade (SC-012). Backend-agnostic; no chunkshop import."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.retrieval.vector import vector_search
from stele.storage.chunk_store.memory import InProcessChunkStore


def _artifact(text: str, aid: str = "aid1") -> ArtifactRecord:
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
    store.write(_artifact("user prefers dark mode dashboard", aid="aid_a"))
    store.write(_artifact("migration deadline is june", aid="aid_b"))
    return store


def test_vector_search_returns_vector_hits() -> None:
    hits = vector_search(_store(), "dark mode", limit=5)
    assert hits
    assert all(h.retrieval_mode == "vector" for h in hits)
    assert all(0.0 <= h.score <= 1.0 for h in hits)


def test_vector_search_respects_limit() -> None:
    hits = vector_search(_store(), "dark mode migration", limit=1)
    assert len(hits) <= 1


def test_vector_search_reference_filter() -> None:
    hits = vector_search(_store(), "dark mode", limit=5, reference="stele://default/aid_a")
    assert hits
    assert {h.reference for h in hits} == {"stele://default/aid_a"}
