"""Postgres MemoryStore — tsvector search, mirror of SQLite shape."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    KIND_VALUES,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    ScoredMemoryHit,
    memory_text_hash,
)

# Built from the model's Literal so the CHECK and MemoryKind never drift.
_KINDS_SQL = ", ".join(f"'{k}'" for k in KIND_VALUES)

# tsvector over the composed insight (summary/detail/action/text). When the
# tripartite fields are NULL this reduces to to_tsvector(text) modulo
# whitespace, so existing rows index identically to before.
_TSV_EXPR = (
    "to_tsvector('english', "
    "coalesce(summary,'') || ' ' || coalesce(detail,'') || ' ' || "
    "coalesce(action,'') || ' ' || text)"
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  summary TEXT,
  detail  TEXT,
  action  TEXT,
  kind TEXT NOT NULL CHECK (kind IN ({_KINDS_SQL})),
  user_id TEXT, agent_id TEXT, app_id TEXT, session_id TEXT,
  namespace TEXT NOT NULL DEFAULT 'default',
  source_refs JSONB NOT NULL,
  source_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  confirmations INTEGER NOT NULL DEFAULT 1,
  last_confirmed TIMESTAMPTZ,
  last_queried TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'active' CHECK (
    status IN ('active','superseded','retracted','disputed','deleted')
  ),
  supersedes JSONB NOT NULL DEFAULT '[]'::jsonb,
  text_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  effective_from TIMESTAMPTZ NOT NULL,
  effective_until TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
  pii_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  search_tsv TSVECTOR GENERATED ALWAYS AS ({_TSV_EXPR}) STORED
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

-- Idempotent forward-migration for tables created before this feature. Each
-- arm is guarded by an existence check so a table that is ALREADY current
-- runs ZERO DDL: no ALTER, no lock. (ALTER TABLE needs ACCESS EXCLUSIVE; on a
-- busy live store an unconditional ALTER on every initialize() would block.)
DO $do$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'memories' AND column_name = 'confirmations'
  ) THEN
    ALTER TABLE memories ADD COLUMN confirmations  INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE memories ADD COLUMN last_confirmed TIMESTAMPTZ;
    ALTER TABLE memories ADD COLUMN last_queried   TIMESTAMPTZ;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'memories' AND column_name = 'summary'
  ) THEN
    ALTER TABLE memories ADD COLUMN summary TEXT;
    ALTER TABLE memories ADD COLUMN detail  TEXT;
    ALTER TABLE memories ADD COLUMN action  TEXT;
    ALTER TABLE memories DROP COLUMN IF EXISTS search_tsv;
    ALTER TABLE memories
      ADD COLUMN search_tsv TSVECTOR GENERATED ALWAYS AS ({_TSV_EXPR}) STORED;
    CREATE INDEX IF NOT EXISTS idx_memories_search_tsv
      ON memories USING GIN(search_tsv);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'memories_kind_check'
      AND pg_get_constraintdef(oid) LIKE '%tool_gap%'
  ) THEN
    ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_kind_check;
    ALTER TABLE memories ADD CONSTRAINT memories_kind_check
      CHECK (kind IN ({_KINDS_SQL}));
  END IF;
END
$do$;
"""


def _temporal_sql(
    as_of: datetime, *, include_superseded: bool
) -> tuple[str, list[object]]:
    """Scope-independent temporal predicate shared by ``search`` and
    ``search_with_score`` so the status/effective_until interplay — the
    exact BUG-1 re-divergence locus — has ONE definition. Reproduces this
    backend's existing ``search`` semantics (the ``effective_until`` bound
    always applies here, unlike the SQLite backend)."""
    parts = [
        "AND effective_from <= %s",
        "AND (effective_until IS NULL OR effective_until > %s)",
    ]
    params: list[object] = [as_of, as_of]
    if not include_superseded:
        parts.append(
            "AND (status = 'active'"
            " OR (status = 'superseded' AND effective_until > %s))"
        )
        params.append(as_of)
    else:
        parts.append("AND status != 'deleted'")
    return " ".join(parts), params


_INSERT_SQL = (
    "INSERT INTO memories ("
    "id, text, summary, detail, action, kind,"
    "user_id, agent_id, app_id, session_id, namespace,"
    "source_refs, source_chunk_ids, confidence, confirmations,"
    "last_confirmed, last_queried, status, supersedes,"
    "text_hash, created_at, updated_at, effective_from, effective_until,"
    "metadata, pii_flags"
    ") VALUES ("
    "%s, %s, %s, %s, %s, %s,"
    "%s, %s, %s, %s, %s,"
    "%s::jsonb, %s::jsonb, %s, %s,"
    "%s, %s, %s, %s::jsonb,"
    "%s, %s, %s, %s, %s,"
    "%s::jsonb, %s::jsonb)"
)


def _insert_params(record: MemoryRecord) -> tuple[object, ...]:
    return (
        record.id, record.text, record.summary, record.detail, record.action,
        record.kind,
        record.scope.user_id, record.scope.agent_id,
        record.scope.app_id, record.scope.session_id, record.scope.namespace,
        json.dumps(record.source_refs),
        json.dumps(record.source_chunk_ids),
        record.confidence, record.confirmations,
        record.last_confirmed, record.last_queried,
        record.status, json.dumps(record.supersedes),
        memory_text_hash(record.text, record.scope),
        record.created_at, record.updated_at,
        record.effective_from, record.effective_until,
        json.dumps(record.metadata),
        json.dumps(record.pii_flags),
    )


def _to_record(row: dict[str, object]) -> MemoryRecord:
    return MemoryRecord(
        id=str(row["id"]),
        text=str(row["text"]),
        summary=row["summary"],  # type: ignore[arg-type]
        detail=row["detail"],  # type: ignore[arg-type]
        action=row["action"],  # type: ignore[arg-type]
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
        confirmations=int(row["confirmations"]),  # type: ignore[call-overload]
        last_confirmed=row["last_confirmed"],  # type: ignore[arg-type]
        last_queried=row["last_queried"],  # type: ignore[arg-type]
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
                cur.execute(_INSERT_SQL, _insert_params(record))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return record, list(supersedes)

    def add_many(
        self,
        items: list[tuple[MemoryRecord, list[str]]],
    ) -> list[tuple[MemoryRecord, list[str]]]:
        if not items:
            return []
        now = datetime.now(UTC)
        try:
            with self.conn.cursor() as cur:
                # Supersedes: per-id UPDATE; rowcount must be verified per row.
                # We can't use executemany for these because we need to detect
                # missing IDs individually.
                for _, sups in items:
                    for old_id in sups:
                        affected = cur.execute(
                            "UPDATE memories SET status='superseded', "
                            "effective_until=%s, updated_at=%s WHERE id=%s",
                            (now, now, old_id),
                        ).rowcount
                        if affected == 0:
                            raise ArtifactNotFound(f"memory not found: {old_id}")
                rows = [_insert_params(r) for r, _ in items]
                cur.executemany(_INSERT_SQL, rows)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return [(r, list(s)) for r, s in items]

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM memories WHERE id=%s", (memory_id,))
            row = cur.fetchone()
        return _to_record(row) if row else None

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        as_of = query.as_of or datetime.now(UTC)
        temporal_sql, temporal_params = _temporal_sql(
            as_of, include_superseded=query.include_superseded
        )
        sql = [
            "SELECT * FROM memories",
            "WHERE search_tsv @@ plainto_tsquery('english', %s)",
            temporal_sql,
            "AND namespace = %s",
        ]
        params: list[object] = [query.query, *temporal_params, query.scope.namespace]
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
        # Newest-valid view (as_of = now, include_superseded = False) via
        # the shared predicate so this never diverges from search(). BUG-1.
        as_of = datetime.now(UTC)
        temporal_sql, temporal_params = _temporal_sql(
            as_of, include_superseded=False
        )
        sql_parts = [
            "SELECT id, ts_rank_cd(search_tsv, plainto_tsquery('english', %s)) AS raw_score",
            "FROM memories",
            "WHERE search_tsv @@ plainto_tsquery('english', %s)",
            f"  {temporal_sql}",
            "  AND namespace = %s",
        ]
        params: list[object] = [
            query, query, *temporal_params, scope.namespace,
        ]
        for field, value in (
            ("user_id", scope.user_id),
            ("agent_id", scope.agent_id),
            ("app_id", scope.app_id),
            ("session_id", scope.session_id),
        ):
            if value is not None:
                sql_parts.append(f"  AND {field} = %s")
                params.append(value)
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
        # Stamp last_queried on the rows recall surfaced. Batched and applied
        # after ranking so it never perturbs scores. BUG-1 candidate set is
        # already fixed; this is a pure evidence side-effect.
        ids = [row["id"] for row in rows]
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET last_queried = %s WHERE id = ANY(%s)",
                (datetime.now(UTC), ids),
            )
        self.conn.commit()
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
        *,
        as_of: datetime | None = None,
    ) -> list[MemoryRecord]:
        sql = ["SELECT * FROM memories WHERE namespace=%s"]
        params: list[object] = [scope.namespace]
        if as_of is None:
            effective: list[str] = (
                list(status_filter) if status_filter is not None else ["active", "superseded"]
            )
            sql.append("AND status = ANY(%s)")
            params.append(effective)
        else:
            # Time-travel view (issue #3): records VALID at as_of regardless
            # of current status, with the optional status_filter composed.
            sql.append("AND effective_from <= %s")
            params.append(as_of)
            sql.append("AND (effective_until IS NULL OR effective_until > %s)")
            params.append(as_of)
            sql.append("AND status != 'deleted'")
            if status_filter is not None:
                sql.append("AND status = ANY(%s)")
                params.append(list(status_filter))
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

    def purge_superseded(self, before: datetime) -> int:
        # Predicate: status='superseded' AND effective_until < before.
        with self.conn.cursor() as cur:
            affected = cur.execute(
                "DELETE FROM memories WHERE status='superseded' "
                "AND effective_until IS NOT NULL AND effective_until < %s",
                (before,),
            ).rowcount
        self.conn.commit()
        return int(affected)

    def delete_namespace(self, namespace: str) -> int:
        with self.conn.cursor() as cur:
            affected = cur.execute(
                "DELETE FROM memories WHERE namespace = %s", (namespace,)
            ).rowcount
        self.conn.commit()
        return int(affected)

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

    def confirm(
        self,
        memory_id: str,
        *,
        at: datetime,
        new_confidence: float | None = None,
    ) -> MemoryRecord:
        floor = new_confidence if new_confidence is not None else 0.0
        with self.conn.cursor() as cur:
            affected = cur.execute(
                "UPDATE memories SET confirmations = confirmations + 1, "
                "last_confirmed = %s, updated_at = %s, "
                "confidence = LEAST(1.0, GREATEST(confidence, %s)) "
                "WHERE id = %s",
                (at, at, floor, memory_id),
            ).rowcount
            if affected == 0:
                raise ArtifactNotFound(f"memory not found: {memory_id}")
        self.conn.commit()
        updated = self.get(memory_id)
        assert updated is not None
        return updated

    def close(self) -> None:
        self.conn.close()
