"""Session-memory temporal-routing demo — does filter-then-rank beat rank-alone?

LoCoMo cannot test this (its temporal questions ask FOR a date, not BY a
recency window — only 58/1540 trigger the parser, and those are speaker-relative
not asker-relative). This is the right instrument: dated work-sessions with
overlapping vocabulary, and recency-window queries ("what auth work did I do
last week"). We compare two retrieval paths through the real Stele facade:

  baseline : query(ns, raw_query)                       # rank-alone
  routed   : query(ns, cleaned_query, filters=window)   # filter-then-rank
             via parse_temporal(raw_query, now)

Each query has a correct in-window session AND an out-of-window distractor that
shares vocabulary, so rank-alone is tempted to the wrong date. Metric: does the
top hit fall inside the intended window (correct) vs outside (distractor)?

Run: python -m benchmarks.external.session_memory_demo
"""
from __future__ import annotations

import datetime as dt

from stele.core.config import BackendConfig, StashConfig
from stele.core.stash import Stele
from stele.retrieval.temporal import parse_temporal

NOW = dt.datetime(2026, 5, 29, 12, 0)  # Friday
NS = "sessions"

# (date, text). Pairs share vocabulary across an in-window / out-of-window split.
SESSIONS: list[tuple[str, str]] = [
    # auth pair — distractor old, target last week
    ("2026-03-02", "fixed the authentication login bug in the user service"),
    ("2026-05-20", "fixed the authentication token refresh bug and added tests"),
    # parser pair
    ("2026-01-15", "wrote the markdown parser for the docs pipeline"),
    ("2026-05-19", "wrote the temporal query parser for session memory"),
    # deploy pair
    ("2026-04-10", "debugged the staging deploy script timeout"),
    ("2026-05-22", "debugged the production deploy script rollback step"),
    # db pair
    ("2026-02-08", "optimized the postgres index on the orders table"),
    ("2026-05-21", "optimized the postgres connection pool settings"),
    # unrelated filler in-window + out
    ("2026-05-18", "reviewed the quarterly roadmap with the team"),
    ("2026-05-01", "onboarded a new engineer to the codebase"),
]

# (raw query, expected in-window date). All "last week" = 2026-05-18..05-24.
QUERIES: list[tuple[str, str]] = [
    ("what authentication bug did I fix last week", "2026-05-20"),
    ("what parser did I write last week", "2026-05-19"),
    ("what deploy script issue did I debug last week", "2026-05-22"),
    ("what postgres optimization did I do last week", "2026-05-21"),
]


def _in_window(date: str, after: dt.datetime, before: dt.datetime) -> bool:
    d = dt.date.fromisoformat(date)
    return after.date() <= d <= before.date()


def main() -> None:
    stash = Stele(config=StashConfig(backend=BackendConfig(type="memory")))
    for date, text in SESSIONS:
        stash.store(text, namespace=NS, metadata={"date": date})

    base_correct = routed_correct = 0
    print(f"now = {NOW.date()} (Friday); 'last week' = 2026-05-18 .. 2026-05-24\n")
    for raw, expected in QUERIES:
        cleaned, tf = parse_temporal(raw, NOW)
        assert tf is not None, f"parser missed temporal intent in {raw!r}"
        mf = tf.as_metadata_filters("date")

        base = stash.query(NS, raw, limit=1)
        routed = stash.query(NS, cleaned, limit=1, filters=mf)

        b_date = base[0].metadata.get("date", "—") if base else "—"
        r_date = routed[0].metadata.get("date", "—") if routed else "—"
        b_ok = bool(base) and b_date == expected
        r_ok = bool(routed) and r_date == expected
        base_correct += b_ok
        routed_correct += r_ok

        print(f"Q: {raw}")
        print(f"   expected in-window: {expected}")
        print(f"   baseline top: {b_date:11s} {'✓' if b_ok else '✗'}   "
              f"routed top: {r_date:11s} {'✓' if r_ok else '✗'}")
    n = len(QUERIES)
    print(f"\nbaseline (rank-alone):   {base_correct}/{n} correct")
    print(f"routed   (filter+rank):  {routed_correct}/{n} correct")
    stash.close()


if __name__ == "__main__":
    main()
