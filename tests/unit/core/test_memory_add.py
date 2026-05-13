"""memory.add() — basic insert + supersession atomicity (SC-002)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    MemoryRecord,
    MemoryScope,
    memory_text_hash,
)
from stele.storage.memory_store.sqlite import SQLiteMemoryStore


def _make(record_id: str, text: str = "hello", scope: MemoryScope | None = None) -> MemoryRecord:
    scope = scope or MemoryScope(user_id="alice")
    now = datetime.now(UTC)
    return MemoryRecord(
        id=record_id,
        text=text,
        kind="fact",
        scope=scope,
        source_refs=["stele://ns/" + record_id],
        created_at=now,
        updated_at=now,
        effective_from=now,
    )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteMemoryStore:
    s = SQLiteMemoryStore(tmp_path / "m.db")
    s.initialize()
    return s


def test_add_persists_record(store: SQLiteMemoryStore) -> None:
    r = _make("m1")
    stored, sup = store.add(r, supersedes=[])
    assert stored.id == "m1"
    assert sup == []
    fetched = store.get("m1")
    assert fetched is not None
    assert fetched.text == "hello"
    assert fetched.status == "active"


def test_get_returns_none_for_missing(store: SQLiteMemoryStore) -> None:
    assert store.get("does-not-exist") is None


def test_add_with_supersedes_marks_old_records(store: SQLiteMemoryStore) -> None:
    a = _make("m_a", text="old preference")
    store.add(a, supersedes=[])
    b = _make("m_b", text="new preference")
    stored, sup = store.add(b, supersedes=["m_a"])
    assert sup == ["m_a"]
    old = store.get("m_a")
    assert old is not None
    assert old.status == "superseded"
    assert old.effective_until is not None
    new = store.get("m_b")
    assert new is not None
    assert new.status == "active"


def test_add_supersedes_missing_id_raises_and_keeps_new_unsaved(
    store: SQLiteMemoryStore,
) -> None:
    r = _make("m_new", text="new")
    with pytest.raises(ArtifactNotFound):
        store.add(r, supersedes=["does-not-exist"])
    # SC-002 atomicity: the new record must NOT have been inserted
    assert store.get("m_new") is None


def test_find_duplicate_returns_id_for_same_scope_same_text(
    store: SQLiteMemoryStore,
) -> None:
    scope = MemoryScope(user_id="alice")
    r = _make("m1", text="duplicate me", scope=scope)
    store.add(r, supersedes=[])
    h = memory_text_hash("duplicate me", scope)
    assert store.find_duplicate(scope, h) == "m1"


def test_find_duplicate_returns_none_for_different_scope(
    store: SQLiteMemoryStore,
) -> None:
    r = _make("m1", text="duplicate me", scope=MemoryScope(user_id="alice"))
    store.add(r, supersedes=[])
    h = memory_text_hash("duplicate me", MemoryScope(user_id="bob"))
    assert store.find_duplicate(MemoryScope(user_id="bob"), h) is None
