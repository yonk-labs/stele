"""ArtifactSearchStrategy — global stele.query or reference-scoped stele.search."""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)
from stele.recall.ranking import normalize_scores


class ArtifactSearchStrategy:
    name = "artifact_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        if request.artifact_id is not None:
            fetched = deps.stele.fetch(request.artifact_id)
            hits = deps.stele.search(
                fetched.reference, request.query, limit=request.max_artifact_hits
            )
        else:
            # Global search across the scope's namespace
            hits = deps.stele.query(
                request.scope.namespace,
                request.query,
                limit=request.max_artifact_hits,
            )

        citations = normalize_scores(
            [
                Citation(
                    kind="chunk",
                    id=hit.chunk_id or hit.artifact_id,
                    reference=hit.reference,
                    score=hit.score,
                    snippet=hit.text,
                )
                for hit in hits
            ]
        )

        context = "\n\n".join(c.snippet for c in citations)
        top_score = citations[0].score if citations else None

        return RecallResult(
            strategy_used="artifact_search",
            context=context,
            citations=citations,
            escalations=[
                Escalation(
                    strategy="artifact_search",
                    hit_count=len(citations),
                    top_score=top_score,
                    reason="tier_complete" if citations else "zero_hits",
                )
            ],
            pii_flags=sorted(
                {flag for hit in hits if hit.pii for flag in (hit.pii.entity_types or [])}
            ),
            source_refs=sorted({hit.reference for hit in hits}),
            stats=RecallStats(
                artifact_searches=1,
                estimated_context_tokens=estimate_tokens(context) if context else 0,
            ),
        )
