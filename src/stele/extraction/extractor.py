"""MemoryExtractor — I/O orchestrator for Phase 2 extraction."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from stele.core.exceptions import (
    ArtifactNotFound,
    CapabilityError,
    SteleError,
    ValidationError,
)
from stele.core.memory_record import MemoryScope
from stele.extraction.candidates import extract_candidates
from stele.extraction.classifier import classify_kind
from stele.extraction.models import (
    AcceptedCandidate,
    ExtractionReport,
    ExtractionStats,
    MemoryCandidate,
    RejectedCandidate,
)

if TYPE_CHECKING:
    from stele.core.config import ExtractionConfig
    from stele.core.memory import Memory
    from stele.core.stash import Stele
    from stele.pii.regex import RegexPIIScrubber
    from stele.pii.scrubber import DisabledPIIScrubber


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
    ) -> ExtractionReport:
        """Distill durable memory from a real agent transcript (Claude .jsonl, a
        generic message list, or pre-parsed Turns). The deterministic extractor
        does not fit conversational, tool-heavy transcripts, so this is
        LLM-driven: parse, window (failures first), and ask the injected `llm`
        to extract kinded memories with evidence. Commits via the memory facade
        (PII scrubbing inherited); the transcript is stashed as the source ref."""
        self._check_enabled()
        from stele.extraction.session import (
            ReduceConfig,
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
        candidates: list[MemoryCandidate] = []
        accepted: list[AcceptedCandidate] = []
        rejected: list[RejectedCandidate] = []
        for window in windows(turns, max_chars=4000, limit=max_windows):
            for mem in extract_session_memories(llm, window):
                cand = MemoryCandidate(
                    text=mem.summary, kind=mem.kind, confidence=0.8,  # type: ignore[arg-type]
                    lede_source="key_fact", classifier_path="pattern_overlay",
                )
                candidates.append(cand)
                try:
                    result = self._memory.add(
                        text=mem.detail or mem.summary, kind=mem.kind,  # type: ignore[arg-type]
                        source_refs=[ref], scope=scope, summary=mem.summary,
                        detail=mem.detail, confidence=0.8, metadata=dict(base_meta),
                    )
                except ValidationError as exc:
                    rejected.append(RejectedCandidate(
                        candidate=cand, reason="validation_error", error_message=str(exc)))
                    continue
                if result.duplicate_of is not None:
                    rejected.append(RejectedCandidate(
                        candidate=cand, reason="duplicate", duplicate_of=result.duplicate_of))
                    continue
                accepted.append(AcceptedCandidate(candidate=cand, stored_id=result.record.id))
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
