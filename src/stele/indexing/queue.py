"""Synchronous indexers for core and chunked retrieval paths."""

from stele.core.artifact import Artifact, ArtifactRecord
from stele.indexing.chunk_index import ChunkIndex
from stele.indexing.job import IndexJob, IndexResult
from stele.storage.chunk_store.base import ChunkStore


class NoOpIndexer:
    def submit(self, artifact: Artifact) -> IndexJob:
        return IndexJob(artifact_id=artifact.artifact_id, status="skipped")

    def index_now(self, artifact: Artifact) -> IndexResult:
        return IndexResult(artifact_id=artifact.artifact_id, status="skipped")

    def status(self, artifact_id: str) -> IndexResult:
        return IndexResult(artifact_id=artifact_id, status="skipped")


class SyncChunkIndexer:
    def __init__(self, index: ChunkIndex | ChunkStore) -> None:
        # Attr name kept as ``index`` — stash.py + tests reference it.
        self.index = index
        self._status: dict[str, IndexResult] = {}

    def submit(self, artifact: Artifact) -> IndexJob:
        result = self.index_now(ArtifactRecord.model_validate(artifact.model_dump()))
        return IndexJob(artifact_id=artifact.artifact_id, status=result.status)

    def index_now(self, artifact: ArtifactRecord) -> IndexResult:
        try:
            # Only the write call differs: ChunkIndex.index vs ChunkStore.write.
            if isinstance(self.index, ChunkIndex):
                chunk_count = self.index.index(artifact)
            else:
                chunk_count = self.index.write(artifact)
        except Exception as exc:  # pragma: no cover - defensive status path
            result = IndexResult(
                artifact_id=artifact.artifact_id,
                status="failed",
                message=str(exc),
            )
        else:
            result = IndexResult(
                artifact_id=artifact.artifact_id,
                status="indexed",
                message=f"indexed {chunk_count} chunks",
            )
        self._status[artifact.artifact_id] = result
        return result

    def status(self, artifact_id: str) -> IndexResult:
        return self._status.get(artifact_id, IndexResult(artifact_id=artifact_id, status="skipped"))
