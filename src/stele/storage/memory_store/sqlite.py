"""SQLite MemoryStore — schema migration + connection management.

Operations (add/search/list/etc.) land in subsequent tasks.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    ScoredMemoryHit,
    memory_text_hash,
)


def _fts_query(query: str) -> str:
    """Make a user query safe for FTS5 MATCH.

    Raw user text can contain FTS5 operators (``?``, ``"``, ``*``, ``:``,
    ``(``, ``-`` …) that raise ``fts5: syntax error``. Quoting each
    whitespace-separated term turns it into a literal phrase token; joining
    with ``OR`` gives ranked recall over any term. Mirrors the artifact
    retrieval layer's sanitizer (``stele.retrieval.sqlite._fts_query``).
    """
    terms = [term.replace('"', '""') for term in query.split() if term.strip()]
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms)


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


def _record_to_row(r: MemoryRecord) -> dict[str, object]:
    return {
        "id": r.id,
        "text": r.text,
        "kind": r.kind,
        "user_id": r.scope.user_id,
        "agent_id": r.scope.agent_id,
        "app_id": r.scope.app_id,
        "session_id": r.scope.session_id,
        "namespace": r.scope.namespace,
        "source_refs": json.dumps(r.source_refs),
        "source_chunk_ids": json.dumps(r.source_chunk_ids),
        "confidence": r.confidence,
        "status": r.status,
        "supersedes": json.dumps(r.supersedes),
        "text_hash": memory_text_hash(r.text, r.scope),
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
        "effective_from": r.effective_from.isoformat(),
        "effective_until": r.effective_until.isoformat() if r.effective_until else None,
        "metadata": json.dumps(r.metadata),
        "pii_flags": json.dumps(r.pii_flags),
    }


def _row_to_record(row: dict[str, object]) -> MemoryRecord:
    return MemoryRecord(
        id=str(row["id"]),
        text=str(row["text"]),
        kind=str(row["kind"]),  # type: ignore[arg-type]
        scope=MemoryScope(
            user_id=row["user_id"],  # type: ignore[arg-type]
            agent_id=row["agent_id"],  # type: ignore[arg-type]
            app_id=row["app_id"],  # type: ignore[arg-type]
            session_id=row["session_id"],  # type: ignore[arg-type]
            namespace=str(row["namespace"]),
        ),
        source_refs=json.loads(str(row["source_refs"])),
        source_chunk_ids=json.loads(str(row["source_chunk_ids"])),
        confidence=float(row["confidence"]),  # type: ignore[arg-type]
        status=str(row["status"]),  # type: ignore[arg-type]
        supersedes=json.loads(str(row["supersedes"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        effective_from=datetime.fromisoformat(str(row["effective_from"])),
        effective_until=(
            datetime.fromisoformat(str(row["effective_until"]))
            if row["effective_until"]
            else None
        ),
        metadata=json.loads(str(row["metadata"])),
        pii_flags=json.loads(str(row["pii_flags"])),
    )


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

    def add(
        self,
        record: MemoryRecord,
        supersedes: list[str],
    ) -> tuple[MemoryRecord, list[str]]:
        now = datetime.now(UTC).isoformat()
        cur = self.conn.cursor()
        try:
            cur.execute("BEGIN")
            for old_id in supersedes:
                affected = cur.execute(
                    "UPDATE memories SET status='superseded', "
                    "effective_until=?, updated_at=? WHERE id=?",
                    (now, now, old_id),
                ).rowcount
                if affected == 0:
                    raise ArtifactNotFound(f"memory not found: {old_id}")
            row = _record_to_row(record)
            cur.execute(
                "INSERT INTO memories ("
                "id, text, kind, user_id, agent_id, app_id, session_id, namespace,"
                "source_refs, source_chunk_ids, confidence, status, supersedes,"
                "text_hash, created_at, updated_at, effective_from, effective_until,"
                "metadata, pii_flags"
                ") VALUES ("
                ":id, :text, :kind, :user_id, :agent_id, :app_id, :session_id, :namespace,"
                ":source_refs, :source_chunk_ids, :confidence, :status, :supersedes,"
                ":text_hash, :created_at, :updated_at, :effective_from, :effective_until,"
                ":metadata, :pii_flags"
                ")",
                row,
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return record, list(supersedes)

    def get(self, memory_id: str) -> MemoryRecord | None:
        cur = self.conn.execute(
            "SELECT * FROM memories WHERE id=?", (memory_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_record(dict(row))

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        cur = self.conn.execute(
            "SELECT id FROM memories WHERE text_hash=? AND namespace=? "
            "AND user_id IS ? AND agent_id IS ? AND app_id IS ? AND session_id IS ? "
            "AND status NOT IN ('deleted','superseded') LIMIT 1",
            (
                text_hash,
                scope.namespace,
                scope.user_id,
                scope.agent_id,
                scope.app_id,
                scope.session_id,
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else None

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        as_of = (query.as_of or datetime.now(UTC)).isoformat()
        params: list[object] = [_fts_query(query.query), as_of]
        sql = [
            "SELECT memories.* FROM memories",
            "JOIN memories_fts ON memories.rowid = memories_fts.rowid",
            "WHERE memories_fts MATCH ?",
            "AND memories.effective_from <= ?",
        ]
        if not query.include_superseded:
            sql.append("AND (memories.effective_until IS NULL OR memories.effective_until > ?)")
            params.append(as_of)
            sql.append(
                "AND (memories.status = 'active'"
                " OR (memories.status = 'superseded' AND memories.effective_until > ?))"
            )
            params.append(as_of)
        else:
            sql.append("AND memories.status != 'deleted'")
        sql.append("AND memories.namespace = ?")
        params.append(query.scope.namespace)
        for field, value in (
            ("user_id", query.scope.user_id),
            ("agent_id", query.scope.agent_id),
            ("app_id", query.scope.app_id),
            ("session_id", query.scope.session_id),
        ):
            if value is not None:
                sql.append(f"AND memories.{field} = ?")
                params.append(value)
        sql.append("ORDER BY memories.effective_from DESC LIMIT ?")
        params.append(query.limit)
        cur = self.conn.execute(" ".join(sql), params)
        return [_row_to_record(dict(row)) for row in cur.fetchall()]

    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        if not query.strip():
            return []
        params: list[object] = [
            _fts_query(query),
            scope.user_id, scope.agent_id, scope.app_id, scope.session_id, scope.namespace,
        ]
        source_ref_sql = ""
        if source_ref_filter is not None:
            source_ref_sql = (
                " AND EXISTS ("
                "  SELECT 1 FROM json_each(m.source_refs) j WHERE j.value = ?"
                ")"
            )
            params.append(source_ref_filter)
        params.append(limit)

        sql = f"""
            SELECT m.id, -bm25(memories_fts) AS raw_score
            FROM memories_fts JOIN memories m ON memories_fts.rowid = m.rowid
            WHERE memories_fts MATCH ?
              AND m.status = 'active'
              AND m.user_id IS ? AND m.agent_id IS ? AND m.app_id IS ?
              AND m.session_id IS ? AND m.namespace = ?
              {source_ref_sql}
            ORDER BY raw_score DESC
            LIMIT ?
        """
        rows = self.conn.execute(sql, params).fetchall()
        if not rows:
            return []
        max_score = max(row["raw_score"] for row in rows) or 1.0
        records_by_id = {row["id"]: self.get(row["id"]) for row in rows}
        result: list[ScoredMemoryHit] = []
        for row in rows:
            rec = records_by_id[row["id"]]
            if rec is not None:
                result.append(ScoredMemoryHit(record=rec, score=row["raw_score"] / max_score))
        return result

    def list(
        self,
        scope: MemoryScope,
        status_filter: list[str] | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        effective: list[str] = (
            list(status_filter) if status_filter is not None else ["active", "superseded"]
        )
        placeholders = ",".join("?" * len(effective))
        params: list[object] = [scope.namespace]
        sql = [
            "SELECT * FROM memories WHERE namespace = ?",
            f"AND status IN ({placeholders})",
        ]
        params.extend(effective)
        for field, value in (
            ("user_id", scope.user_id),
            ("agent_id", scope.agent_id),
            ("app_id", scope.app_id),
            ("session_id", scope.session_id),
        ):
            if value is not None:
                sql.append(f"AND {field} = ?")
                params.append(value)
        sql.append("ORDER BY effective_from DESC LIMIT ?")
        params.append(limit)
        cur = self.conn.execute(" ".join(sql), params)
        return [_row_to_record(dict(row)) for row in cur.fetchall()]

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord:
        existing = self.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        merged = dict(existing.metadata)
        merged.update(metadata_patch)
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE memories SET metadata=?, updated_at=? WHERE id=?",
            (json.dumps(merged), now, memory_id),
        )
        self.conn.commit()
        return existing.model_copy(
            update={"metadata": merged, "updated_at": datetime.fromisoformat(now)}
        )

    def soft_delete(self, memory_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        affected = self.conn.execute(
            "UPDATE memories SET status='deleted', updated_at=? WHERE id=?",
            (now, memory_id),
        ).rowcount
        if affected == 0:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self.conn.commit()
