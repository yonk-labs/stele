"""Postgres MemoryStore — tsvector search, mirror of SQLite shape."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    ScoredMemoryHit,
    memory_text_hash,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (
    kind IN ('fact','preference','decision','instruction','commitment','issue','summary')
  ),
  user_id TEXT, agent_id TEXT, app_id TEXT, session_id TEXT,
  namespace TEXT NOT NULL DEFAULT 'default',
  source_refs JSONB NOT NULL,
  source_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  status TEXT NOT NULL DEFAULT 'active' CHECK (
    status IN ('active','superseded','retracted','disputed','deleted')
  ),
  supersedes JSONB NOT NULL DEFAULT '[]'::jsonb,
  text_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  effective_from TIMESTAMPTZ NOT NULL,
  effective_until TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  pii_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  search_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

CREATE INDEX IF NOT EXISTS idx_memories_scope
  ON memories(namespace, user_id, agent_id, app_id, session_id);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_effective
  ON memories(effective_from, effective_until);
CREATE INDEX IF NOT EXISTS idx_memories_text_hash
  ON memories(text_hash, namespace, user_id);
CREATE INDEX IF NOT EXISTS idx_memories_search_tsv
  ON memories USING GIN(search_tsv);
"""


def _to_record(row: dict[str, object]) -> MemoryRecord:
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
        source_refs=row["source_refs"],  # type: ignore[arg-type]
        source_chunk_ids=row["source_chunk_ids"],  # type: ignore[arg-type]
        confidence=float(row["confidence"]),  # type: ignore[arg-type]
        status=str(row["status"]),  # type: ignore[arg-type]
        supersedes=row["supersedes"],  # type: ignore[arg-type]
        created_at=row["created_at"],  # type: ignore[arg-type]
        updated_at=row["updated_at"],  # type: ignore[arg-type]
        effective_from=row["effective_from"],  # type: ignore[arg-type]
        effective_until=row["effective_until"],  # type: ignore[arg-type]
        metadata=row["metadata"],  # type: ignore[arg-type]
        pii_flags=row["pii_flags"],  # type: ignore[arg-type]
    )


class PostgresMemoryStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)

    def initialize(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(_SCHEMA)
        self.conn.commit()

    def add(
        self,
        record: MemoryRecord,
        supersedes: list[str],
    ) -> tuple[MemoryRecord, list[str]]:
        now = datetime.now(UTC)
        try:
            with self.conn.cursor() as cur:
                for old_id in supersedes:
                    affected = cur.execute(
                        "UPDATE memories SET status='superseded', "
                        "effective_until=%s, updated_at=%s WHERE id=%s",
                        (now, now, old_id),
                    ).rowcount
                    if affected == 0:
                        raise ArtifactNotFound(f"memory not found: {old_id}")
                cur.execute(
                    "INSERT INTO memories ("
                    "id, text, kind, user_id, agent_id, app_id, session_id, namespace,"
                    "source_refs, source_chunk_ids, confidence, status, supersedes,"
                    "text_hash, created_at, updated_at, effective_from, effective_until,"
                    "metadata, pii_flags"
                    ") VALUES ("
                    "%s, %s, %s, %s, %s, %s, %s, %s,"
                    "%s::jsonb, %s::jsonb, %s, %s, %s::jsonb,"
                    "%s, %s, %s, %s, %s,"
                    "%s::jsonb, %s::jsonb)",
                    (
                        record.id, record.text, record.kind,
                        record.scope.user_id, record.scope.agent_id,
                        record.scope.app_id, record.scope.session_id,
                        record.scope.namespace,
                        json.dumps(record.source_refs),
                        json.dumps(record.source_chunk_ids),
                        record.confidence, record.status,
                        json.dumps(record.supersedes),
                        memory_text_hash(record.text, record.scope),
                        record.created_at, record.updated_at,
                        record.effective_from, record.effective_until,
                        json.dumps(record.metadata),
                        json.dumps(record.pii_flags),
                    ),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return record, list(supersedes)

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM memories WHERE id=%s", (memory_id,))
            row = cur.fetchone()
        return _to_record(row) if row else None

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        as_of = query.as_of or datetime.now(UTC)
        sql = [
            "SELECT * FROM memories",
            "WHERE search_tsv @@ plainto_tsquery('english', %s)",
            "AND effective_from <= %s",
            "AND (effective_until IS NULL OR effective_until > %s)",
            "AND namespace = %s",
        ]
        params: list[object] = [query.query, as_of, as_of, query.scope.namespace]
        if not query.include_superseded:
            # Include records active at as_of: status='active', or superseded
            # after as_of (i.e. was still active at that point in time).
            sql.append(
                "AND (status = 'active'"
                " OR (status = 'superseded' AND effective_until > %s))"
            )
            params.append(as_of)
        else:
            sql.append("AND status != 'deleted'")
        for field, value in (
            ("user_id", query.scope.user_id),
            ("agent_id", query.scope.agent_id),
            ("app_id", query.scope.app_id),
            ("session_id", query.scope.session_id),
        ):
            if value is not None:
                sql.append(f"AND {field} = %s")
                params.append(value)
        sql.append("ORDER BY effective_from DESC LIMIT %s")
        params.append(query.limit)
        with self.conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()
        return [_to_record(r) for r in rows]

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
        sql_parts = [
            "SELECT id, ts_rank_cd(search_tsv, plainto_tsquery('english', %s)) AS raw_score",
            "FROM memories",
            "WHERE search_tsv @@ plainto_tsquery('english', %s)",
            "  AND status = 'active'",
            "  AND user_id IS NOT DISTINCT FROM %s",
            "  AND agent_id IS NOT DISTINCT FROM %s",
            "  AND app_id IS NOT DISTINCT FROM %s",
            "  AND session_id IS NOT DISTINCT FROM %s",
            "  AND namespace = %s",
        ]
        params: list[object] = [
            query, query,
            scope.user_id, scope.agent_id, scope.app_id, scope.session_id, scope.namespace,
        ]
        if source_ref_filter is not None:
            sql_parts.append(
                "  AND EXISTS ("
                "    SELECT 1 FROM jsonb_array_elements_text(source_refs) elem"
                "    WHERE elem = %s"
                "  )"
            )
            params.append(source_ref_filter)
        sql_parts.append("ORDER BY raw_score DESC")
        sql_parts.append("LIMIT %s")
        params.append(limit)
        sql = "\n".join(sql_parts)

        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
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
        sql = ["SELECT * FROM memories WHERE namespace=%s AND status = ANY(%s)"]
        params: list[object] = [scope.namespace, effective]
        for field, value in (
            ("user_id", scope.user_id),
            ("agent_id", scope.agent_id),
            ("app_id", scope.app_id),
            ("session_id", scope.session_id),
        ):
            if value is not None:
                sql.append(f"AND {field} = %s")
                params.append(value)
        sql.append("ORDER BY effective_from DESC LIMIT %s")
        params.append(limit)
        with self.conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()
        return [_to_record(r) for r in rows]

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
        now = datetime.now(UTC)
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET metadata=%s::jsonb, updated_at=%s WHERE id=%s",
                (json.dumps(merged), now, memory_id),
            )
        self.conn.commit()
        return existing.model_copy(update={"metadata": merged, "updated_at": now})

    def soft_delete(self, memory_id: str) -> None:
        now = datetime.now(UTC)
        with self.conn.cursor() as cur:
            affected = cur.execute(
                "UPDATE memories SET status='deleted', updated_at=%s WHERE id=%s",
                (now, memory_id),
            ).rowcount
        if affected == 0:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self.conn.commit()

    def set_retracted(self, memory_id: str, retracted_at: datetime) -> None:
        now = datetime.now(UTC)
        with self.conn.cursor() as cur:
            affected = cur.execute(
                "UPDATE memories SET status='retracted', effective_until=%s, "
                "updated_at=%s WHERE id=%s",
                (retracted_at, now, memory_id),
            ).rowcount
        if affected == 0:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self.conn.commit()

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        sql = [
            "SELECT id FROM memories",
            "WHERE text_hash=%s AND namespace=%s",
            "AND user_id IS NOT DISTINCT FROM %s",
            "AND agent_id IS NOT DISTINCT FROM %s",
            "AND app_id IS NOT DISTINCT FROM %s",
            "AND session_id IS NOT DISTINCT FROM %s",
            "AND status NOT IN ('deleted','superseded')",
            "LIMIT 1",
        ]
        params = (
            text_hash,
            scope.namespace,
            scope.user_id, scope.agent_id, scope.app_id, scope.session_id,
        )
        with self.conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            row = cur.fetchone()
        return str(row["id"]) if row else None

    def close(self) -> None:
        self.conn.close()
