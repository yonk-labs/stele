"""Tests for Memory.search_with_score across backends (in-process scope here)."""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime

from stele.core.memory_record import MemoryRecord, MemoryScope, ScoredMemoryHit
from stele.storage.memory_store.memory import InProcessMemoryStore
from stele.storage.memory_store.sqlite import SQLiteMemoryStore


def _record(id_: str, text: str, refs: list[str]) -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id=id_,
        text=text,
        kind="fact",
        scope=MemoryScope(user_id="alice"),
        source_refs=refs,
        created_at=now,
        updated_at=now,
        effective_from=now,
    )


def test_in_process_search_with_score_returns_scored_hits() -> None:
    store = InProcessMemoryStore()
    store.add(_record("m1", "user prefers dark mode", ["stele://default/a"]), [])
    store.add(_record("m2", "user prefers cold brew", ["stele://default/b"]), [])
    store.add(_record("m3", "completely unrelated", ["stele://default/c"]), [])

    hits = store.search_with_score(
        "dark mode",
        scope=MemoryScope(user_id="alice"),
        limit=5,
    )
    assert isinstance(hits, list)
    assert all(isinstance(h, ScoredMemoryHit) for h in hits)
    assert hits, "expected at least one hit on a keyword match"
    assert hits[0].record.id == "m1"
    assert all(0.0 <= h.score <= 1.0 for h in hits)


def test_in_process_search_with_score_filters_by_source_ref() -> None:
    store = InProcessMemoryStore()
    store.add(_record("m1", "dark mode preferred", ["stele://default/a"]), [])
    store.add(_record("m2", "dark mode preferred", ["stele://default/b"]), [])

    hits = store.search_with_score(
        "dark",
        scope=MemoryScope(user_id="alice"),
        limit=5,
        source_ref_filter="stele://default/a",
    )
    assert len(hits) == 1
    assert hits[0].record.id == "m1"


def test_in_process_search_with_score_limit_respected() -> None:
    store = InProcessMemoryStore()
    for i in range(10):
        store.add(_record(f"m{i}", f"common term {i}", [f"stele://default/a{i}"]), [])

    hits = store.search_with_score(
        "common",
        scope=MemoryScope(user_id="alice"),
        limit=3,
    )
    assert len(hits) <= 3


def _make_sqlite_store(tmp_path: pathlib.Path) -> SQLiteMemoryStore:
    return SQLiteMemoryStore(str(tmp_path / "memory.db"))


def test_sqlite_search_with_score_keyword_match(tmp_path: pathlib.Path) -> None:
    store = _make_sqlite_store(tmp_path)
    store.initialize()
    store.add(_record("m1", "user prefers dark mode for the dashboard", ["stele://default/a"]), [])
    store.add(_record("m2", "user prefers cold brew", ["stele://default/b"]), [])

    hits = store.search_with_score(
        "dark mode",
        scope=MemoryScope(user_id="alice"),
        limit=5,
    )
    assert hits
    assert hits[0].record.id == "m1"


def test_sqlite_search_with_score_filters_by_source_ref(tmp_path: pathlib.Path) -> None:
    store = _make_sqlite_store(tmp_path)
    store.initialize()
    store.add(_record("m1", "dark mode preferred", ["stele://default/a"]), [])
    store.add(_record("m2", "dark mode preferred", ["stele://default/b"]), [])

    hits = store.search_with_score(
        "dark",
        scope=MemoryScope(user_id="alice"),
        limit=5,
        source_ref_filter="stele://default/a",
    )
    assert len(hits) == 1
    assert hits[0].record.id == "m1"


def test_sqlite_search_with_score_handles_fts5_special_chars(
    tmp_path: pathlib.Path,
) -> None:
    """Natural-language queries (ending in '?', containing quotes, etc.) must
    not raise ``fts5: syntax error``. Regression for the recall path crashing
    on SQLite with a question-style query.
    """
    store = _make_sqlite_store(tmp_path)
    store.initialize()
    store.add(_record("m1", "Alice prefers the Helix editor", ["stele://default/a"]), [])

    for query in (
        "what editor does Alice prefer?",
        'who said "Helix"?',
        "editor: prefer*",
        "(Alice) -Vim",
        "???",
    ):
        hits = store.search_with_score(query, scope=MemoryScope(user_id="alice"))
        assert isinstance(hits, list)  # no exception, well-formed result

    assert store.search_with_score(
        "editor preference?", scope=MemoryScope(user_id="alice")
    )[0].record.id == "m1"


def test_sqlite_memory_search_handles_fts5_special_chars(
    tmp_path: pathlib.Path,
) -> None:
    """Phase 1 Memory.search has the same FTS5 surface — same guarantee."""
    from stele.core.memory_record import MemoryQuery

    store = _make_sqlite_store(tmp_path)
    store.initialize()
    store.add(_record("m1", "Alice prefers the Helix editor", ["stele://default/a"]), [])

    hits = store.search(
        MemoryQuery(query="what editor does Alice prefer?", scope=MemoryScope(user_id="alice"))
    )
    assert [h.id for h in hits] == ["m1"]
