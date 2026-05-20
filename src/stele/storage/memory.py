"""In-memory exact artifact storage."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import Artifact, ArtifactRecord, CleanupResult, Page
from stele.core.capabilities import StorageCapabilities
from stele.core.exceptions import ArtifactNotFound
from stele.core.reference import Reference


class MemoryStorageBackend:
    def __init__(self) -> None:
        self._records: dict[str, ArtifactRecord] = {}

    def initialize(self) -> None:
        return None

    def store(self, artifact: Artifact) -> ArtifactRecord:
        record = ArtifactRecord.model_validate(artifact.model_dump())
        self._records[record.reference] = record
        return record

    def fetch(self, reference: Reference) -> ArtifactRecord:
        record = self.try_fetch(reference)
        if record is None:
            raise ArtifactNotFound(f"Artifact not found: {reference.canonical}")
        return record

    def try_fetch(self, reference: Reference) -> ArtifactRecord | None:
        canonical = reference.canonical_without_params
        return self._records.get(canonical)

    def list(
        self,
        *,
        namespace: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[ArtifactRecord]:
        del cursor
        records = sorted(self._records.values(), key=lambda record: record.created_at)
        if namespace is not None:
            records = [record for record in records if record.namespace == namespace]
        if session_id is not None:
            records = [record for record in records if record.session_id == session_id]
        return Page[ArtifactRecord](items=records[:limit], next_cursor=None)

    def delete(self, reference: Reference) -> bool:
        canonical = reference.canonical_without_params
        if canonical in self._records:
            del self._records[canonical]
            return True
        return False

    def delete_namespace(self, namespace: str) -> int:
        to_remove = [k for k, r in self._records.items() if r.namespace == namespace]
        for k in to_remove:
            del self._records[k]
        return len(to_remove)

    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult:
        now = datetime.now(UTC)
        deleted = 0
        for key, record in list(self._records.items()):
            if deleted >= limit:
                break
            if record.expires_at and record.expires_at <= now:
                del self._records[key]
                deleted += 1
        return CleanupResult(deleted_count=deleted)

    def capabilities(self) -> StorageCapabilities:
        return StorageCapabilities(backend_type="memory", durable=False)

    def close(self) -> None:
        self._records.clear()
