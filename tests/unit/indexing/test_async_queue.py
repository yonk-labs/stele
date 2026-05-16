"""Tests for AsyncChunkIndexer."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord
from stele.indexing.async_queue import AsyncChunkIndexer
from stele.indexing.chunk_index import ChunkIndex
from stele.indexing.queue import SyncChunkIndexer
from stele.indexing.task_backend.in_process import InProcessTaskBackend


def _artifact(text: str = "hello world") -> ArtifactRecord:
    now = datetime.now(UTC)
    return ArtifactRecord(
        artifact_id="aid1",
        reference="stele://default/aid1",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=2,
        summary=text,
        digest_sha256="x" * 64,
        metadata={},
        created_at=now,
    )


def test_async_indexer_queued_then_indexed() -> None:
    from stele.core.config import IndexingConfig

    sync = SyncChunkIndexer(ChunkIndex(IndexingConfig()))
    backend = InProcessTaskBackend(worker=lambda t: sync.index_now(_artifact()))
    indexer = AsyncChunkIndexer(task_backend=backend, sync=sync)
    try:
        result = indexer.submit(_artifact())
        # Per correction sheet: submit returns "queued" (not "pending")
        assert result.status == "queued"
        # Poll status until indexed or failed
        for _ in range(100):
            status = indexer.status(_artifact().artifact_id)
            if status.status in {"indexed", "failed"}:
                break
            time.sleep(0.01)
        final = indexer.status(_artifact().artifact_id)
        assert final.status == "indexed"
    finally:
        backend.close()
