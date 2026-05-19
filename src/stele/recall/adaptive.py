"""AdaptiveStrategy — composes other strategies; runs tier order with escalation."""

from __future__ import annotations

from stele.recall.abstain import AbstainStrategy
from stele.recall.artifact_search import ArtifactSearchStrategy
from stele.recall.base import Strategy, _RecallDeps
from stele.recall.graph_search import GraphSearchStrategy
from stele.recall.memory_search import MemorySearchStrategy
from stele.recall.models import (
    Citation,
    Escalation,
    EscalationReason,
    RecallContext,
    RecallRequest,
    RecallResult,
    RecallStats,
    StrategyName,
)
from stele.recall.ranking import merge_hits
from stele.recall.raw_fetch import RawFetchStrategy
from stele.recall.summary_only import SummaryOnlyStrategy


class AdaptiveStrategy:
    name = "adaptive"

    def __init__(self) -> None:
        self._registry: dict[StrategyName, Strategy] = {
            "summary_only": SummaryOnlyStrategy(),
            "memory_search": MemorySearchStrategy(),
            "artifact_search": ArtifactSearchStrategy(),
            "graph_search": GraphSearchStrategy(),
            "raw_fetch": RawFetchStrategy(),
            "abstain": AbstainStrategy(),
        }

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        tier_order: list[StrategyName]
        if request.as_of is not None or request.version_filter is not None:
            # Time-travel / versioned query: only temporal-aware strategies
            # are valid. Falling back to a non-temporal strategy and
            # returning today's answer is a correctness violation (BUG-3).
            tier_order = ["graph_search", "abstain"]
        else:
            tier_order = list(deps.config.adaptive_tier_order)
        floor = (
            request.confidence_floor
            if request.confidence_floor is not None
            else deps.config.confidence_floor
        )

        # Skip raw_fetch when no artifact_id and config says so
        if (
            deps.config.adaptive_skip_raw_fetch_without_artifact_id
            and request.artifact_id is None
            and "raw_fetch" in tier_order
        ):
            tier_order = [t for t in tier_order if t != "raw_fetch"]

        accumulated_citations: list[Citation] = []
        accumulated_stats = RecallStats()
        all_escalations: list[Escalation] = []
        all_pii_flags: set[str] = set()
        all_source_refs: set[str] = set()

        terminating_result: RecallResult | None = None
        for tier_name in tier_order:
            strategy = self._registry[tier_name]
            tier_result = strategy.execute(request, deps)

            accumulated_citations = merge_hits(accumulated_citations, tier_result.citations)
            accumulated_stats = _sum_stats(accumulated_stats, tier_result.stats)
            all_pii_flags.update(tier_result.pii_flags)
            all_source_refs.update(tier_result.source_refs)

            top_score = tier_result.citations[0].score if tier_result.citations else None
            hit_count = len(tier_result.citations)

            reason: EscalationReason
            stop = False

            if tier_name == "abstain":
                # abstain is always terminal
                all_escalations.append(
                    Escalation(
                        strategy=tier_name,
                        hit_count=0,
                        top_score=None,
                        reason="exhausted",
                    )
                )
                terminating_result = tier_result
                break

            if hit_count == 0:
                reason = "zero_hits"
            elif top_score is not None and top_score >= floor:
                reason = "tier_complete"
                stop = True
            else:
                reason = "below_floor"

            # Optional caller callback layered on top
            if stop and request.sufficient is not None:
                ctx = RecallContext(
                    query=request.query,
                    scope=request.scope,
                    accumulated_citations=list(accumulated_citations),
                    accumulated_text="\n\n".join(c.snippet for c in accumulated_citations),
                )
                try:
                    is_sufficient = request.sufficient(ctx)
                except Exception as exc:
                    from stele.core.exceptions import SteleError

                    raise SteleError(f"sufficient callback raised: {exc}") from exc
                if not is_sufficient:
                    stop = False
                    reason = "sufficient_callback_false"

            all_escalations.append(
                Escalation(
                    strategy=tier_name,
                    hit_count=hit_count,
                    top_score=top_score,
                    reason=reason,
                )
            )
            if stop:
                terminating_result = tier_result
                break

        # Fallback if loop exited without abstain (shouldn't happen if config is valid)
        if terminating_result is None:
            fallback = AbstainStrategy()
            terminating_result = fallback.execute(request, deps)
            all_escalations.append(
                Escalation(strategy="abstain", hit_count=0, top_score=None, reason="exhausted")
            )

        context = "\n\n".join(c.snippet for c in accumulated_citations)

        return RecallResult(
            strategy_used=terminating_result.strategy_used,
            context=context,
            citations=accumulated_citations,
            escalations=all_escalations,
            pii_flags=sorted(all_pii_flags),
            source_refs=sorted(all_source_refs),
            stats=accumulated_stats,
            abstained=terminating_result.abstained,
            abstain_reason=terminating_result.abstain_reason,
        )


def _sum_stats(a: RecallStats, b: RecallStats) -> RecallStats:
    return RecallStats(
        memory_searches=a.memory_searches + b.memory_searches,
        artifact_searches=a.artifact_searches + b.artifact_searches,
        chunk_searches=a.chunk_searches + b.chunk_searches,
        fetches=a.fetches + b.fetches,
        estimated_context_tokens=a.estimated_context_tokens + b.estimated_context_tokens,
        latency_ms=a.latency_ms + b.latency_ms,
    )
