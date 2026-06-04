"""Unit tests for the episodic recall strategy: model, temporal helpers,
and the end-to-end strategy (soft boost, hard filter, fallback)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope
from stele.recall.episodic import (
    SESSION_SOURCE,
    _episode_when,
    _in_window,
    _soft_boost,
)
from stele.recall.models import EpisodeHit
from stele.retrieval.temporal import TemporalFilter, parse_temporal


def _stele() -> Stele:
    return Stele(StashConfig())


def _ingest_episode(
    stele: Stele,
    *,
    session_id: str,
    text: str,
    when: datetime,
) -> str:
    """Store a session-ingest artifact tagged with its session_mtime and
    return its reference."""
    stored = stele.store(
        content=text,
        namespace="default",
        session_id=session_id,
        metadata={"source": SESSION_SOURCE, "session_mtime": when.isoformat()},
    )
    return stored.reference


def _window(after: datetime | None, before: datetime | None) -> TemporalFilter:
    return TemporalFilter(after=after, before=before, matched="test")


def test_episode_hit_defaults() -> None:
    hit = EpisodeHit(summary="auth refactor", ref="stele://default/x", score=0.7)
    assert hit.session_id is None
    assert hit.when is None
    assert hit.memories == []
    assert hit.score == 0.7


def test_episode_when_prefers_session_mtime_datetime() -> None:
    mtime = datetime(2026, 5, 20, tzinfo=UTC)
    created = datetime(2026, 6, 1, tzinfo=UTC)
    assert _episode_when({"session_mtime": mtime}, created) == mtime


def test_episode_when_parses_session_mtime_iso_string() -> None:
    created = datetime(2026, 6, 1, tzinfo=UTC)
    out = _episode_when({"session_mtime": "2026-05-20T00:00:00+00:00"}, created)
    assert out == datetime(2026, 5, 20, tzinfo=UTC)


def test_episode_when_falls_back_to_created_at() -> None:
    created = datetime(2026, 6, 1, tzinfo=UTC)
    assert _episode_when({}, created) == created
    # Unparseable mtime also falls back.
    assert _episode_when({"session_mtime": "not-a-date"}, created) == created


def test_in_window_inclusive_bounds() -> None:
    after = datetime(2026, 5, 18)
    before = datetime(2026, 5, 24, 23, 59, 59)
    window = _window(after, before)
    assert _in_window(datetime(2026, 5, 20, tzinfo=UTC), window) is True
    assert _in_window(datetime(2026, 5, 17, tzinfo=UTC), window) is False
    assert _in_window(datetime(2026, 5, 25, tzinfo=UTC), window) is False


def test_soft_boost_rewards_in_window_never_excludes() -> None:
    window = _window(datetime(2026, 5, 18), datetime(2026, 5, 24, 23, 59, 59))
    inside = datetime(2026, 5, 20, tzinfo=UTC)
    outside = datetime(2026, 6, 1, tzinfo=UTC)
    boosted = _soft_boost(0.5, inside, window)
    unchanged = _soft_boost(0.5, outside, window)
    assert boosted > unchanged
    # Out-of-window is never dropped: it keeps its base score.
    assert unchanged == 0.5


def test_soft_boost_no_window_is_identity() -> None:
    assert _soft_boost(0.42, datetime(2026, 5, 20, tzinfo=UTC), None) == 0.42


# --- strategy end-to-end ---------------------------------------------------


def test_episodic_returns_episodes_with_back_linked_memories() -> None:
    stele = _stele()
    scope = MemoryScope(namespace="default")
    ref = _ingest_episode(
        stele,
        session_id="sess-auth",
        text="we refactored the auth token refresh flow and switched to keep120",
        when=datetime.now(UTC) - timedelta(days=2),
    )
    mem = stele.memory.add(
        text="switched token cadence to keep120",
        kind="decision",
        source_refs=[ref],
        scope=scope,
    )

    result = stele.recall(query="auth token refresh", scope=scope, strategy="episodic")

    assert result.strategy_used == "episodic"
    assert result.episodes, "expected at least one episode"
    top = result.episodes[0]
    assert top.ref == ref
    assert top.session_id == "sess-auth"
    assert {m.id for m in top.memories} == {mem.record.id}
    # The standard recall contract is still populated.
    assert result.context
    assert result.source_refs == [ref]
    stele.close()


def test_episodic_soft_boost_surfaces_in_window_episode_first() -> None:
    stele = _stele()
    scope = MemoryScope(namespace="default")
    now = datetime.now(UTC)
    # Derive "last week" with the same parser the strategy uses, so the test is
    # deterministic regardless of wall-clock.
    _, window = parse_temporal("what was I building last week", now)
    assert window is not None and window.after is not None

    in_window = window.after + timedelta(hours=12)
    out_window = now  # this week, outside "last week"

    recent_ref = _ingest_episode(
        stele,
        session_id="sess-recent",
        text="building the dashboard widget layout",
        when=out_window,
    )
    older_ref = _ingest_episode(
        stele,
        session_id="sess-older",
        text="building the dashboard widget layout",
        when=in_window,
    )
    # Same topic text in both so the only differentiator is the window boost.
    for ref in (recent_ref, older_ref):
        stele.memory.add(
            text=f"note for {ref}",
            kind="fact",
            source_refs=[ref],
            scope=scope,
        )

    result = stele.recall(
        query="what was I building last week", scope=scope, strategy="episodic"
    )
    assert result.episodes
    assert result.episodes[0].ref == older_ref, (
        "the in-window episode should be soft-boosted above the equally-relevant "
        "out-of-window one"
    )
    stele.close()


def test_episodic_via_facade_shim() -> None:
    stele = _stele()
    scope = MemoryScope(namespace="default")
    ref = _ingest_episode(
        stele,
        session_id="sess-x",
        text="kafka partition rebalancing investigation",
        when=datetime.now(UTC) - timedelta(days=1),
    )
    stele.memory.add(
        text="kafka rebalance storm fixed with cooperative-sticky",
        kind="fact",
        source_refs=[ref],
        scope=scope,
    )
    result = stele.recall.episodic(query="kafka rebalancing", scope=scope)
    assert result.strategy_used == "episodic"
    assert result.episodes and result.episodes[0].ref == ref
    stele.close()
