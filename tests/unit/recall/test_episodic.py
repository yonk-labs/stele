"""Unit tests for the episodic recall strategy: model, temporal helpers,
and the end-to-end strategy (soft boost, hard filter, fallback)."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.recall.episodic import (
    _episode_when,
    _in_window,
    _soft_boost,
)
from stele.recall.models import EpisodeHit
from stele.retrieval.temporal import TemporalFilter


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
