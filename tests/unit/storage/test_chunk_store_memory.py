"""Tests for InProcessChunkStore — no Chunkshop required."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.storage.chunk_store.memory import InProcessChunkStore


def _artifact(
    text: str, artifact_id: str = "aid1", namespace: str = "default"
) -> ArtifactRecord:
    now = datetime.now(UTC)
    return ArtifactRecord(
        artifact_id=artifact_id,
        reference=f"stele://{namespace}/{artifact_id}",
        namespace=namespace,
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


# --- SC-026: PII boundary assertion semantics (T27) ---

import pytest  # noqa: E402


def test_memory_store_trusts_upstream_pii_scrubbing() -> None:
    """The in-process memory store is the deterministic offline fallback;
    it does NOT re-assert PII — it trusts the upstream Stele PII layer.
    Only chunkshop-backed wrappers do the defensive write-boundary check.
    """
    pytest.skip("memory ChunkStore trusts upstream PII scrubbing by design")


def test_chunkshop_backed_store_asserts_pii_at_write_boundary(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """SC-026: a chunkshop-backed store fails loud on unscrubbed PII."""
    from stele.core.exceptions import BackendError
    from stele.storage.chunk_store.sqlite import SQLiteChunkStore

    store = SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "pii.db"))
    art = _artifact("email the user at jane.doe@example.com about the SSN 123-45-6789")
    with pytest.raises(BackendError, match="PII"):
        store.write(art)
    store.close()


def test_in_process_delete_namespace_drops_target_only() -> None:
    """Per #8b — chunk store must purge by namespace, leaving others intact."""
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("alphacontent only here", artifact_id="aa", namespace="ns_a"))
    store.write(_artifact("alphacontent also here", artifact_id="ab", namespace="ns_a"))
    store.write(_artifact("betacontent elsewhere", artifact_id="ba", namespace="ns_b"))

    removed = store.delete_namespace("ns_a")

    assert removed == 2
    # ns_b survivor intact (unique token).
    assert store.keyword_search("betacontent", limit=5)
    # ns_a's unique token has no remaining hits.
    assert store.keyword_search("alphacontent", limit=5) == []


def test_in_process_delete_namespace_idempotent_when_absent() -> None:
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("solotoken", artifact_id="sa", namespace="ns_a"))
    assert store.delete_namespace("ns_other") == 0
    # Original ns_a row intact.
    assert store.keyword_search("solotoken", limit=5)
