"""MemoryStore Protocol — the per-backend contract."""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Protocol

from stele.core.memory_record import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    ScoredMemoryHit,
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
        *,
        as_of: datetime | None = None,
    ) -> list[MemoryRecord]:
        """When ``as_of`` is set, return records that were VALID at that
        time (``effective_from <= as_of`` AND ``effective_until > as_of``
        or NULL), regardless of CURRENT status — so a record retracted or
        superseded after ``as_of`` still appears in the historical view.
        If ``status_filter`` is also supplied, it composes on top
        (current status must match too). Default ``as_of=None`` keeps the
        existing current-view behavior unchanged."""
        ...

    def get(self, memory_id: str) -> MemoryRecord | None: ...

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord: ...

    def soft_delete(self, memory_id: str) -> None: ...

    def set_retracted(self, memory_id: str, retracted_at: datetime) -> None:
        """Set status='retracted' and effective_until=retracted_at. Raises
        ArtifactNotFound if absent. Additive Phase-5 surface."""
        ...

    def delete_namespace(self, namespace: str) -> int:
        """Hard-delete every memory row in ``namespace``. Returns the count
        removed. Idempotent. Other namespaces are never touched.

        Used by :meth:`Stele.purge_namespace` for GDPR-style lifecycle ops.
        Unlike :meth:`purge_superseded`, this drops live and historical
        rows alike — namespace purge is a deliberate forget."""
        ...

    def purge_superseded(self, before: datetime) -> int:
        """Hard-delete memory rows with status='superseded' AND
        effective_until strictly before ``before``. Returns the count
        removed. Records still valid, active, or superseded-but-recent
        (effective_until >= before, or NULL) are untouched. This is the
        only primitive that destroys history — callers bound it with an
        explicit retention horizon."""
        ...

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        """Return existing memory_id with matching (scope, text_hash) or None."""
        ...

    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> builtins.list[ScoredMemoryHit]:
        """Like search, but returns hits with normalized score in [0, 1].

        source_ref_filter: when set, hits are filtered (in the backend) to
        memories whose source_refs include this URI. None = no filter.
        """
        ...

    def close(self) -> None: ...
