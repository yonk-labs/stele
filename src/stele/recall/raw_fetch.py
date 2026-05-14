"""RawFetchStrategy — requires artifact_id; fetches full raw content."""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.core.exceptions import ValidationError
from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)


class RawFetchStrategy:
    name = "raw_fetch"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        if request.artifact_id is None:
            raise ValidationError("raw_fetch requires artifact_id")
        fetched = deps.stele.fetch(request.artifact_id, raw=True)
        content = (
            fetched.content
            if isinstance(fetched.content, str)
            else fetched.content.decode("utf-8", errors="replace")
        )
        citation = Citation(
            kind="artifact",
            id=request.artifact_id,
            reference=fetched.reference,
            score=1.0,
            snippet=content,
        )
        return RecallResult(
            strategy_used="raw_fetch",
            context=content,
            citations=[citation],
            escalations=[
                Escalation(
                    strategy="raw_fetch",
                    hit_count=1,
                    top_score=1.0,
                    reason="tier_complete",
                )
            ],
            pii_flags=list(fetched.pii.entity_types) if fetched.pii else [],
            source_refs=[fetched.reference],
            stats=RecallStats(
                fetches=1,
                estimated_context_tokens=estimate_tokens(content),
            ),
        )
