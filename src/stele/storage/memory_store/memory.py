"""In-process MemoryStore — dict-backed, for tests and the memory backend."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    ScoredMemoryHit,
    canonical_scope_key,
    memory_text_hash,
)


def _scope_matches(record_scope: MemoryScope, query_scope: MemoryScope) -> bool:
    for field in ("user_id", "agent_id", "app_id", "session_id"):
        q = getattr(query_scope, field)
        if q is not None and getattr(record_scope, field) != q:
            return False
    return record_scope.namespace == query_scope.namespace


def _is_valid_at(record: MemoryRecord, when: datetime) -> bool:
    if record.effective_from > when:
        return False
    return record.effective_until is None or record.effective_until > when


def _passes_scope_and_temporal(
    record: MemoryRecord,
    scope: MemoryScope,
    as_of: datetime,
    *,
    include_superseded: bool,
) -> bool:
    """Single scope + temporal predicate shared by ``search`` and
    ``search_with_score`` so the two can never re-diverge (BUG-1: a copy
    of this logic in ``search_with_score`` once used strict full-scope
    equality + a status='active'-only filter and silently dropped
    in-scope / still-valid rows). One definition, one behavior."""
    if not _scope_matches(record.scope, scope):
        return False
    if record.status == "deleted":
        return False
    if not _is_valid_at(record, as_of):
        return False
    return not (
        not include_superseded
        and record.status == "superseded"
        and (record.effective_until is None or record.effective_until <= as_of)
    )


class InProcessMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def initialize(self) -> None:
        return None

    def add(
        self,
        record: MemoryRecord,
        supersedes: list[str],
    ) -> tuple[MemoryRecord, list[str]]:
        actually_superseded: list[str] = []
        now = datetime.now(UTC)
        for old_id in supersedes:
            existing = self._records.get(old_id)
            if existing is None:
                raise ArtifactNotFound(f"memory not found: {old_id}")
            updated = existing.model_copy(
                update={
                    "status": "superseded",
                    "effective_until": now,
                    "updated_at": now,
                }
            )
            self._records[old_id] = updated
            actually_superseded.append(old_id)
        self._records[record.id] = record
        return record, actually_superseded

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        as_of = query.as_of or datetime.now(UTC)
        results: list[MemoryRecord] = []
        q_lower = query.query.lower()
        for r in self._records.values():
            if not _passes_scope_and_temporal(
                r, query.scope, as_of, include_superseded=query.include_superseded
            ):
                continue
            if q_lower not in r.text.lower():
                continue
            results.append(r)
        return results[: query.limit]

    def list(
        self,
        scope: MemoryScope,
        status_filter: list[MemoryStatus] | None = None,
        limit: int = 100,
        *,
        as_of: datetime | None = None,
    ) -> list[MemoryRecord]:
        if as_of is None:
            effective_filter: list[MemoryStatus] = (
                status_filter if status_filter is not None else ["active", "superseded"]
            )
            out: list[MemoryRecord] = []
            for r in self._records.values():
                if not _scope_matches(r.scope, scope):
                    continue
                if r.status not in effective_filter:
                    continue
                out.append(r)
            return out[:limit]
        # Time-travel view (issue #3 — late-binding filter trap fix):
        # accept anything valid at `as_of` regardless of current status,
        # then compose with an explicit status_filter when supplied.
        # ``include_superseded=True`` selects "scope + not deleted +
        # is_valid_at(as_of)" — exactly the historical-view predicate.
        out2: list[MemoryRecord] = []
        for r in self._records.values():
            if not _passes_scope_and_temporal(
                r, scope, as_of, include_superseded=True
            ):
                continue
            if status_filter is not None and r.status not in status_filter:
                continue
            out2.append(r)
        return out2[:limit]

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._records.get(memory_id)

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord:
        existing = self._records.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        merged = dict(existing.metadata)
        merged.update(metadata_patch)
        updated = existing.model_copy(
            update={"metadata": merged, "updated_at": datetime.now(UTC)}
        )
        self._records[memory_id] = updated
        return updated

    def soft_delete(self, memory_id: str) -> None:
        existing = self._records.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self._records[memory_id] = existing.model_copy(
            update={"status": "deleted", "updated_at": datetime.now(UTC)}
        )

    def set_retracted(self, memory_id: str, retracted_at: datetime) -> None:
        existing = self._records.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self._records[memory_id] = existing.model_copy(
            update={
                "status": "retracted",
                "effective_until": retracted_at,
                "updated_at": datetime.now(UTC),
            }
        )

    def purge_superseded(self, before: datetime) -> int:
        # Predicate: status='superseded' AND effective_until < before.
        to_remove = [
            mid
            for mid, r in self._records.items()
            if r.status == "superseded"
            and r.effective_until is not None
            and r.effective_until < before
        ]
        for mid in to_remove:
            del self._records[mid]
        return len(to_remove)

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        target_scope = canonical_scope_key(scope)
        for r in self._records.values():
            if r.status in {"deleted", "superseded"}:
                continue
            if canonical_scope_key(r.scope) != target_scope:
                continue
            if memory_text_hash(r.text, r.scope) == text_hash:
                return r.id
        return None

    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> builtins.list[ScoredMemoryHit]:
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return []
        # Newest-valid view (as_of = now, include_superseded = False) via
        # the shared predicate so this never diverges from search(). BUG-1.
        as_of = datetime.now(UTC)
        candidates: list[tuple[MemoryRecord, int]] = []
        for record in self._records.values():
            if not _passes_scope_and_temporal(
                record, scope, as_of, include_superseded=False
            ):
                continue
            if source_ref_filter is not None and source_ref_filter not in record.source_refs:
                continue
            text_lower = record.text.lower()
            score = sum(text_lower.count(t) for t in terms)
            if score > 0:
                candidates.append((record, score))
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        top = candidates[:limit]
        if not top:
            return []
        max_score = max(s for _, s in top) or 1
        return [
            ScoredMemoryHit(record=rec, score=raw / max_score) for rec, raw in top
        ]

    def close(self) -> None:
        return None
