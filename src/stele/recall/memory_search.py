"""MemorySearchStrategy — uses Memory.search_with_score with optional source_ref forcing."""

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


class MemorySearchStrategy:
    name = "memory_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        source_ref_filter = None
        if request.artifact_id is not None:
            fetched = deps.stele.fetch(request.artifact_id)
            source_ref_filter = fetched.reference

        hits = deps.memory.search_with_score(
            request.query,
            request.scope,
            limit=request.max_memory_hits,
            source_ref_filter=source_ref_filter,
        )

        citations = normalize_scores(
            [
                Citation(
                    kind="memory",
                    id=hit.record.id,
                    reference=hit.record.source_refs[0] if hit.record.source_refs else "",
                    score=hit.score,
                    snippet=hit.record.text,
                )
                for hit in hits
            ]
        )

        context = "\n\n".join(c.snippet for c in citations)
        top_score = citations[0].score if citations else None

        return RecallResult(
            strategy_used="memory_search",
            context=context,
            citations=citations,
            escalations=[
                Escalation(
                    strategy="memory_search",
                    hit_count=len(citations),
                    top_score=top_score,
                    reason="tier_complete" if citations else "zero_hits",
                )
            ],
            pii_flags=sorted({f for hit in hits for f in hit.record.pii_flags}),
            source_refs=sorted(
                {hit.record.source_refs[0] for hit in hits if hit.record.source_refs}
            ),
            stats=RecallStats(
                memory_searches=1,
                estimated_context_tokens=estimate_tokens(context) if context else 0,
            ),
        )
