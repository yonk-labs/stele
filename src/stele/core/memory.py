"""Memory facade — public API on top of MemoryStore."""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from stele.core.exceptions import CapabilityError
from stele.core.memory_record import (
    MemoryAddResult,
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    ScoredMemoryHit,
    memory_text_hash,
)
from stele.pii.regex import RegexPIIScrubber
from stele.pii.scrubber import DisabledPIIScrubber
from stele.storage.memory_store.base import MemoryStore


class Memory:
    def __init__(
        self,
        store: MemoryStore,
        scrubber: RegexPIIScrubber | DisabledPIIScrubber,
    ) -> None:
        self._store = store
        self._scrubber = scrubber

    def add(
        self,
        *,
        text: str,
        kind: MemoryKind,
        source_refs: list[str],
        scope: MemoryScope,
        supersedes: list[str] | None = None,
        confidence: float = 1.0,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        scrubbed = self._scrubber.scrub(text)
        now = datetime.now(UTC)
        supersedes_ids = supersedes or []
        record = MemoryRecord(
            id=uuid.uuid4().hex,
            text=scrubbed.text,
            kind=kind,
            scope=scope,
            source_refs=source_refs,
            supersedes=supersedes_ids,
            confidence=confidence,
            created_at=now,
            updated_at=now,
            effective_from=now,
            metadata=metadata or {},
            pii_flags=sorted({d.entity_type for d in scrubbed.detections}),
        )
        dup_id = self._store.find_duplicate(
            scope, memory_text_hash(record.text, scope)
        )
        stored, superseded_ids = self._store.add(record, supersedes_ids)
        return MemoryAddResult(
            record=stored,
            duplicate_of=dup_id,
            superseded_ids=superseded_ids,
        )

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        return self._store.search(query)

    def list(
        self,
        scope: MemoryScope,
        status_filter: list[MemoryStatus] | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        return self._store.list(scope, status_filter, limit)

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._store.get(memory_id)

    def update(
        self,
        memory_id: str,
        *,
        text: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryRecord:
        if text is not None:
            raise CapabilityError(
                "text edits must use add(supersedes=[id]); update() preserves history"
            )
        if metadata is None:
            existing = self._store.get(memory_id)
            if existing is None:
                from stele.core.exceptions import ArtifactNotFound

                raise ArtifactNotFound(f"memory not found: {memory_id}")
            return existing
        return self._store.update_metadata(memory_id, metadata)

    def delete(self, memory_id: str) -> None:
        self._store.soft_delete(memory_id)

    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> builtins.list[ScoredMemoryHit]:
        return self._store.search_with_score(
            query,
            scope,
            limit=limit,
            source_ref_filter=source_ref_filter,
        )

    def close(self) -> None:
        self._store.close()
