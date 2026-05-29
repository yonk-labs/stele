"""Unit tests for the shared retrieval filter predicate + temporal mapping."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from stele.retrieval._filters import record_matches_filters
from stele.retrieval.temporal import parse_temporal


@dataclass
class _Rec:
    session_id: str | None = None
    created_at: dt.datetime = dt.datetime(2026, 5, 20, 12, 0)
    metadata: dict[str, Any] = field(default_factory=dict)


def test_none_or_empty_filters_match_everything() -> None:
    assert record_matches_filters(_Rec(), None) is True
    assert record_matches_filters(_Rec(), {}) is True


def test_session_id_eq() -> None:
    r = _Rec(session_id="s1")
    assert record_matches_filters(r, {"session_id": "s1"})
    assert not record_matches_filters(r, {"session_id": "s2"})


def test_created_range_inclusive() -> None:
    r = _Rec(created_at=dt.datetime(2026, 5, 20))
    assert record_matches_filters(r, {"created_after": dt.datetime(2026, 5, 18)})
    assert record_matches_filters(r, {"created_before": dt.datetime(2026, 5, 24)})
    assert not record_matches_filters(r, {"created_after": dt.datetime(2026, 5, 21)})
    assert not record_matches_filters(r, {"created_before": dt.datetime(2026, 5, 19)})


def test_created_range_tz_aware_vs_naive() -> None:
    # stored created_at is tz-aware UTC; parser bounds are naive — must compare.
    r = _Rec(created_at=dt.datetime(2026, 5, 20, 12, tzinfo=dt.UTC))
    assert record_matches_filters(r, {"created_after": dt.datetime(2026, 5, 18)})
    assert not record_matches_filters(r, {"created_before": dt.datetime(2026, 5, 19)})


def test_metadata_eq_in_and_range() -> None:
    r = _Rec(metadata={"git_branch": "auth", "date": "2026-05-20", "tool": "shell"})
    assert record_matches_filters(r, {"metadata.git_branch": "auth"})
    assert not record_matches_filters(r, {"metadata.git_branch": "main"})
    assert record_matches_filters(r, {"metadata.tool__in": ["shell", "editor"]})
    assert not record_matches_filters(r, {"metadata.tool__in": ["web"]})
    assert record_matches_filters(r, {"metadata.date__gte": "2026-05-18"})
    assert record_matches_filters(r, {"metadata.date__lte": "2026-05-24"})
    assert not record_matches_filters(r, {"metadata.date__gte": "2026-05-21"})


def test_filters_are_anded() -> None:
    r = _Rec(metadata={"date": "2026-05-20", "repo": "stele"})
    assert record_matches_filters(
        r, {"metadata.date__gte": "2026-05-18", "metadata.repo": "stele"})
    assert not record_matches_filters(
        r, {"metadata.date__gte": "2026-05-18", "metadata.repo": "other"})


def test_missing_metadata_key_fails_range() -> None:
    assert not record_matches_filters(_Rec(metadata={}), {"metadata.date__gte": "2026-01-01"})


def test_temporal_to_metadata_filter_roundtrip() -> None:
    now = dt.datetime(2026, 5, 29, 12, 0)  # Friday
    _cleaned, tf = parse_temporal("what shipped last week", now)
    assert tf is not None
    mf = tf.as_metadata_filters("date")
    assert mf == {
        "metadata.date__gte": "2026-05-18",
        "metadata.date__lte": "2026-05-24",
    }
    # An in-window record passes, an out-of-window one does not.
    assert record_matches_filters(_Rec(metadata={"date": "2026-05-20"}), mf)
    assert not record_matches_filters(_Rec(metadata={"date": "2026-05-26"}), mf)
