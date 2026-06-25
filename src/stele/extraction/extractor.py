"""MemoryExtractor — I/O orchestrator for Phase 2 extraction."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from stele.core.exceptions import (
    ArtifactNotFound,
    CapabilityError,
    SteleError,
    ValidationError,
)
from stele.core.memory_record import MemoryScope, canonical_scope_key
from stele.extraction.candidates import extract_candidates
from stele.extraction.classifier import classify_kind
from stele.extraction.consolidation import (
    SlotKey,
    Slotted,
    is_newer,
    overlap_warnings,
    plan_chains,
    slot_for,
)
from stele.extraction.identity import canonical_subject, canonical_subject_type
from stele.extraction.models import (
    AcceptedCandidate,
    ExtractionReport,
    ExtractionStats,
    MemoryCandidate,
    RejectedCandidate,
)
from stele.extraction.registry import ExistingSubject, SubjectDisambiguationError, resolve_subject

if TYPE_CHECKING:
    from stele.core.config import ExtractionConfig
    from stele.core.memory import Memory
    from stele.core.stash import Stele
    from stele.pii.regex import RegexPIIScrubber
    from stele.pii.scrubber import DisabledPIIScrubber

_log = logging.getLogger(__name__)


def _record_recency(metadata: dict[str, object], effective_from: datetime) -> float:
    mt = metadata.get("session_mtime")
    if isinstance(mt, (int, float)):
        return float(mt)
    return effective_from.timestamp()


def _cross_session_superseded(
    memory: object, lookup_scope: MemoryScope, slot: SlotKey, this_recency: float,
) -> list[str]:
    """Active memories in the SAME slot from other sessions that this session's
    fact supersedes. Bias to false-negatives: exact subject+aspect match AND
    strictly newer (by recency)."""
    out: list[str] = []
    # Ceiling: 500 active records per namespace/slot. Exceeding this limit biases
    # toward false-negatives (cross-session match missed, both facts left active);
    # metadata-indexed query is the upgrade path. Observe via warning log if ceiling hit.
    results = memory.list(lookup_scope, status_filter=["active"], limit=500)  # type: ignore[attr-defined]
    if len(results) == 500:
        _log.warning(
            "cross-session supersession search hit 500-record ceiling for namespace=%s slot=%s; "
            "possible cross-session match missed (false-negative bias)",
            lookup_scope.namespace, slot,
        )
    for r in results:
        meta = r.metadata or {}
        if meta.get("subject_id") != slot.subject_id:
            continue
        if meta.get("aspect") != slot.aspect:
            continue
        if not is_newer(this_recency, _record_recency(meta, r.effective_from)):
            continue
        out.append(r.id)
    return out


def _scope_key_no_session(scope: MemoryScope) -> str:
    # canonical_scope_key is a MODULE FUNCTION in memory_record.py, not a method.
    return canonical_scope_key(scope.model_copy(update={"session_id": None}))


def _active_subjects(memory: object, scope: MemoryScope) -> list[ExistingSubject]:
    lookup = scope.model_copy(update={"session_id": None})
    rows = memory.list(lookup, status_filter=["active"], limit=500)  # type: ignore[attr-defined]
    if len(rows) == 500:
        _log.warning(
            "_active_subjects hit 500-record ceiling for namespace=%s; "
            "some existing subjects may be invisible (false-negative bias)",
            lookup.namespace,
        )
    seen: dict[str, ExistingSubject] = {}
    for r in rows:
        meta = r.metadata or {}
        sid, stype = meta.get("subject_id"), meta.get("subject_type")
        if sid and stype and sid not in seen:
            # normalized_label must match the label that minted subject_id for registry consistency.
            seen[sid] = ExistingSubject(
                sid, stype, canonical_subject(meta.get("canonical_subject", "")),
            )
    return list(seen.values())


def _fingerprint(config: ExtractionConfig) -> str:
    return hashlib.sha256(
        json.dumps(config.model_dump(), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _validate_source_refs(source_refs: list[str]) -> None:
    if not source_refs:
        raise ValidationError(
            "every memory must cite at least one stele:// source_ref"
        )
    for ref in source_refs:
        if not ref.startswith("stele://"):
            raise ValidationError(
                f"source_refs entries must be stele:// URIs, got {ref!r}"
            )


class MemoryExtractor:
    def __init__(
        self,
        *,
        stele: Stele,
        memory: Memory,
        scrubber: RegexPIIScrubber | DisabledPIIScrubber,
        config: ExtractionConfig,
    ) -> None:
        self._stele = stele
        self._memory = memory
        self._scrubber = scrubber
        self._config = config

    def _check_enabled(self) -> None:
        if not self._config.enabled:
            raise CapabilityError("extraction is disabled in config")

    def _run_pure_core(
        self, *, text: str, source_refs: list[str]
    ) -> list[MemoryCandidate]:
        try:
            return extract_candidates(
                text=text,
                source_refs=source_refs,
                scrubber=self._scrubber,
                overlay_enabled=self._config.overlay_patterns_enabled,
                max_candidates=self._config.max_candidates_per_doc,
                extract_rules=self._config.extract_rules,
            )
        except Exception as exc:
            raise SteleError("Extraction failed during lede pass") from exc

    def _verbatim_message_candidates(
        self, messages: list[dict[str, str]]
    ) -> list[MemoryCandidate]:
        """One candidate per substantive message, content kept VERBATIM
        (post-PII-scrub). Lede distillation paraphrases away exact literals
        (dates/names/ids); retaining the raw turn preserves them — Stele's
        exact-evidence thesis and the conversational-recall lever. Not
        capped by max_candidates_per_doc (turns are the evidence). Dedup is
        handled downstream by the memory content-hash."""
        out: list[MemoryCandidate] = []
        for m in messages:
            content = (m.get("content") or "").strip()
            if len(content) < 8:  # skip greetings / acks / empty
                continue
            scrubbed = self._scrubber.scrub(content)
            cls = classify_kind(
                text=scrubbed.text,
                lede_source="key_fact",
                overlay_enabled=self._config.overlay_patterns_enabled,
            )
            out.append(
                MemoryCandidate(
                    text=scrubbed.text,
                    kind=cls.kind,
                    confidence=1.0,  # verbatim source = highest fidelity
                    lede_source="key_fact",
                    classifier_path=cls.classifier_path,
                    pattern_match=cls.pattern_match,
                )
            )
        return out

    def from_text(
        self,
        *,
        text: str,
        source_refs: list[str],
        scope: MemoryScope,
    ) -> ExtractionReport:
        self._check_enabled()
        _validate_source_refs(source_refs)

        candidates = self._run_pure_core(text=text, source_refs=source_refs)
        accepted, rejected = self._commit_candidates(
            candidates=candidates,
            source_refs=source_refs,
            scope=scope,
        )
        return self._build_report(
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            source_refs=source_refs,
        )

    def from_artifact(
        self,
        *,
        artifact_id: str,
        scope: MemoryScope,
    ) -> ExtractionReport:
        self._check_enabled()
        # `artifact_id` may be either a bare id (legacy: assumes default
        # namespace) or a full `stele://<namespace>/<artifact_id>` URI. Accept
        # both so callers that stored into a non-default namespace can extract
        # from those artifacts without rebuilding the ref.
        from stele.core.reference import make_reference

        if "://" in artifact_id:
            ref_uri = artifact_id
        else:
            ref_uri = make_reference("default", artifact_id).canonical_without_params
        try:
            fetched = self._stele.fetch(ref_uri)
        except Exception as exc:
            # Re-raise as ArtifactNotFound if the fetch fails (covers both
            # ReferenceError on malformed IDs and backend not-found).
            raise ArtifactNotFound(f"artifact not found: {artifact_id!r}") from exc
        # FetchResult.reference is already the full stele:// URI.
        source_refs = [fetched.reference]
        text = (
            fetched.content
            if isinstance(fetched.content, str)
            else fetched.content.decode("utf-8", errors="replace")
        )
        candidates = self._run_pure_core(text=text, source_refs=source_refs)
        accepted, rejected = self._commit_candidates(
            candidates=candidates,
            source_refs=source_refs,
            scope=scope,
        )
        return self._build_report(
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            source_refs=source_refs,
        )

    def from_messages(
        self,
        *,
        messages: list[dict[str, str]],
        scope: MemoryScope,
    ) -> ExtractionReport:
        self._check_enabled()
        if not messages:
            return ExtractionReport(
                candidates=[],
                accepted=[],
                rejected=[],
                pii_flags=[],
                source_refs=[],
                stats=ExtractionStats(
                    candidate_count=0, accepted_count=0, rejected_count=0
                ),
                config_fingerprint=_fingerprint(self._config),
            )

        thread_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
        )

        if self._config.auto_stash_messages:
            stored = self._stele.store(thread_text, namespace="default")
            # StoredResult.reference is already the full stele:// URI.
            source_refs = [stored.reference]
        else:
            raise ValidationError(
                "from_messages requires auto_stash_messages=True or pre-stashed messages; "
                "use from_text with explicit source_refs instead"
            )

        candidates = self._run_pure_core(text=thread_text, source_refs=source_refs)
        if self._config.retain_message_text:
            candidates = self._verbatim_message_candidates(messages) + candidates
        accepted, rejected = self._commit_candidates(
            candidates=candidates,
            source_refs=source_refs,
            scope=scope,
        )
        return self._build_report(
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            source_refs=source_refs,
        )

    def from_session(
        self,
        *,
        transcript: object,
        scope: MemoryScope,
        llm: Callable[[str], str],
        max_windows: int = 3,
        source_ref: str | None = None,
        extra_subjects: list[ExistingSubject] | None = None,
    ) -> ExtractionReport:
        """Distill durable memory from a real agent transcript (Claude .jsonl, a
        generic message list, or pre-parsed Turns). The deterministic extractor
        does not fit conversational, tool-heavy transcripts, so this is
        LLM-driven: parse, window (failures first), and ask the injected `llm`
        to extract kinded memories with evidence. Commits via the memory facade
        (PII scrubbing inherited); the transcript is stashed as the source ref.

        `extra_subjects` (#71): caller-supplied subjects unioned with the scope's
        internally-derived active set, for cross-scope identity, a distilled top-N
        past the 500-record ceiling, or a deterministic harness seed. Caller entries
        win on subject_id collision. Default None keeps behaviour unchanged."""
        self._check_enabled()
        from stele.extraction.session import (
            ReduceConfig,
            SessionMemory,
            extract_session_memories,
            parse_transcript,
            render,
            windows,
        )

        # The reduction (keep120 by default) is config-driven, so the stream and
        # the backfill path stay in sync via the same knobs.
        reduce_cfg = ReduceConfig(
            result_chars=self._config.reduce_result_chars,
            error_chars=self._config.reduce_error_chars,
            tool_chars=self._config.reduce_tool_chars,
            drop_success_results=self._config.reduce_drop_success_results,
        )
        turns = parse_transcript(transcript, reduce_cfg)
        empty = ExtractionReport(
            candidates=[], accepted=[], rejected=[], pii_flags=[], source_refs=[],
            stats=ExtractionStats(candidate_count=0, accepted_count=0, rejected_count=0),
            config_fingerprint=_fingerprint(self._config),
        )
        if not turns:
            return empty
        ref = source_ref or str(
            self._stele.store(render(turns)[:200_000], namespace=scope.namespace).reference
        )
        fp = _fingerprint(self._config)
        # session recency, so consolidation can keep the newest of duplicate facts
        session_mtime: float | None = None
        if isinstance(transcript, str | Path):
            with contextlib.suppress(OSError):
                session_mtime = Path(str(transcript)).stat().st_mtime
        base_meta: dict[str, object] = {"source": "session", "extraction_config": fp}
        if session_mtime is not None:
            base_meta["session_mtime"] = session_mtime
        scope_key = _scope_key_no_session(scope)
        active = _active_subjects(self._memory, scope)
        if extra_subjects:
            # #71: caller entries win on subject_id collision so they can correct a
            # stale label; they also reach the LLM handoff list and resolve_subject's
            # `existing=` set, past the 500-record ceiling.
            by_id = {e.subject_id: e for e in active}
            for e in extra_subjects:
                by_id[e.subject_id] = e
            active = list(by_id.values())
        aliases = self._config.subject_aliases
        slotted: list[Slotted] = []
        known_subjects = [(e.subject_id, e.normalized_label) for e in active]
        for w_idx, window in windows(turns, max_chars=4000, limit=max_windows):
            for e_idx, mem in enumerate(
                extract_session_memories(llm, window, known_subjects)
            ):
                slot = None
                if (self._config.experimental_evolving_facts
                        and mem.kind == "fact" and canonical_subject(mem.subject_label)):
                    stype = canonical_subject_type(mem.subject_type or "entity")
                    try:
                        sid = resolve_subject(
                            scope_key=scope_key,
                            subject_type=stype,
                            raw_label=mem.subject_label,
                            user_id=scope.user_id,
                            existing=active,
                            aliases=aliases,
                            proposed_subject_id=mem.subject_id,
                            on_ambiguous="refuse",
                        )
                        slot = slot_for(mem, scope_key=scope_key, subject_id=sid,
                                        subject_type=stype)
                    except SubjectDisambiguationError as exc:
                        _log.warning(
                            "from_session: subject disambiguation failed for %r: "
                            "downgrading fact to standalone: %s",
                            mem.subject_label, exc,
                        )
                slotted.append(Slotted(order=(w_idx, e_idx), memory=mem, slot=slot))
        chains, standalone = plan_chains(slotted)

        candidates: list[MemoryCandidate] = []
        accepted: list[AcceptedCandidate] = []
        rejected: list[RejectedCandidate] = []

        def _commit(
            mem: SessionMemory, *, supersedes: list[str], extra_meta: dict[str, object]
        ) -> str | None:
            cand = MemoryCandidate(
                text=mem.summary, kind=mem.kind, confidence=0.8,  # type: ignore[arg-type]
                lede_source="key_fact", classifier_path="pattern_overlay",
            )
            candidates.append(cand)
            meta = dict(base_meta)
            meta.update(extra_meta)
            if mem.do_instead:
                # #62: carry the pitfall remediation so distill.rules can
                # surface it (it reads metadata["do_instead"]).
                meta["do_instead"] = mem.do_instead
            try:
                result = self._memory.add(
                    text=mem.detail or mem.summary, kind=mem.kind,  # type: ignore[arg-type]
                    source_refs=[ref], scope=scope, summary=mem.summary,
                    detail=mem.detail, confidence=0.8, metadata=meta,
                    supersedes=supersedes,
                )
            except ValidationError as exc:
                rejected.append(RejectedCandidate(
                    candidate=cand, reason="validation_error", error_message=str(exc)))
                return None
            # When supersedes is non-empty, we allow storing even if a text-hash twin exists,
            # because superseding = updating (the new memory replaces the old one).
            if result.duplicate_of is not None and not supersedes:
                rejected.append(RejectedCandidate(
                    candidate=cand, reason="duplicate", duplicate_of=result.duplicate_of))
                return None
            accepted.append(AcceptedCandidate(candidate=cand, stored_id=result.record.id))
            return result.record.id

        for it in standalone:
            _commit(it.memory, supersedes=[], extra_meta={})

        this_recency = session_mtime if session_mtime is not None else datetime.now(UTC).timestamp()
        lookup_scope = scope.model_copy(update={"session_id": None})
        for slot, states in chains.items():
            slot_meta: dict[str, object] = {
                # Earliest label is display only (subject_id drives identity/supersession)
                "canonical_subject": canonical_subject(states[0].memory.subject_label),
                "aspect": slot.aspect,
                "subject_id": slot.subject_id,
                "subject_type": slot.subject_type,
            }
            cross_ids = _cross_session_superseded(self._memory, lookup_scope, slot, this_recency)
            prev_id: str | None = None
            for it in states:  # already chronological from plan_chains
                supersedes = [prev_id] if prev_id is not None else cross_ids
                new_id = _commit(it.memory, supersedes=supersedes, extra_meta=slot_meta)
                if new_id is not None:
                    prev_id = new_id

        for subject_id, aspects in overlap_warnings(chains):
            _log.info(
                "evolving-fact: subject_id %r carries multiple active aspects %s "
                "(possible aspect drift; left distinct, not merged)", subject_id, aspects,
            )

        return self._build_report(
            candidates=candidates, accepted=accepted, rejected=rejected, source_refs=[ref],
        )

    def preview(
        self,
        *,
        text: str,
        source_refs: list[str],
        scope: MemoryScope,
    ) -> list[MemoryCandidate]:
        """Run extraction's pure core without storing. Used by Phase 3 policy engine."""
        self._check_enabled()
        _validate_source_refs(source_refs)
        del scope  # not consumed by the pure core; accepted for symmetry
        return self._run_pure_core(text=text, source_refs=source_refs)

    # ----- internals shared by all three entry points -----

    def _commit_candidates(
        self,
        *,
        candidates: list[MemoryCandidate],
        source_refs: list[str],
        scope: MemoryScope,
    ) -> tuple[list[AcceptedCandidate], list[RejectedCandidate]]:
        accepted: list[AcceptedCandidate] = []
        rejected: list[RejectedCandidate] = []
        fp = _fingerprint(self._config)
        for cand in candidates:
            if cand.confidence < self._config.min_confidence:
                rejected.append(RejectedCandidate(candidate=cand, reason="below_threshold"))
                continue
            try:
                result = self._memory.add(
                    text=cand.text,
                    kind=cand.kind,
                    source_refs=source_refs,
                    scope=scope,
                    confidence=cand.confidence,
                    metadata={"extraction_config": fp},
                )
            except ValidationError as exc:
                rejected.append(
                    RejectedCandidate(
                        candidate=cand,
                        reason="validation_error",
                        error_message=str(exc),
                    )
                )
                continue
            if result.duplicate_of is not None:
                rejected.append(
                    RejectedCandidate(
                        candidate=cand,
                        reason="duplicate",
                        duplicate_of=result.duplicate_of,
                    )
                )
                continue
            accepted.append(
                AcceptedCandidate(candidate=cand, stored_id=result.record.id)
            )
        return accepted, rejected

    def _build_report(
        self,
        *,
        candidates: list[MemoryCandidate],
        accepted: list[AcceptedCandidate],
        rejected: list[RejectedCandidate],
        source_refs: list[str],
    ) -> ExtractionReport:
        pii_flags = sorted(
            {flag for a in accepted for flag in self._collect_pii_flags(a)}
        )
        return ExtractionReport(
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            pii_flags=pii_flags,
            source_refs=source_refs,
            stats=ExtractionStats(
                candidate_count=len(candidates),
                accepted_count=len(accepted),
                rejected_count=len(rejected),
            ),
            config_fingerprint=_fingerprint(self._config),
        )

    def _collect_pii_flags(self, accepted: AcceptedCandidate) -> list[str]:
        stored = self._memory.get(accepted.stored_id)
        return list(stored.pii_flags) if stored else []

    def close(self) -> None:
        # The orchestrator owns no resources directly; Memory + Stele are
        # closed by their owners. This method exists for symmetry with
        # Stele.memory.close() so wire-up code can call it uniformly.
        pass
