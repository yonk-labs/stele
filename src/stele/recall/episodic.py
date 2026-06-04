"""EpisodicStrategy — retrieve a past session (artifact + back-linked memories).

Phase 1 of episodic recall. An *episode* is one session: a stored session
artifact plus the memories that cite it via ``source_refs``. The strategy
composes primitives that already exist: ``parse_temporal`` (turn "last week"
into a window), ``stele.query`` (semantic rank of session text), and
``memory.by_source_ref`` (the evidence back-link).

Temporal is a SOFT boost by default (never excludes a candidate); a caller can
opt in to a HARD window restriction with ``hard_temporal=True``. Either way the
anti-backfire rule holds: a window that empties or nearly empties the candidate
set falls back to the unfiltered rank rather than returning nothing.

This module imports no LLM client, no pg_raggraph, no chunkshop, and no lede —
``parse_temporal`` is a pure regex/date-math parser. The recall invariant is
enforced by ``tests/unit/recall/test_architecture.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from stele.core.artifact import SearchHit
from stele.retrieval.temporal import TemporalFilter

# Episodes are session artifacts. A caller's ingest feed tags them with this
# metadata source; when no candidate carries it we fall back to all artifacts.
SESSION_SOURCE = "session-ingest"

# Multiplicative reward applied to an episode that lands inside the parsed
# window. Soft by design: it re-ranks toward the window without ever dropping
# an out-of-window episode (the LoCoMo entity-filter result showed hard
# exclusion on a bad parse is a net loss).
_IN_WINDOW_BOOST = 1.5

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
    inside the window: a fixed multiplicative reward. The boost only reorders
    candidates; it never removes one."""
    if window is None:
        return score
    return score * _IN_WINDOW_BOOST if _in_window(when, window) else score


def _hit_metadata(hit: SearchHit) -> dict[str, object]:
    return hit.metadata if isinstance(hit.metadata, dict) else {}


def _hit_when(hit: SearchHit) -> datetime:
    meta = _hit_metadata(hit)
    raw = meta.get("created_at")
    created_at: datetime
    if isinstance(raw, datetime):
        created_at = raw
    elif isinstance(raw, str):
        try:
            created_at = datetime.fromisoformat(raw)
        except ValueError:
            created_at = datetime.now(UTC)
    else:
        created_at = datetime.now(UTC)
    return _episode_when(meta, created_at)


def _is_session_episode(hit: SearchHit) -> bool:
    return _hit_metadata(hit).get("source") == SESSION_SOURCE


def _dedupe_episodes(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """One hit per artifact (a session can produce several chunk hits). Keep
    the highest-scoring chunk as the episode's representative."""
    best: dict[str, SearchHit] = {}
    for hit in hits:
        key = hit.reference
        current = best.get(key)
        if current is None or hit.score > current.score:
            best[key] = hit
    return list(best.values())
