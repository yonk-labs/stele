"""Unit table for the temporal query parser.

Reference clock: now = Friday 29 May 2026, 14:30. Key anchors:
  - last Friday (strictly before today) = 2026-05-22
  - this-week start (Monday)            = 2026-05-25
  - last week                           = 2026-05-18 .. 2026-05-24
  - yesterday                           = 2026-05-28
  - last 7 days                         = 2026-05-22 .. 2026-05-29
"""
from __future__ import annotations

import datetime as dt

import pytest

from stele.retrieval.temporal import parse_temporal

NOW = dt.datetime(2026, 5, 29, 14, 30, 0)  # Friday


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@pytest.mark.parametrize(
    ("query", "exp_after", "exp_before", "exp_clean"),
    [
        # last N units → window ending now
        ("what was I building in the last 7 days", "2026-05-22", "2026-05-29",
         "what was I building"),
        ("errors over the past 2 weeks", "2026-05-15", "2026-05-29", "errors"),
        # N units ago → single-day window
        ("what did I commit 3 days ago", "2026-05-26", "2026-05-26",
         "what did I commit"),
        # last <weekday> → that specific prior day
        ("the bug I hit last friday", "2026-05-22", "2026-05-22", "the bug I hit"),
        # minimal cleaning keeps the dangling "from" (we don't guess connectives)
        ("notes from last monday", "2026-05-25", "2026-05-25", "notes from"),
        # last week / month / year → previous calendar period
        ("the thing I was working on last week", "2026-05-18", "2026-05-24",
         "the thing I was working on"),
        ("invoices last month", "2026-04-01", "2026-04-30", "invoices"),
        ("releases last year", "2025-01-01", "2025-12-31", "releases"),
        # this week / month → period start .. now
        ("standups this week", "2026-05-25", "2026-05-29", "standups"),
        ("this month's deploys", "2026-05-01", "2026-05-29", "deploys"),
        # bare weekday (most recent, inclusive of today) → today is Friday
        ("the meeting friday", "2026-05-29", "2026-05-29", "the meeting"),
        # yesterday / today
        ("what broke yesterday", "2026-05-28", "2026-05-28", "what broke"),
        ("today's changes", "2026-05-29", "2026-05-29", "changes"),
        # recently → default 7-day window
        ("what have I touched recently", "2026-05-22", "2026-05-29",
         "what have I touched"),
    ],
)
def test_parse_temporal_table(
    query: str, exp_after: str, exp_before: str, exp_clean: str
) -> None:
    cleaned, tf = parse_temporal(query, NOW)
    assert tf is not None, f"expected temporal intent in {query!r}"
    assert tf.after is not None and tf.before is not None
    assert tf.after.date() == _d(exp_after), f"after for {query!r}"
    assert tf.before.date() == _d(exp_before), f"before for {query!r}"
    # day-bound conventions: after at 00:00, before at 23:59
    assert (tf.after.hour, tf.after.minute) == (0, 0)
    assert (tf.before.hour, tf.before.minute) == (23, 59)
    assert cleaned == exp_clean, f"cleaned query for {query!r}"


def test_no_temporal_intent_is_passthrough() -> None:
    q = "how does the auth middleware validate tokens"
    cleaned, tf = parse_temporal(q, NOW)
    assert tf is None
    assert cleaned == q


def test_as_filters_maps_to_query_contract() -> None:
    _cleaned, tf = parse_temporal("deploys this week", NOW)
    assert tf is not None
    f = tf.as_filters()
    assert set(f) == {"created_after", "created_before"}
    assert f["created_after"].date() == _d("2026-05-25")


def test_matched_phrase_recorded() -> None:
    _cleaned, tf = parse_temporal("the bug I hit last friday", NOW)
    assert tf is not None
    assert tf.matched.lower() == "last friday"


def test_stripping_empty_keeps_original() -> None:
    # A query that is ONLY a temporal phrase should not collapse to "".
    cleaned, tf = parse_temporal("yesterday", NOW)
    assert tf is not None
    assert cleaned == "yesterday"
