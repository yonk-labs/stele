"""AbstainStrategy — explicit "no sufficient context" terminator."""

from __future__ import annotations

from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)


class AbstainStrategy:
    name = "abstain"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        # Reason is carried on the request via a backdoor field set by the
        # facade shim; the canonical RecallRequest model doesn't have a
        # `reason` field, so the facade injects it on the orchestrator side
        # when the caller invokes `recall.abstain(reason=...)`. Default is
        # config.abstain_default_reason.
        reason = getattr(request, "_abstain_reason", None) or deps.config.abstain_default_reason
        return RecallResult(
            strategy_used="abstain",
            context="",
            citations=[],
            escalations=[
                Escalation(
                    strategy="abstain",
                    hit_count=0,
                    top_score=None,
                    reason="exhausted",
                )
            ],
            pii_flags=[],
            source_refs=[],
            stats=RecallStats(),
            abstained=True,
            abstain_reason=reason,
        )
