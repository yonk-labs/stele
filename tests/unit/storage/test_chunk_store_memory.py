"""Tests for InProcessChunkStore — no Chunkshop required."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.storage.chunk_store.memory import InProcessChunkStore


def _artifact(text: str, artifact_id: str = "aid1") -> ArtifactRecord:
    now = datetime.now(UTC)
    return ArtifactRecord(
        artifact_id=artifact_id,
        reference=f"stele://default/{artifact_id}",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=len(text.split()),
        summary=text[:200],
        digest_sha256="x" * 64,
        metadata={},
        created_at=now,
    )


def test_in_process_write_and_vector_search() -> None:
    store = InProcessChunkStore(IndexingConfig())
    n = store.write(_artifact("user prefers dark mode for the dashboard"))
    assert n >= 1
    hits = store.vector_search("dark mode", limit=5)
    assert hits, "vector search should hit on lexical proximity (hash embedder is deterministic)"
    assert all(0.0 <= h.score <= 1.0 for h in hits)
    assert all(h.retrieval_mode == "vector" for h in hits)


def test_in_process_keyword_search() -> None:
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("the migration deadline is june 30"))
    hits = store.keyword_search("migration", limit=5)
    assert hits
    assert "migration" in hits[0].text.lower()
    assert hits[0].retrieval_mode == "keyword"


def test_in_process_embed_dim_consistent() -> None:
    store = InProcessChunkStore(IndexingConfig())
    a = store.embed("hello")
    b = store.embed("world")
    assert len(a) == len(b)
    assert store.dim == len(a)


def test_in_process_reference_filter() -> None:
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("apple banana cherry", artifact_id="aid_a"))
    store.write(_artifact("apple banana cherry", artifact_id="aid_b"))
    hits = store.vector_search("apple", limit=5, reference="stele://default/aid_a")
    assert hits
    for h in hits:
        assert h.reference == "stele://default/aid_a"


def test_in_process_delete() -> None:
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("apple banana cherry", artifact_id="aid_a"))
    store.delete("stele://default/aid_a")
    assert store.vector_search("apple", limit=5) == []


def test_in_process_surface() -> None:
    store = InProcessChunkStore(IndexingConfig())
    assert store.name == "memory"
    assert store.similarity == "cosine"
    # Structural ChunkStore surface: required callables present.
    for attr in ("write", "delete", "keyword_search", "vector_search", "embed", "close"):
        assert callable(getattr(store, attr))
