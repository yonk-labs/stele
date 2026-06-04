"""EpisodicStrategy: retrieve a past session (artifact + back-linked memories).

Phase 1 of episodic recall. An *episode* is one session: a stored session
artifact plus the memories that cite it via ``source_refs``. The strategy
composes primitives that already exist: ``parse_temporal`` (turn "last week"
into a window), ``stele.query`` (semantic rank of session text), and
``memory.by_source_ref`` (the evidence back-link).

Temporal is a SOFT boost by default (never excludes a candidate); a caller can
opt in to a HARD window restriction with ``hard_temporal=True``. Either way the
anti-backfire rule holds: a window that empties or nearly empties the candidate
set falls back to the unfiltered rank rather than returning nothing.

This module imports no LLM client, no pg_raggraph, no chunkshop, and no lede.
``parse_temporal`` is a pure regex/date-math parser. The recall invariant is
enforced by ``tests/unit/recall/test_architecture.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord, SearchHit, estimate_tokens
from stele.core.memory_record import MemoryRecord
from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Citation,
    EpisodeHit,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)
from stele.recall.ranking import normalize_scores
from stele.retrieval.temporal import TemporalFilter, parse_temporal

# Episodes are session artifacts. A caller's ingest feed tags them with this
# metadata source; when no candidate carries it we fall back to all artifacts.
SESSION_SOURCE = "session-ingest"

# Additive reward applied to an episode that lands inside the parsed window.
# Soft by design: it re-ranks toward the window without ever dropping an
# out-of-window episode (the LoCoMo entity-filter result showed hard exclusion
# on a bad parse is a net loss). Additive (not multiplicative) so window
# membership still tips the order when the semantic score is 0 (the window-
# only query "what happened last week" with no surviving topic terms).
_IN_WINDOW_BOOST = 1.0

# Below this many in-window candidates a hard/soft window is treated as a
# bad/over-tight parse and we fall back to the unfiltered rank (anti-backfire).
_MIN_WINDOW_CANDIDATES = 1


def _as_naive_utc(value: datetime) -> datetime:
    """Normalize to a tz-naive UTC instant so window comparisons are total.

    ``parse_temporal`` returns tz-naive day bounds; artifact ``created_at`` is
    tz-aware UTC. Compare apples to apples by stripping tz (converting aware
    values to UTC first)."""
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _episode_when(metadata: dict[str, object], created_at: datetime) -> datetime:
    """The episode's temporal anchor: ``metadata.session_mtime`` if present and
    parseable, else the artifact ``created_at``."""
    raw = metadata.get("session_mtime")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return created_at
    return created_at


def _in_window(when: datetime, window: TemporalFilter) -> bool:
    """True when ``when`` falls inside the (inclusive) window bounds."""
    w = _as_naive_utc(when)
    if window.after is not None and w < _as_naive_utc(window.after):
        return False
    return not (window.before is not None and w > _as_naive_utc(window.before))


def _soft_boost(score: float, when: datetime, window: TemporalFilter | None) -> float:
    """Re-rank ``score`` toward the window without ever excluding.

    No window, or an episode outside it: the score is unchanged. An episode
    inside the window: a fixed additive reward. The boost only reorders
    candidates; it never removes one."""
    if window is None:
        return score
    return score + _IN_WINDOW_BOOST if _in_window(when, window) else score


def _record_when(record: ArtifactRecord) -> datetime:
    return _episode_when(dict(record.metadata), record.created_at)


def _episode_summary(record: ArtifactRecord, memories: Sequence[MemoryRecord]) -> str:
    """Prefer a distilled 'what happened' summary (the Phase 2 episode view's
    deterministic composition over the session's memories) when the episode has
    back-linked memories; fall back to the raw artifact summary otherwise.

    Reuses ``distill.episodes._compose_summary`` so the recall and distill
    surfaces describe an episode identically. That helper is pure and
    deterministic (no LLM, no graph), so the recall invariant is preserved."""
    if not memories:
        return record.summary
    from stele.distill.episodes import _compose_summary

    return _compose_summary(record, list(memories))


def _is_session_record(record: ArtifactRecord) -> bool:
    return record.metadata.get("source") == SESSION_SOURCE


def _scores_by_reference(hits: Sequence[SearchHit]) -> dict[str, float]:
    """Fold ranked search hits into one score per artifact (a session can
    produce several chunk hits). Keep the highest-scoring chunk's score."""
    best: dict[str, float] = {}
    for hit in hits:
        prev = best.get(hit.reference)
        if prev is None or hit.score > prev:
            best[hit.reference] = hit.score
    return best


class _Candidate:
    """An episode candidate: its artifact record, base semantic score, temporal
    anchor, and whether it falls inside the parsed window."""

    __slots__ = ("record", "base_score", "when", "in_window")

    def __init__(
        self,
        record: ArtifactRecord,
        base_score: float,
        when: datetime,
        window: TemporalFilter | None,
    ) -> None:
        self.record = record
        self.base_score = base_score
        self.when = when
        self.in_window = window is not None and _in_window(when, window)


class EpisodicStrategy:
    name = "episodic"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        now = datetime.now(UTC)
        cleaned, window = parse_temporal(request.query, now)
        namespace = request.scope.namespace

        # Semantic signal: rank session text on the time-stripped query. Pull a
        # wider pool than the final K so the temporal re-rank has room to work.
        pool = max(request.max_artifact_hits * 4, 20)
        ranked = deps.stele.query(namespace, cleaned, limit=pool)
        scores = _scores_by_reference(ranked)

        # Candidate records carry the metadata (created_at, session_id, source,
        # session_mtime) the keyword search-hit dict does not. Enumerate the
        # namespace once and join the semantic scores by reference.
        records = self._candidate_records(deps, namespace, request.scope.session_id)
        candidates = [
            _Candidate(rec, scores.get(rec.reference, 0.0), _record_when(rec), window)
            for rec in records
        ]

        selected = self._select(candidates, window, hard=request.hard_temporal)
        selected.sort(key=lambda c: (self._rank(c, window), c.when), reverse=True)
        top = selected[: request.max_artifact_hits]

        episodes = [self._to_episode(c, request, deps, window) for c in top]
        return self._assemble(episodes)

    @staticmethod
    def _candidate_records(
        deps: _RecallDeps, namespace: str, session_id: str | None
    ) -> list[ArtifactRecord]:
        page = deps.stele.list(namespace=namespace, session_id=session_id, limit=10_000)
        records = list(page.items)
        # Episodes are session-ingest artifacts where the feed tags them; if
        # nothing is tagged, treat every artifact as a candidate episode.
        session_records = [r for r in records if _is_session_record(r)]
        return session_records or records

    @staticmethod
    def _select(
        candidates: list[_Candidate],
        window: TemporalFilter | None,
        *,
        hard: bool,
    ) -> list[_Candidate]:
        """Apply the window. Hard mode restricts to in-window candidates; soft
        mode keeps everything (the boost re-ranks). EITHER way, the
        anti-backfire rule holds: when the window matches too few candidates,
        fall back to the unfiltered set rather than returning (near) nothing."""
        if window is None:
            return candidates
        in_window = [c for c in candidates if c.in_window]
        if len(in_window) < _MIN_WINDOW_CANDIDATES:
            return candidates  # bad/over-tight parse -> unfiltered fallback
        return in_window if hard else candidates

    @staticmethod
    def _rank(candidate: _Candidate, window: TemporalFilter | None) -> float:
        return _soft_boost(candidate.base_score, candidate.when, window)

    @staticmethod
    def _to_episode(
        candidate: _Candidate,
        request: RecallRequest,
        deps: _RecallDeps,
        window: TemporalFilter | None,
    ) -> EpisodeHit:
        rec = candidate.record
        memories = deps.memory.by_source_ref(request.scope, rec.reference)
        return EpisodeHit(
            session_id=rec.session_id,
            when=candidate.when,
            summary=_episode_summary(rec, memories),
            ref=rec.reference,
            score=_soft_boost(candidate.base_score, candidate.when, window),
            memories=memories,
        )

    @staticmethod
    def _assemble(episodes: list[EpisodeHit]) -> RecallResult:
        citations = normalize_scores(
            [
                Citation(
                    kind="artifact",
                    id=ep.ref,
                    reference=ep.ref,
                    score=ep.score,
                    snippet=ep.summary,
                )
                for ep in episodes
            ]
        )
        context = "\n\n".join(ep.summary for ep in episodes)
        top_score = citations[0].score if citations else None
        return RecallResult(
            strategy_used="episodic",
            context=context,
            citations=citations,
            escalations=[
                Escalation(
                    strategy="episodic",
                    hit_count=len(episodes),
                    top_score=top_score,
                    reason="tier_complete" if episodes else "zero_hits",
                )
            ],
            source_refs=[ep.ref for ep in episodes],
            stats=RecallStats(
                artifact_searches=1,
                estimated_context_tokens=estimate_tokens(context) if context else 0,
            ),
            episodes=episodes,
        )
