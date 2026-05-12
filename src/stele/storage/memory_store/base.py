"""MemoryStore Protocol — the per-backend contract."""

from __future__ import annotations

from typing import Protocol

from stele.core.memory_record import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
)


class MemoryStore(Protocol):
    def initialize(self) -> None: ...

    def add(
        self,
        record: MemoryRecord,
        supersedes: list[str],
    ) -> tuple[MemoryRecord, list[str]]:
        """Insert record. If supersedes is non-empty, mark those memories
        superseded in the same transaction. Returns (stored_record,
        actually_superseded_ids)."""
        ...

    def search(self, query: MemoryQuery) -> list[MemoryRecord]: ...

    def list(
        self,
        scope: MemoryScope,
        status_filter: list[MemoryStatus] | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]: ...

    def get(self, memory_id: str) -> MemoryRecord | None: ...

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord: ...

    def soft_delete(self, memory_id: str) -> None: ...

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        """Return existing memory_id with matching (scope, text_hash) or None."""
        ...

    def close(self) -> None: ...
