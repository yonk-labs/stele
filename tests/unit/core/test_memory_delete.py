"""memory.delete() soft semantics + list() filtering (SC-005)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from stele.core.memory_record import MemoryQuery, MemoryRecord, MemoryScope
from stele.storage.memory_store.sqlite import SQLiteMemoryStore


def _r(id_: str, text: str = "x") -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id=id_, text=text, kind="fact",
        scope=MemoryScope(user_id="alice"),
        source_refs=[f"stele://ns/{id_}"],
        created_at=now, updated_at=now, effective_from=now,
    )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteMemoryStore:
    s = SQLiteMemoryStore(tmp_path / "m.db")
    s.initialize()
    return s


def test_soft_delete_flips_status(store: SQLiteMemoryStore) -> None:
    store.add(_r("m1"), supersedes=[])
    store.soft_delete("m1")
    got = store.get("m1")
    assert got is not None
    assert got.status == "deleted"


def test_search_excludes_deleted(store: SQLiteMemoryStore) -> None:
    store.add(_r("m1", "find me"), supersedes=[])
    store.soft_delete("m1")
    hits = store.search(
        MemoryQuery(query="find", scope=MemoryScope(user_id="alice"))
    )
    assert hits == []


def test_search_include_superseded_does_not_resurrect_deleted(
    store: SQLiteMemoryStore,
) -> None:
    store.add(_r("m1", "find me"), supersedes=[])
    store.soft_delete("m1")
    hits = store.search(
        MemoryQuery(
            query="find",
            scope=MemoryScope(user_id="alice"),
            include_superseded=True,
        )
    )
    assert hits == []


def test_list_default_excludes_deleted(store: SQLiteMemoryStore) -> None:
    store.add(_r("alive"), supersedes=[])
    store.add(_r("doomed"), supersedes=[])
    store.soft_delete("doomed")
    items = store.list(MemoryScope(user_id="alice"))
    ids = {r.id for r in items}
    assert ids == {"alive"}


def test_update_metadata_only(store: SQLiteMemoryStore) -> None:
    store.add(_r("m1"), supersedes=[])
    updated = store.update_metadata("m1", {"tag": "important"})
    assert updated.metadata["tag"] == "important"
