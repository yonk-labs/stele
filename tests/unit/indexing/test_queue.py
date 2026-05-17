"""SyncChunkIndexer writes through a ChunkStore or a ChunkIndex (T20)."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.indexing.chunk_index import ChunkIndex
from stele.indexing.queue import NoOpIndexer, SyncChunkIndexer
from stele.storage.chunk_store.memory import InProcessChunkStore


def _artifact(aid: str = "aid1", text: str = "user prefers dark mode") -> ArtifactRecord:
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


def test_indexes_through_chunk_index() -> None:
    idx = ChunkIndex(IndexingConfig())
    indexer = SyncChunkIndexer(idx)
    result = indexer.index_now(_artifact())
    assert result.status == "indexed"
    assert indexer.status("aid1").status == "indexed"


def test_indexes_through_chunk_store() -> None:
    store = InProcessChunkStore(IndexingConfig())
    indexer = SyncChunkIndexer(store)
    result = indexer.index_now(_artifact("aid_s"))
    assert result.status == "indexed"
    # Chunk store actually received the write.
    assert store.vector_search("dark mode", limit=3)
    assert indexer.status("aid_s").status == "indexed"


def test_submit_preserved() -> None:
    store = InProcessChunkStore(IndexingConfig())
    job = SyncChunkIndexer(store).submit(_artifact("aid_j"))
    assert job.artifact_id == "aid_j"
    assert job.status == "indexed"


def test_failure_path_reports_failed() -> None:
    class Boom:
        def write(self, artifact: ArtifactRecord) -> int:
            raise RuntimeError("backend down")

    indexer = SyncChunkIndexer(Boom())  # type: ignore[arg-type]
    result = indexer.index_now(_artifact("aid_f"))
    assert result.status == "failed"
    assert "backend down" in (result.message or "")


def test_noop_indexer_unchanged() -> None:
    noop = NoOpIndexer()
    assert noop.index_now(_artifact("aid_n")).status == "skipped"
    assert noop.submit(_artifact("aid_n")).status == "skipped"
    assert noop.status("aid_n").status == "skipped"
