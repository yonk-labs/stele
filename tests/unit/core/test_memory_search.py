"""memory.search() — default filter, as_of, include_superseded (SC-003)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele.core.memory_record import MemoryQuery, MemoryRecord, MemoryScope
from stele.storage.memory_store.sqlite import SQLiteMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteMemoryStore:
    s = SQLiteMemoryStore(tmp_path / "m.db")
    s.initialize()
    return s


def _record(
    id_: str, text: str, effective_from: datetime, scope: MemoryScope | None = None
) -> MemoryRecord:
    return MemoryRecord(
        id=id_,
        text=text,
        kind="preference",
        scope=scope or MemoryScope(user_id="alice"),
        source_refs=[f"stele://ns/{id_}"],
        created_at=effective_from,
        updated_at=effective_from,
        effective_from=effective_from,
    )


def test_search_returns_active_matches(store: SQLiteMemoryStore) -> None:
    now = datetime.now(UTC)
    store.add(_record("m1", "user prefers Helix editor", now), supersedes=[])
    hits = store.search(
        MemoryQuery(query="Helix", scope=MemoryScope(user_id="alice"))
    )
    assert [h.id for h in hits] == ["m1"]


def test_search_hides_superseded_by_default(store: SQLiteMemoryStore) -> None:
    t0 = datetime.now(UTC) - timedelta(days=2)
    t1 = datetime.now(UTC)
    store.add(_record("old", "user prefers Helix", t0), supersedes=[])
    store.add(_record("new", "user prefers Zed", t1), supersedes=["old"])
    hits = store.search(
        MemoryQuery(query="prefers", scope=MemoryScope(user_id="alice"))
    )
    ids = {h.id for h in hits}
    assert ids == {"new"}


def test_search_include_superseded_returns_both(store: SQLiteMemoryStore) -> None:
    t0 = datetime.now(UTC) - timedelta(days=2)
    t1 = datetime.now(UTC)
    store.add(_record("old", "user prefers Helix", t0), supersedes=[])
    store.add(_record("new", "user prefers Zed", t1), supersedes=["old"])
    hits = store.search(
        MemoryQuery(
            query="prefers",
            scope=MemoryScope(user_id="alice"),
            include_superseded=True,
        )
    )
    ids = {h.id for h in hits}
    assert ids == {"old", "new"}


def test_search_as_of_returns_historical_view(store: SQLiteMemoryStore) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)
    store.add(_record("old", "user prefers Helix", t0), supersedes=[])
    store.add(_record("new", "user prefers Zed", t1), supersedes=["old"])
    mid = datetime(2026, 1, 15, tzinfo=UTC)
    hits = store.search(
        MemoryQuery(
            query="prefers",
            scope=MemoryScope(user_id="alice"),
            as_of=mid,
        )
    )
    ids = {h.id for h in hits}
    assert ids == {"old"}


def test_search_filters_by_scope(store: SQLiteMemoryStore) -> None:
    now = datetime.now(UTC)
    store.add(
        _record("ma", "shared text", now, scope=MemoryScope(user_id="alice")),
        supersedes=[],
    )
    store.add(
        _record("mb", "shared text", now, scope=MemoryScope(user_id="bob")),
        supersedes=[],
    )
    hits = store.search(
        MemoryQuery(query="shared", scope=MemoryScope(user_id="alice"))
    )
    assert [h.id for h in hits] == ["ma"]
