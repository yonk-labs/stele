"""DigestStrategy — hybrid-search retrieval packed as summary + facts + top chunks.

Retrieval is identical to ArtifactSearchStrategy (reference-scoped
``stele.search`` or global ``stele.query``). The difference is packing: instead
of concatenating snippets, the hits are packed via the injected ``DigestPacker``
(lede summary + extracted facts + top-N raw chunks). If no packer is wired the
strategy degrades to the plain snippet join, so it never hard-fails.
"""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.core.reference import make_reference
from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)
from stele.recall.ranking import normalize_scores


class DigestStrategy:
    name = "digest"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        if request.artifact_id is not None:
            ref = make_reference(
                request.scope.namespace, request.artifact_id
            ).canonical_without_params
            fetched = deps.stele.fetch(ref)
            hits = deps.stele.search(
                fetched.reference, request.query, limit=request.max_artifact_hits
            )
        else:
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

        if deps.digest_packer is not None:
            context = deps.digest_packer.pack(hits, request.query)
        else:
            context = "\n\n".join(c.snippet for c in citations)
        top_score = citations[0].score if citations else None

        return RecallResult(
            strategy_used="digest",
            context=context,
            citations=citations,
            escalations=[
                Escalation(
                    strategy="digest",
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
