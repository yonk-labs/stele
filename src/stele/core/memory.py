"""Memory facade — public API on top of MemoryStore."""

from __future__ import annotations

import builtins
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from stele.core import reuse as _reuse
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import (
    AddRequest,
    MemoryAddResult,
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    ScoredMemoryHit,
    evolved_confidence,
    memory_text_hash,
    parse_event_date,
)
from stele.pii.regex import RegexPIIScrubber
from stele.pii.scrubber import DisabledPIIScrubber
from stele.revisor.base import NoOpRevisor, Revisor
from stele.storage.memory_store.base import MemoryStore


@dataclass(frozen=True)
class ReuseResult:
    """Verdict from :meth:`Memory.reuse_outcome`: whether a cached outcome is still valid to
    reuse, the candidate record it judged (None on a cache miss), and why."""

    reuse: bool
    record: MemoryRecord | None
    reason: str  # "fingerprint-match" | "drift" | "reused-noise" | "not-worth-reuse"
    #            | "expired" | "miss"


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

    def _scrub_optional(self, value: str | None, flags: set[str]) -> str | None:
        """Scrub an optional tripartite field, folding any PII entity types
        into the shared flag set. None passes through untouched."""
        if value is None:
            return None
        scrubbed = self._scrubber.scrub(value)
        flags.update(d.entity_type for d in scrubbed.detections)
        return scrubbed.text

    def add(
        self,
        *,
        text: str,
        kind: MemoryKind,
        source_refs: list[str],
        scope: MemoryScope,
        summary: str | None = None,
        detail: str | None = None,
        action: str | None = None,
        supersedes: list[str] | None = None,
        confidence: float = 1.0,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        scrubbed = self._scrubber.scrub(text)
        flags: set[str] = {d.entity_type for d in scrubbed.detections}
        s_summary = self._scrub_optional(summary, flags)
        s_detail = self._scrub_optional(detail, flags)
        s_action = self._scrub_optional(action, flags)
        now = datetime.now(UTC)
        supersedes_ids = supersedes or []
        meta = metadata or {}
        # Valid-time, not write-time: a fact carrying metadata.event_date (#88)
        # became TRUE then, even though it is being written now. Without this,
        # as_of time-travel over a backfilled/imported chain returns nothing,
        # because every row's validity starts at ingest (#90).
        effective_from = parse_event_date(meta.get("event_date")) or now
        record = MemoryRecord(
            id=uuid.uuid4().hex,
            text=scrubbed.text,
            summary=s_summary,
            detail=s_detail,
            action=s_action,
            kind=kind,
            scope=scope,
            source_refs=source_refs,
            supersedes=supersedes_ids,
            confidence=confidence,
            created_at=now,
            updated_at=now,
            effective_from=effective_from,
            metadata=dict(meta),
            pii_flags=sorted(flags),
        )
        dup_id = self._store.find_duplicate(
            scope, memory_text_hash(record.text, scope)
        )
        # Re-observation: the exact assertion already exists in-scope and the
        # caller isn't superseding anything, so confirm the existing row
        # (bump confirmations, evolve confidence) instead of inserting a twin.
        # The asserted text is immutable; only its evidence moves. The
        # evidence doc was ingested into the revisor on first write, so we
        # don't re-ingest here.
        if dup_id is not None and not supersedes_ids:
            existing = self._store.get(dup_id)
            if existing is not None:
                target = evolved_confidence(
                    existing.confidence, existing.confirmations + 1
                )
                confirmed = self._store.confirm(
                    dup_id, at=now, new_confidence=max(target, confidence)
                )
                return MemoryAddResult(record=confirmed, duplicate_of=dup_id)
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

    def record_outcome(
        self,
        *,
        text: str,
        source_refs: list[str],
        scope: MemoryScope,
        env: dict[str, str],
        declared_deps: list[str] | None = None,
        fingerprint_dims: tuple[str, ...] | None = None,
        cost: dict[str, object] | None = None,
        ttl_seconds: float | None = None,
        summary: str | None = None,
        supersedes: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        """Store a cached multi-step OUTCOME with the canary anchors needed to reuse it safely:
        a broad fingerprint of ``env`` (the validity gate), the declared dependency set plus its
        values at derivation (for the later tiered narrow check), an optional cost spine, and an
        optional ``ttl_seconds`` (the time bound on the canary's semantic blind spot; ``None`` =
        no expiry, the back-compatible default). The anchors live in ``metadata`` so they
        round-trip on every backend. Reuse is decided later by :meth:`reuse_outcome`."""
        declared = list(declared_deps or [])
        # store the FULL env at derivation as the baseline, so a dimension learned later
        # (promoted into the declared set) already has its derivation value to compare against.
        deps_at_derivation = dict(env)
        meta: dict[str, object] = dict(metadata or {})
        meta[_reuse.META_FINGERPRINT] = _reuse.fingerprint(env, fingerprint_dims)
        if fingerprint_dims is not None:
            meta[_reuse.META_FINGERPRINT_DIMS] = list(fingerprint_dims)
        meta[_reuse.META_DECLARED_DEPS] = declared
        meta[_reuse.META_DEPS_AT_DERIVATION] = deps_at_derivation
        if cost is not None:
            meta[_reuse.META_COST] = cost
        if ttl_seconds is not None:
            meta[_reuse.META_TTL] = ttl_seconds
        return self.add(
            text=text,
            kind="outcome",
            source_refs=source_refs,
            scope=scope,
            summary=summary,
            supersedes=supersedes,
            metadata=meta,
        )

    def record_procedure(
        self,
        *,
        text: str,
        intent: str,
        source_refs: list[str],
        scope: MemoryScope,
        env: dict[str, str] | None = None,
        summary: str | None = None,
        supersedes: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        """Store a learned PROCEDURE (the steps for a workflow) so recall.shortcut can return it
        as advisory steps to re-run. ``intent`` is the trigger this procedure answers (kept for
        routing/diagnostics); ``env`` is an optional applicability snapshot at recording time so a
        later recall can flag env drift. No validity gate: the procedure tier is advisory, the
        agent re-runs the steps."""
        meta: dict[str, object] = dict(metadata or {})
        meta[_reuse.META_INTENT] = intent
        if env is not None:
            meta[_reuse.META_ENV] = dict(env)
        return self.add(
            text=text,
            kind="procedure",
            source_refs=source_refs,
            scope=scope,
            summary=summary,
            supersedes=supersedes,
            metadata=meta,
        )

    def record_context(
        self,
        *,
        text: str,
        source_ref: str,
        source: str,
        intent: str,
        scope: MemoryScope,
        ttl_seconds: float | None = None,
        summary: str | None = None,
        supersedes: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        """Store recalled CONTEXT (what a source is/does) with the freshness anchors
        recall.shortcut needs: a content hash of ``source`` (the observable-drift gate) and an
        optional ``ttl_seconds`` backstop. ``intent`` is the trigger this context answers
        (routing/diagnostics). Freshness is decided later by :func:`reuse.is_stale`."""
        meta: dict[str, object] = dict(metadata or {})
        meta[_reuse.META_INTENT] = intent
        meta[_reuse.META_SOURCE_HASH] = _reuse.source_hash(source)
        if ttl_seconds is not None:
            meta[_reuse.META_TTL] = ttl_seconds
        return self.add(
            text=text,
            kind="observation",
            source_refs=[source_ref],
            scope=scope,
            summary=summary,
            supersedes=supersedes,
            metadata=meta,
        )

    def _latest_outcome(self, scope: MemoryScope) -> MemoryRecord | None:
        """The most recent active outcome in scope (the current cached result to test)."""
        active_only: list[MemoryStatus] = ["active"]
        rows = self.list(scope, status_filter=active_only, limit=1000)
        outcomes = [r for r in rows if r.kind == "outcome"]
        if not outcomes:
            return None
        return max(outcomes, key=lambda r: r.created_at)

    def _outcome_candidates(
        self, scope: MemoryScope, intent: str | None, *, top_n: int = 5
    ) -> builtins.list[MemoryRecord]:
        """The outcomes to test, best-first. With an ``intent``, route by semantic match over
        kind=outcome (so a broad scope cannot reuse an unrelated task's result); without one,
        the single latest-in-scope outcome (back-compatible)."""
        if intent is None:
            latest = self._latest_outcome(scope)
            return [latest] if latest is not None else []
        hits = self.search_with_score(intent, scope, limit=top_n, kind_filter="outcome")
        return [h.record for h in hits]

    def _gate_outcome(
        self,
        candidate: MemoryRecord,
        env: dict[str, str],
        mode: str,
        now: datetime | None,
    ) -> ReuseResult:
        """Apply the TTL backstop then the canary/tiered fingerprint gate to ONE outcome. TTL is
        checked first: an outcome aged past it returns ``"expired"`` regardless of fingerprint."""
        meta = candidate.metadata
        ttl_raw = meta.get(_reuse.META_TTL)
        ttl = (
            ttl_raw
            if isinstance(ttl_raw, (int, float)) and not isinstance(ttl_raw, bool)
            else None
        )
        when = now if now is not None else datetime.now(UTC)
        if _reuse.is_expired(candidate.created_at, ttl, when):
            return ReuseResult(reuse=False, record=candidate, reason="expired")
        stored_fp = meta.get(_reuse.META_FINGERPRINT)
        dims_raw = meta.get(_reuse.META_FINGERPRINT_DIMS)
        dims = tuple(str(d) for d in dims_raw) if isinstance(dims_raw, list) else None
        cost_raw = meta.get(_reuse.META_COST)
        cost: dict[str, object] | None = cost_raw if isinstance(cost_raw, dict) else None
        if mode == "tiered":
            declared_raw = meta.get(_reuse.META_DECLARED_DEPS)
            declared = (
                [str(d) for d in declared_raw] if isinstance(declared_raw, list) else []
            )
            deps_raw = meta.get(_reuse.META_DEPS_AT_DERIVATION)
            deps_at: dict[str, object] = deps_raw if isinstance(deps_raw, dict) else {}
            decision = _reuse.decide_tiered(stored_fp, dims, declared, deps_at, env, cost)
        else:
            decision = _reuse.decide_canary(stored_fp, env, dims, cost)
        return ReuseResult(reuse=decision.reuse, record=candidate, reason=decision.reason)

    def reuse_outcome(
        self,
        scope: MemoryScope,
        env: dict[str, str],
        *,
        mode: str = "canary",
        now: datetime | None = None,
        intent: str | None = None,
    ) -> ReuseResult:
        """Decide whether a cached outcome in ``scope`` is still valid to reuse under ``env``.

        **Experimental, opt-in.** Real-coding value is unproven (see
        ``docs/measurements/agent-memory-research-summary.md``). Never invoked by the default
        recall path (``recall.default_strategy="adaptive"``); call it explicitly to use it.

        With ``intent``, candidate outcomes are routed by intent (semantic match over
        kind=outcome) and gated best-first; the first that reuses wins, so a broad scope cannot
        reuse an unrelated task's result. Without ``intent``, the latest-in-scope outcome is gated
        (back-compatible). ``canary`` reuses only when the stored broad fingerprint is unchanged;
        ``tiered`` adds a narrow check that reuses an undeclared-only trip (``reused-noise``). A
        recorded TTL is checked FIRST (``"expired"`` beats a fingerprint match). ``now`` defaults
        to the current UTC time. Returns reuse=False reason ``"miss"`` when nothing is cached."""
        if mode not in ("canary", "tiered"):
            raise ValueError(f"unknown reuse mode: {mode!r}")
        candidates = self._outcome_candidates(scope, intent)
        if not candidates:
            return ReuseResult(reuse=False, record=None, reason="miss")
        result = ReuseResult(reuse=False, record=None, reason="miss")
        for candidate in candidates:
            result = self._gate_outcome(candidate, env, mode, now)
            if result.reuse:
                return result
        return result  # no candidate reused: the best candidate's reason (drift/expired/...)

    def learn_dependencies(self, record_id: str, env: dict[str, str]) -> MemoryRecord:
        """Teach a cached outcome a dependency it under-declared, from a reuse that proved
        stale. Any dimension whose value at ``env`` differs from the derivation baseline and is
        not already declared is promoted into the declared set, so future ``tiered`` checks
        re-derive on that dimension instead of reusing through it. This is the post-miss
        learning loop, driven by caller-supplied detection (stele has no oracle of its own)."""
        rec = self.get(record_id)
        if rec is None:
            raise KeyError(f"no memory with id {record_id!r}")
        declared_raw = rec.metadata.get(_reuse.META_DECLARED_DEPS)
        declared = [str(d) for d in declared_raw] if isinstance(declared_raw, list) else []
        deps_raw = rec.metadata.get(_reuse.META_DEPS_AT_DERIVATION)
        deps_at: dict[str, object] = deps_raw if isinstance(deps_raw, dict) else {}
        missed = [
            d for d in env if d not in declared and str(env.get(d)) != str(deps_at.get(d))
        ]
        if not missed:
            return rec
        return self.update_metadata(
            record_id, {_reuse.META_DECLARED_DEPS: declared + missed}
        )

    def add_many(self, items: list[AddRequest]) -> list[MemoryAddResult]:
        """Insert N memories. Returns per-row :class:`MemoryAddResult` in
        input order.

        Observably equivalent to N sequential :meth:`add` calls, including
        the re-observation merge: a row whose exact assertion already exists
        in-scope (pre-existing OR earlier in this same batch) confirms that
        row instead of inserting a twin, unless it is superseding something.
        Non-duplicate rows are inserted in one store transaction; confirms
        are applied after (a duplicate of a within-batch row must wait for
        that row to land). Revisor projection fires only for inserts."""
        if not items:
            return []
        now = datetime.now(UTC)
        # Plan per row: either ("insert", record) or ("confirm", target_id).
        plans: list[tuple[str, MemoryRecord | str]] = []
        first_insert_by_hash: dict[str, str] = {}
        for item in items:
            scrubbed = self._scrubber.scrub(item.text)
            flags: set[str] = {d.entity_type for d in scrubbed.detections}
            record = MemoryRecord(
                id=uuid.uuid4().hex,
                text=scrubbed.text,
                summary=self._scrub_optional(item.summary, flags),
                detail=self._scrub_optional(item.detail, flags),
                action=self._scrub_optional(item.action, flags),
                kind=item.kind,
                scope=item.scope,
                source_refs=item.source_refs,
                supersedes=list(item.supersedes),
                confidence=item.confidence,
                created_at=now,
                updated_at=now,
                effective_from=parse_event_date(item.metadata.get("event_date")) or now,
                metadata=dict(item.metadata),
                pii_flags=sorted(flags),
            )
            text_hash = memory_text_hash(record.text, item.scope)
            supersedes_ids = list(item.supersedes)
            target = None
            if not supersedes_ids:
                target = first_insert_by_hash.get(text_hash) or (
                    self._store.find_duplicate(item.scope, text_hash)
                )
            if target is not None:
                plans.append(("confirm", target))
            else:
                plans.append(("insert", record))
                first_insert_by_hash[text_hash] = record.id

        # One transaction for the inserts; preserves the batch guarantee for
        # the rows that actually create new assertions.
        insert_items = [
            (rec, list(rec.supersedes))
            for kind, rec in plans
            if kind == "insert" and isinstance(rec, MemoryRecord)
        ]
        stored_pairs = self._store.add_many(insert_items)
        stored_by_id = {rec.id: (rec, sup) for rec, sup in stored_pairs}

        results: list[MemoryAddResult] = []
        for kind, payload in plans:
            if kind == "confirm" and isinstance(payload, str):
                existing = self._store.get(payload)
                conf = (
                    existing.confidence if existing is not None else 1.0
                )
                confs = (
                    existing.confirmations if existing is not None else 1
                )
                confirmed = self._store.confirm(
                    payload,
                    at=now,
                    new_confidence=evolved_confidence(conf, confs + 1),
                )
                results.append(
                    MemoryAddResult(record=confirmed, duplicate_of=payload)
                )
                continue
            assert isinstance(payload, MemoryRecord)
            stored, superseded_ids = stored_by_id[payload.id]
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
                    old_doc_ref = old.source_refs[0] if old.source_refs else None
                    new_doc_ref = stored.source_refs[0] if stored.source_refs else None
                    if old_doc_ref is not None and new_doc_ref is not None:
                        self._revisor.supersede(
                            old_ref=old_doc_ref,
                            new_ref=new_doc_ref,
                            reason="superseded",
                        )
            results.append(MemoryAddResult(
                record=stored,
                duplicate_of=None,
                superseded_ids=superseded_ids,
            ))
        return results

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

    def find_precedent(
        self,
        scope: MemoryScope,
        *,
        match: dict[str, object],
        kind: MemoryKind | None = None,
        limit: int = 1000,
    ) -> builtins.list[MemoryRecord]:
        """Active memories in ``scope`` whose ``metadata`` contains all ``match`` pairs.

        The supersession-candidate lookup: a new memory whose identifying attributes
        are ``match`` (e.g. ``{"subject": "deploy_day", "predicate": "is"}``) should
        supersede the records returned here. Pass ``kind`` to restrict to one kind
        (e.g. ``"fact"``). Returns ``[]`` when nothing matches. Absorbs the
        list-active-then-filter glue a consumer would otherwise reimplement to find
        what a new fact replaces.
        """
        # ponytail: O(n) scan over up to `limit` active records in scope — the same
        # cost as the caller-side filter it replaces. Push `match` into the store
        # query if a single scope ever holds enough active memories for it to matter.
        active: builtins.list[MemoryStatus] = ["active"]
        records = self._store.list(scope, active, limit, as_of=None)
        return [
            r
            for r in records
            if (kind is None or r.kind == kind)
            and all((r.metadata or {}).get(k) == v for k, v in match.items())
        ]

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._store.get(memory_id)

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord:
        """Replace a record's metadata (labels/derived index only; never the fact text).
        Used by the registry backfill. Memory text immutability is unaffected."""
        return self._store.update_metadata(memory_id, metadata_patch)

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

    def delete_namespace(self, namespace: str) -> int:
        """Hard-delete every memory row in ``namespace``. Returns the count
        removed. Used by :meth:`Stele.purge_namespace` for GDPR-style
        lifecycle ops — drops live and historical rows alike."""
        return self._store.delete_namespace(namespace)

    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
        kind_filter: str | None = None,
    ) -> builtins.list[ScoredMemoryHit]:
        return self._store.search_with_score(
            query,
            scope,
            limit=limit,
            source_ref_filter=source_ref_filter,
            kind_filter=kind_filter,
        )

    def by_source_ref(
        self,
        scope: MemoryScope,
        ref: str,
        *,
        status_filter: tuple[MemoryStatus, ...] = ("active",),
    ) -> builtins.list[MemoryRecord]:
        """Return in-scope memories whose ``source_refs`` contains ``ref``.

        The episodic back-link: given an episode's artifact ref, the
        memories distilled from it. Active-head only by default; widen
        ``status_filter`` to include superseded/retracted history."""
        return self._store.by_source_ref(scope, ref, status_filter=status_filter)

    def close(self) -> None:
        self._store.close()
