"""SummaryOnlyStrategy — requires artifact_id; returns the artifact's stored summary."""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.core.exceptions import ValidationError
from stele.core.reference import make_reference
from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)


class SummaryOnlyStrategy:
    name = "summary_only"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        if request.artifact_id is None:
            raise ValidationError("summary_only requires artifact_id")
        ref = make_reference(
            request.scope.namespace, request.artifact_id
        ).canonical_without_params
        fetched = deps.stele.fetch(ref)
        # The artifact's stored summary lives on metadata for fetch results.
        summary = fetched.metadata.get("summary") if fetched.metadata else None
        if not summary or not isinstance(summary, str):
            # Fall back to a truncation of content for artifacts that lack a stored summary
            content_text = (
                fetched.content
                if isinstance(fetched.content, str)
                else fetched.content.decode("utf-8", errors="replace")
            )
            summary = content_text[: deps.config.max_context_chars]
        citation = Citation(
            kind="artifact",
            id=request.artifact_id,
            reference=fetched.reference,
            score=1.0,
            snippet=summary,
        )
        return RecallResult(
            strategy_used="summary_only",
            context=summary,
            citations=[citation],
            escalations=[
                Escalation(
                    strategy="summary_only",
                    hit_count=1,
                    top_score=1.0,
                    reason="tier_complete",
                )
            ],
            pii_flags=list(fetched.pii.entity_types) if fetched.pii else [],
            source_refs=[fetched.reference],
            stats=RecallStats(
                fetches=1,
                estimated_context_tokens=estimate_tokens(summary),
            ),
        )
