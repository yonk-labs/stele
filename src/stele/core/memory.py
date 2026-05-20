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
from stele.revisor.base import NoOpRevisor, Revisor
from stele.storage.memory_store.base import MemoryStore


class Memory:
    def __init__(
        self,
        store: MemoryStore,
        scrubber: RegexPIIScrubber | DisabledPIIScrubber,
        *,
        revisor: Revisor | None = None,
    ) -> None:
        self._store = store
        self._scrubber = scrubber
        self._revisor: Revisor = revisor if revisor is not None else NoOpRevisor()

    @staticmethod
    def _mem_ref(record: MemoryRecord) -> str:
        return f"stele://{record.scope.namespace}/mem-{record.id}"

    @staticmethod
    def _evidence_ref(record: MemoryRecord) -> str:
        """Stable pg-raggraph documents.source_path for this memory.

        Memory.add enforces source_refs non-empty, so source_refs[0] is
        normally the path. The synthetic mem-ref is a defensive fallback.
        ALL revisor operations (ingest, supersede, retract) must use the
        SAME ref so pg-raggraph's joins find the same row. Issue #4: the
        BUG-4 fix flipped only the supersede side to source_refs[0];
        this routes ingest + retract through the same choice."""
        if record.source_refs:
            return record.source_refs[0]
        return Memory._mem_ref(record)

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
        if self._revisor.active:
            self._revisor.ingest_evidence(
                stele_ref=self._evidence_ref(stored),
                text=stored.text,
                namespace=stored.scope.namespace,
                effective_from=stored.effective_from,
                session_id=stored.scope.session_id,
                extra={"source_refs": list(stored.source_refs)},
            )
            for old_id in superseded_ids:
                old = self._store.get(old_id)
                if old is None:
                    continue
                # BUG-4: project the real evidence-document ref (not a
                # synthetic mem- ref) into the graph supersede edge. Known
                # limitation: a multi-source memory contributes only its
                # FIRST source_ref to the edge — the graph models one
                # old→new document supersession, not a fan-out across every
                # cited source. Acceptable: the primary citation carries the
                # supersession; secondary refs remain queryable as evidence.
                old_doc_ref = old.source_refs[0] if old.source_refs else None
                new_doc_ref = stored.source_refs[0] if stored.source_refs else None
                if old_doc_ref is not None and new_doc_ref is not None:
                    self._revisor.supersede(
                        old_ref=old_doc_ref,
                        new_ref=new_doc_ref,
                        reason="superseded",
                    )
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
        *,
        as_of: datetime | None = None,
    ) -> list[MemoryRecord]:
        return self._store.list(scope, status_filter, limit, as_of=as_of)

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

    def retract(
        self,
        memory_id: str,
        *,
        reason: str = "",
        retracted_at: datetime | None = None,
    ) -> MemoryRecord:
        """Mark a memory retracted (additive Phase-5 surface). Sets
        status='retracted' + effective_until, and projects to the Revisor
        when one is configured. Memory is truth; the graph mirrors it."""
        existing = self._store.get(memory_id)
        if existing is None:
            from stele.core.exceptions import ArtifactNotFound

            raise ArtifactNotFound(f"memory not found: {memory_id}")
        when = retracted_at or datetime.now(UTC)
        self._store.set_retracted(memory_id, when)
        if self._revisor.active:
            self._revisor.retract(
                stele_ref=self._evidence_ref(existing),
                reason=reason,
                retracted_at=when,
            )
        updated = self._store.get(memory_id)
        assert updated is not None
        return updated

    def purge_superseded(self, before: datetime) -> int:
        """Hard-delete superseded memories whose validity window ended
        strictly before ``before``. Returns the count removed.

        This forfeits ``as_of`` time-travel for anything before the
        horizon — by design. Callers (operators) opt in with an explicit
        cutoff; there is no automatic default. See Stele.cleanup()."""
        return self._store.purge_superseded(before)

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
