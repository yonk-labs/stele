"""Temporal query routing — turn "what did I do last Friday" into a date filter.

A pure, deterministic, LLM-free parser. It detects a temporal expression in a
query, resolves it to a ``[after, before]`` range relative to a caller-supplied
``now``, and returns the query with that phrase stripped (the date words are
noise for the embedding, so removing them sharpens the semantic match).

Design rationale lives in ``docs/archive/session-memory-metadata-design.md``: embeddings
cannot rank dates, so temporal recall must become an exact range *filter* +
semantic *rank*. This module is the front door that builds the filter. It is
opt-in (the caller decides whether to route) and requires an explicit ``now``
so relative dates ("last Friday") never silently depend on wall-clock state.

Usage::

    cleaned, tf = parse_temporal("what was I building last week", now)
    if tf is not None:
        hits = stele.query(ns, cleaned, filters=tf.as_filters())
    else:
        hits = stele.query(ns, query)

Returns ``(query, None)`` unchanged when there is no temporal intent — zero
behaviour change for non-temporal queries.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

_WEEKDAYS = {
    name: i for i, name in enumerate(
        ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    )
}
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}

# How far back a vague "recently"/"lately" reaches when nothing else is given.
DEFAULT_RECENT_DAYS = 7


@dataclass(frozen=True)
class TemporalFilter:
    """A resolved date window. ``after``/``before`` are inclusive day bounds."""

    after: dt.datetime | None
    before: dt.datetime | None
    matched: str  # the phrase that was stripped (telemetry/debugging)

    def as_filters(self) -> dict[str, dt.datetime]:
        """Map to the ``query(filters=...)`` contract keys (filter on created_at)."""
        out: dict[str, dt.datetime] = {}
        if self.after is not None:
            out["created_after"] = self.after
        if self.before is not None:
            out["created_before"] = self.before
        return out

    def as_metadata_filters(self, field: str) -> dict[str, str]:
        """Map the window onto a metadata date field (ISO ``YYYY-MM-DD``).

        Use when the relevant timestamp lives in ``metadata[field]`` rather than
        the artifact's ``created_at`` — e.g. a session/event date. ISO strings
        compare correctly lexicographically, sidestepping tz normalisation.
        """
        out: dict[str, str] = {}
        if self.after is not None:
            out[f"metadata.{field}__gte"] = self.after.date().isoformat()
        if self.before is not None:
            out[f"metadata.{field}__lte"] = self.before.date().isoformat()
        return out


def _sod(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, 0, 0, 0)


def _eod(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, 23, 59, 59)


def _last_weekday(today: dt.date, target: int, *, inclusive: bool) -> dt.date:
    """Most recent date with weekday ``target``. inclusive=True allows today."""
    delta = (today.weekday() - target) % 7
    if delta == 0 and not inclusive:
        delta = 7
    return today - dt.timedelta(days=delta)


def _month_start(d: dt.date) -> dt.date:
    return d.replace(day=1)


def _prev_month_range(d: dt.date) -> tuple[dt.date, dt.date]:
    first_this = d.replace(day=1)
    last_prev = first_this - dt.timedelta(days=1)
    return last_prev.replace(day=1), last_prev


# Pattern table. Each entry: (compiled regex, resolver(now, match) -> (after, before)).
# Order matters — more specific patterns first. Resolvers return date bounds;
# None means "unbounded on that side".
_Bound = tuple[dt.date | None, dt.date | None]


def _r_last_n_units(now: dt.date, m: re.Match[str]) -> _Bound:
    n = int(m.group("n"))
    unit = m.group("unit").rstrip("s")
    return now - dt.timedelta(days=_UNIT_DAYS[unit] * n), now


def _r_n_units_ago(now: dt.date, m: re.Match[str]) -> _Bound:
    n = int(m.group("n"))
    unit = m.group("unit").rstrip("s")
    day = now - dt.timedelta(days=_UNIT_DAYS[unit] * n)
    return day, day  # a point in time -> single-day window


def _r_last_unit(now: dt.date, m: re.Match[str]) -> _Bound:
    unit = m.group("unit").rstrip("s")
    if unit == "week":
        this_mon = now - dt.timedelta(days=now.weekday())
        return this_mon - dt.timedelta(days=7), this_mon - dt.timedelta(days=1)
    if unit == "month":
        return _prev_month_range(now)
    if unit == "year":
        return dt.date(now.year - 1, 1, 1), dt.date(now.year - 1, 12, 31)
    return now - dt.timedelta(days=7), now  # fallback


def _r_this_unit(now: dt.date, m: re.Match[str]) -> _Bound:
    unit = m.group("unit").rstrip("s")
    if unit == "week":
        return now - dt.timedelta(days=now.weekday()), now
    if unit == "month":
        return _month_start(now), now
    if unit == "year":
        return dt.date(now.year, 1, 1), now
    return now, now


def _r_last_weekday(now: dt.date, m: re.Match[str]) -> _Bound:
    wd = _WEEKDAYS[m.group("wd").lower()]
    day = _last_weekday(now, wd, inclusive=False)
    return day, day


def _r_this_or_bare_weekday(now: dt.date, m: re.Match[str]) -> _Bound:
    wd = _WEEKDAYS[m.group("wd").lower()]
    day = _last_weekday(now, wd, inclusive=True)
    return day, day


def _r_yesterday(now: dt.date, m: re.Match[str]) -> _Bound:
    y = now - dt.timedelta(days=1)
    return y, y


def _r_today(now: dt.date, m: re.Match[str]) -> _Bound:
    return now, now


def _r_recently(now: dt.date, m: re.Match[str]) -> _Bound:
    return now - dt.timedelta(days=DEFAULT_RECENT_DAYS), now


def _r_since_units(now: dt.date, m: re.Match[str]) -> _Bound:
    # "since N days/weeks ago" or "in the past ..." -> open-ended to now.
    n = int(m.group("n")) if m.groupdict().get("n") else 1
    unit = (m.group("unit") or "week").rstrip("s")
    return now - dt.timedelta(days=_UNIT_DAYS[unit] * n), now


_WD = "(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_UNIT = "(?P<unit>day|days|week|weeks|month|months|year|years)"

_LAST_N = rf"\b(?:in|over|within|during)?\s*(?:the\s+)?(?:last|past)\s+(?P<n>\d+)\s+{_UNIT}\b"

_PATTERNS: list[tuple[re.Pattern[str], object]] = [
    # "(in/over the) last/past N units"
    (re.compile(_LAST_N, re.I), _r_last_n_units),
    # "N units ago"
    (re.compile(rf"\b(?P<n>\d+)\s+{_UNIT}\s+ago\b", re.I), _r_n_units_ago),
    # "since N units ago" / "since last week"
    (re.compile(rf"\bsince\s+(?:the\s+)?(?:last\s+)?(?:(?P<n>\d+)\s+)?{_UNIT}(?:\s+ago)?\b", re.I),
     _r_since_units),
    # "last <weekday>"
    (re.compile(rf"\blast\s+{_WD}\b", re.I), _r_last_weekday),
    # "last week/month/year"
    (re.compile(rf"\blast\s+{_UNIT}\b", re.I), _r_last_unit),
    # "this week/month/year"
    (re.compile(rf"\bthis\s+{_UNIT}\b", re.I), _r_this_unit),
    # "this <weekday>" / bare "<weekday>"
    (re.compile(rf"\b(?:this\s+)?{_WD}\b", re.I), _r_this_or_bare_weekday),
    # "yesterday" / "today"
    (re.compile(r"\byesterday\b", re.I), _r_yesterday),
    (re.compile(r"\btoday\b", re.I), _r_today),
    # "recently" / "lately"
    (re.compile(r"\b(?:recently|lately)\b", re.I), _r_recently),
]


def _clean(query: str, span: tuple[int, int]) -> str:
    """Remove the matched temporal span and tidy up.

    Deliberately minimal: drop the phrase, consume a possessive ``'s`` that
    abutted it ("today's" -> ""), collapse whitespace, trim stray punctuation.
    We do NOT strip surrounding prepositions/articles — "the bug" and "working
    on" are content, not connectives, and guessing wrong mangles the query.
    """
    start, end = span
    if query[end : end + 2] == "'s":  # "today's" / "this month's"
        end += 2
    out = query[:start] + " " + query[end:]
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out.strip(" ,.")


def parse_temporal(
    query: str, now: dt.datetime
) -> tuple[str, TemporalFilter | None]:
    """Detect + resolve a temporal expression in ``query`` relative to ``now``.

    Returns ``(cleaned_query, TemporalFilter)`` when temporal intent is found,
    else ``(query, None)`` unchanged. ``now`` is required so relative dates are
    explicit and replay-safe.
    """
    today = now.date()
    for pattern, resolver in _PATTERNS:
        m = pattern.search(query)
        if not m:
            continue
        after_d, before_d = resolver(today, m)  # type: ignore[operator]
        cleaned = _clean(query, m.span())
        # If stripping leaves nothing useful, keep the original query text.
        if not cleaned:
            cleaned = query
        return cleaned, TemporalFilter(
            after=_sod(after_d) if after_d is not None else None,
            before=_eod(before_d) if before_d is not None else None,
            matched=m.group(0).strip(),
        )
    return query, None
