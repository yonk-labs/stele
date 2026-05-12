"""SQLite memory schema migration test (SC-001)."""

from pathlib import Path

import pytest

from stele.storage.memory_store.sqlite import SQLiteMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteMemoryStore:
    s = SQLiteMemoryStore(tmp_path / "memory.db")
    s.initialize()
    return s


def test_memories_table_exists(store: SQLiteMemoryStore) -> None:
    cur = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
    )
    assert cur.fetchone() is not None


def test_memories_columns_present(store: SQLiteMemoryStore) -> None:
    cur = store.conn.execute("PRAGMA table_info(memories)")
    cols = {row[1] for row in cur.fetchall()}
    expected = {
        "id", "text", "kind", "user_id", "agent_id", "app_id", "session_id",
        "namespace", "source_refs", "source_chunk_ids", "confidence", "status",
        "supersedes", "text_hash", "created_at", "updated_at",
        "effective_from", "effective_until", "metadata", "pii_flags",
    }
    missing = expected - cols
    assert not missing, f"missing columns: {missing}"


def test_memories_indexes_present(store: SQLiteMemoryStore) -> None:
    cur = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memories'"
    )
    names = {row[0] for row in cur.fetchall()}
    for required in (
        "idx_memories_scope",
        "idx_memories_status",
        "idx_memories_effective",
        "idx_memories_text_hash",
    ):
        assert required in names, f"missing index: {required}"


def test_memories_fts_table_exists(store: SQLiteMemoryStore) -> None:
    cur = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
    )
    assert cur.fetchone() is not None


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    s1 = SQLiteMemoryStore(db)
    s1.initialize()
    s1.close()
    s2 = SQLiteMemoryStore(db)
    s2.initialize()  # should not raise
    cur = s2.conn.execute("SELECT count(*) FROM memories")
    assert cur.fetchone()[0] == 0
