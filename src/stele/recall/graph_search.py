"""GraphSearchStrategy — pg-raggraph living-knowledge retrieval (Phase 5).

Reads ONLY through deps.stele.revisor (the sync Revisor Protocol). No
pg_raggraph import, no asyncio/threading here (DC-P5-1/DC-P5-2). When no
Revisor is configured (NoOp) it remains a CapabilityError, exactly as the
pre-Phase-5 stub (SC-P5-07: capability honesty).
"""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.core.exceptions import CapabilityError
from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)
from stele.recall.ranking import normalize_scores


class GraphSearchStrategy:
    name = "graph_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        revisor = deps.stele.revisor
        if not revisor.active:
            raise CapabilityError(
                "graph_search requires the [postgres-graph] extra and a "
                "Postgres backend with config.graph.enabled=true"
            )
        rb = request.retracted_behavior or "surface_both"
        ns = request.scope.namespace
        if request.as_of is not None:
            hits = revisor.search_as_of(
                request.query,
                namespace=ns,
                limit=request.max_memory_hits,
                as_of=request.as_of,
                retracted_behavior=rb,
                version_filter=request.version_filter,
            )
        else:
            hits = revisor.search_current(
                request.query,
                namespace=ns,
                limit=request.max_memory_hits,
                retracted_behavior=rb,
                version_filter=request.version_filter,
            )
        citations = normalize_scores(
            [
                Citation(
                    kind="memory",
                    id=h.chunk_id or h.stele_ref,
                    reference=h.stele_ref,
                    score=h.score,
                    snippet=h.text,
                )
                for h in hits
            ]
        )
        context = "\n\n".join(c.snippet for c in citations)
        top_score = citations[0].score if citations else None
        return RecallResult(
            strategy_used="graph_search",
            context=context,
            citations=citations,
            escalations=[
                Escalation(
                    strategy="graph_search",
                    hit_count=len(citations),
                    top_score=top_score,
                    reason="tier_complete" if citations else "zero_hits",
                )
            ],
            source_refs=sorted({h.stele_ref for h in hits if h.stele_ref}),
            stats=RecallStats(
                memory_searches=1,
                estimated_context_tokens=estimate_tokens(context) if context else 0,
            ),
        )
