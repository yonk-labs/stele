"""AsyncChunkIndexer — submits to TaskBackend, tracks per-artifact status."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from stele.core.artifact import Artifact, ArtifactRecord
from stele.core.types import IndexStatus
from stele.indexing.job import IndexResult
from stele.indexing.queue import SyncChunkIndexer
from stele.indexing.task_backend.base import IndexTask, TaskBackend


class AsyncChunkIndexer:
    def __init__(
        self,
        *,
        task_backend: TaskBackend,
        sync: SyncChunkIndexer,
    ) -> None:
        self._task_backend = task_backend
        self._sync = sync
        self._lock = threading.Lock()
        self._artifact_to_task: dict[str, str] = {}

    def submit(self, artifact: Artifact | ArtifactRecord) -> IndexResult:
        task = IndexTask(
            artifact_id=artifact.artifact_id,
            reference=artifact.reference,
            namespace=artifact.namespace,
            submitted_at=datetime.now(UTC),
        )
        task_id = self._task_backend.submit(task)
        with self._lock:
            self._artifact_to_task[artifact.artifact_id] = task_id
        return IndexResult(
            artifact_id=artifact.artifact_id,
            status="queued",
            message=f"task_id={task_id}",
        )

    def status(self, artifact_id: str) -> IndexResult:
        with self._lock:
            task_id = self._artifact_to_task.get(artifact_id)
        if task_id is None:
            return self._sync.status(artifact_id)
        ts = self._task_backend.status(task_id)
        # Map TaskStatus.state → IndexStatus
        # pending/running in TaskBackend → "queued" in IndexStatus
        # succeeded → "indexed", failed → "failed"
        state_map: dict[str, IndexStatus] = {
            "pending": "queued",
            "running": "queued",
            "succeeded": "indexed",
            "failed": "failed",
        }
        return IndexResult(
            artifact_id=artifact_id,
            status=state_map[ts.state],
            message=ts.message,
        )

    def close(self) -> None:
        self._task_backend.close()
