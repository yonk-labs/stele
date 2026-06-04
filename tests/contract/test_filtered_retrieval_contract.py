"""Contract: query(filters=...) honors created_at + metadata across backends.

Validates the filter-then-rank primitive (docs/archive/session-memory-metadata-design.md)
on the keyword path. memory + sqlite run for real; postgres/mariadb/clickhouse
run when their DSN env vars are set.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid
from importlib.util import find_spec
from pathlib import Path

import pytest

from stele import Stele


def _backends() -> list[str]:
    bk = ["memory", "sqlite"]
    if os.environ.get("STELE_PG_DSN"):
        bk.append("postgres")
    if os.environ.get("STELE_MARIADB_DSN") and find_spec("MySQLdb"):
        bk.append("mariadb")
    if os.environ.get("STELE_CLICKHOUSE_DSN") and find_spec("clickhouse_connect"):
        bk.append("clickhouse")
    return bk


def _stash(backend: str, tmp_path: Path) -> Stele:
    if backend == "memory":
        return Stele.from_config({"backend": {"type": "memory"}})
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp_path / "s.db")}})
    if backend == "postgres":
        return Stele.from_config(
            {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}})
    if backend == "mariadb":
        return Stele.from_config(
            {"backend": {"type": "mariadb", "dsn": os.environ["STELE_MARIADB_DSN"]}})
    return Stele.from_config(
        {"backend": {"type": "clickhouse", "dsn": os.environ["STELE_CLICKHOUSE_DSN"]}})


@pytest.mark.parametrize("backend", _backends())
def test_metadata_range_filter_then_rank(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, tmp_path)
    ns = f"flt_{uuid.uuid4().hex[:8]}"
    # Two vocabulary-overlapping facts on different dates. Rank-alone can pick
    # either; the date filter must isolate the in-window one.
    stash.store("fixed the authentication login bug in the user service",
                namespace=ns, metadata={"date": "2026-03-02"})
    stash.store("fixed the authentication token refresh bug and tests",
                namespace=ns, metadata={"date": "2026-05-20"})

    # No filter: both are candidates for "authentication bug".
    unfiltered = stash.query(ns, "authentication bug", limit=10)
    dates = {h.metadata.get("date") for h in unfiltered}
    assert dates == {"2026-03-02", "2026-05-20"}, f"{backend}: expected both, got {dates}"

    # Filter to the last-week window -> only the in-window fact survives.
    filtered = stash.query(ns, "authentication bug", limit=10, filters={
        "metadata.date__gte": "2026-05-18",
        "metadata.date__lte": "2026-05-24",
    })
    assert filtered, f"{backend}: filtered query returned nothing"
    assert all(h.metadata.get("date") == "2026-05-20" for h in filtered), (
        f"{backend}: filter leaked out-of-window rows: "
        f"{[h.metadata.get('date') for h in filtered]}"
    )
    stash.close()


@pytest.mark.parametrize("backend", _backends())
def test_metadata_eq_filter(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, tmp_path)
    ns = f"flteq_{uuid.uuid4().hex[:8]}"
    stash.store("refactored the parser on the auth branch",
                namespace=ns, metadata={"branch": "auth"})
    stash.store("refactored the parser on the main branch",
                namespace=ns, metadata={"branch": "main"})
    hits = stash.query(ns, "refactored the parser", limit=10,
                       filters={"metadata.branch": "auth"})
    assert hits, f"{backend}: eq-filtered query returned nothing"
    assert all(h.metadata.get("branch") == "auth" for h in hits), backend
    stash.close()


def test_vector_path_honors_metadata_filter(tmp_path: Path) -> None:
    # mode=vector goes through the chunk store + _scope_namespace, a different
    # filter site than the keyword backends. Verify it filters too.
    stash = Stele.from_config({
        "backend": {"type": "sqlite", "path": str(tmp_path / "s.db")},
        "indexing": {"mode": "sync", "provider": "chunkshop"},
        "retrieval": {"default_mode": "vector"},
    })
    ns = f"vflt_{uuid.uuid4().hex[:8]}"
    stash.store("fixed the authentication login bug in the user service",
                namespace=ns, metadata={"date": "2026-03-02"})
    stash.store("fixed the authentication token refresh bug and tests",
                namespace=ns, metadata={"date": "2026-05-20"})
    filtered = stash.query(ns, "authentication bug", limit=5, mode="vector", filters={
        "metadata.date__gte": "2026-05-18", "metadata.date__lte": "2026-05-24",
    })
    assert filtered, "vector filtered query returned nothing"
    assert all(h.metadata.get("date") == "2026-05-20" for h in filtered), (
        f"vector filter leaked: {[h.metadata.get('date') for h in filtered]}"
    )
    stash.close()


def _routing_stash() -> Stele:
    return Stele.from_config({
        "backend": {"type": "memory"},
        "retrieval": {"temporal_routing": True, "temporal_date_field": "date"},
    })


def test_temporal_routing_gate_auto_filters() -> None:
    s = _routing_stash()
    ns = f"rt_{uuid.uuid4().hex[:8]}"
    s.store("fixed the authentication login bug", namespace=ns, metadata={"date": "2026-03-02"})
    s.store("fixed the authentication token bug", namespace=ns, metadata={"date": "2026-05-20"})
    now = dt.datetime(2026, 5, 29, 12, 0)
    # No explicit filters — routing parses "last week" and filters automatically.
    hits = s.query(ns, "what authentication bug did I fix last week", now=now, limit=5)
    assert hits and all(h.metadata.get("date") == "2026-05-20" for h in hits)
    s.close()


def test_temporal_routing_empty_window_falls_back() -> None:
    s = _routing_stash()
    ns = f"rtfb_{uuid.uuid4().hex[:8]}"
    s.store("fixed the authentication bug", namespace=ns, metadata={"date": "2026-05-20"})
    now = dt.datetime(2026, 5, 29, 12, 0)
    # "5 years ago" window has no data -> must retry unfiltered, not return [].
    hits = s.query(ns, "authentication bug 5 years ago", now=now, limit=5)
    assert hits, "empty-window query should fall back to unfiltered, not return nothing"
    s.close()


def test_temporal_routing_off_by_default() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = f"rtoff_{uuid.uuid4().hex[:8]}"
    s.store("fixed the authentication bug last week", namespace=ns, metadata={"date": "2026-05-20"})
    # routing off -> "last week" is just query text, no auto-filter, returns the hit.
    hits = s.query(ns, "authentication bug last week", limit=5)
    assert hits
    s.close()


@pytest.mark.parametrize("backend", _backends())
def test_created_at_range_filter(backend: str, tmp_path: Path) -> None:
    # created_at is stamped "now"; an open-ended past window keeps everything,
    # a future-only window excludes everything — proves the bound is applied.
    stash = _stash(backend, tmp_path)
    ns = f"fltts_{uuid.uuid4().hex[:8]}"
    stash.store("the deploy script timed out", namespace=ns)
    past = dt.datetime(2000, 1, 1)
    future = dt.datetime(2999, 1, 1)
    assert stash.query(ns, "deploy script", limit=5, filters={"created_after": past})
    assert not stash.query(ns, "deploy script", limit=5, filters={"created_after": future})
    stash.close()
