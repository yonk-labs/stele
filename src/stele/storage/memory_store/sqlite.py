"""SQLite MemoryStore — schema migration + connection management.

Operations (add/search/list/etc.) land in subsequent tasks.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  kind TEXT NOT NULL
    CHECK (kind IN ('fact','preference','decision','instruction','commitment','issue','summary')),
  user_id TEXT,
  agent_id TEXT,
  app_id TEXT,
  session_id TEXT,
  namespace TEXT NOT NULL DEFAULT 'default',
  source_refs TEXT NOT NULL,
  source_chunk_ids TEXT NOT NULL DEFAULT '[]',
  confidence REAL NOT NULL DEFAULT 1.0,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','superseded','retracted','disputed','deleted')),
  supersedes TEXT NOT NULL DEFAULT '[]',
  text_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_until TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  pii_flags TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_memories_scope
  ON memories(namespace, user_id, agent_id, app_id, session_id);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_effective
  ON memories(effective_from, effective_until);
CREATE INDEX IF NOT EXISTS idx_memories_text_hash
  ON memories(text_hash, namespace, user_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
  USING fts5(text, content='memories', content_rowid='rowid');

CREATE TRIGGER IF NOT EXISTS memories_fts_insert
  AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
  END;
CREATE TRIGGER IF NOT EXISTS memories_fts_delete
  AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text)
      VALUES('delete', old.rowid, old.text);
  END;
CREATE TRIGGER IF NOT EXISTS memories_fts_update
  AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text)
      VALUES('delete', old.rowid, old.text);
    INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
  END;
"""


class SQLiteMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
