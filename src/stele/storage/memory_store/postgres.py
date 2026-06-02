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
from stele.storage.memory_store._embedder import MemoryEmbedder, vec_literal

# RRF constant for fusing the keyword and vector legs (matches the chunk side).
_RRF_K = 60

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


# Same as _INSERT_SQL but with the embedding column appended (used when the
# store is configured with an embedder). Derived from _INSERT_SQL so the two
# can't drift.
_INSERT_SQL_VEC = (
    _INSERT_SQL.replace(") VALUES (", ", embedding) VALUES (")[:-1] + ", %s::vector)"
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
    def __init__(self, dsn: str, *, embedder: MemoryEmbedder | None = None) -> None:
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
        # When an embedder is wired (retrieval.memory_vector), the store grows a
        # pgvector column and search_with_score blends a semantic leg. Off ->
        # byte-identical to the keyword-only path.
        self._embedder = embedder
        self._insert_sql = _INSERT_SQL_VEC if embedder is not None else _INSERT_SQL

    def initialize(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(_SCHEMA)
            if self._embedder is not None:
                # pgvector column + HNSW, added lazily (only for vector-enabled
                # stores) and guarded so a current table runs zero DDL / no lock.
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    f"""
                    DO $do$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'memories' AND column_name = 'embedding'
                      ) THEN
                        ALTER TABLE memories ADD COLUMN embedding vector({self._embedder.dim});
                        CREATE INDEX IF NOT EXISTS idx_memories_embedding
                          ON memories USING hnsw (embedding vector_cosine_ops);
                      END IF;
                    END
                    $do$;
                    """
                )
        self.conn.commit()

    def _row_params(self, record: MemoryRecord) -> tuple[object, ...]:
        """Insert params, with the embedding of ``indexable_text`` appended
        when the store is vector-enabled."""
        params = _insert_params(record)
        if self._embedder is not None:
            return (*params, vec_literal(self._embedder.embed(record.indexable_text)))
        return params

    def _records_by_ids(self, ids: list[str]) -> dict[str, MemoryRecord]:
        """Batched fetch (one round-trip) for a set of ids, replacing the
        per-hit get() N+1 in the scored-search paths."""
        if not ids:
            return {}
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM memories WHERE id = ANY(%s)", (ids,))
            rows = cur.fetchall()
        return {str(r["id"]): _to_record(r) for r in rows}

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
                cur.execute(self._insert_sql, self._row_params(record))
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
                rows = [self._row_params(r) for r, _ in items]
                cur.executemany(self._insert_sql, rows)
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
        if self._embedder is not None:
            # Vector-enabled store: blend a semantic leg via RRF. Falls back to
            # this keyword body for any store without an embedder.
            return self._search_hybrid(
                query, scope, limit=limit, source_ref_filter=source_ref_filter
            )
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
        return self._finalize_hits(rows)

    def _finalize_hits(
        self, rows: list[dict[str, object]]
    ) -> list[ScoredMemoryHit]:
        """Shared tail for both scored-search paths: stamp last_queried
        (batched, after ranking, never perturbs scores), normalize the raw
        score into [0, 1], and hydrate records in ONE round-trip (no N+1)."""
        if not rows:
            return []
        ids = [str(row["id"]) for row in rows]
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET last_queried = %s WHERE id = ANY(%s)",
                (datetime.now(UTC), ids),
            )
        self.conn.commit()
        max_score = max(float(row["raw_score"]) for row in rows) or 1.0  # type: ignore[arg-type]
        records = self._records_by_ids(ids)
        result: list[ScoredMemoryHit] = []
        for row in rows:
            rec = records.get(str(row["id"]))
            if rec is not None:
                score = float(row["raw_score"]) / max_score  # type: ignore[arg-type]
                result.append(ScoredMemoryHit(record=rec, score=score))
        return result

    def _search_hybrid(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        """RRF fusion of the tsvector keyword leg and a pgvector semantic leg.
        Same newest-valid scope/temporal predicate as the keyword path (BUG-1),
        applied to BOTH legs. Only reached when an embedder is configured."""
        assert self._embedder is not None
        as_of = datetime.now(UTC)
        qvec = vec_literal(self._embedder.embed(query))
        params: dict[str, object] = {
            "q": query,
            "qvec": qvec,
            "as_of": as_of,
            "ns": scope.namespace,
            "lim": limit,
            "cand": max(limit * 5, 50),
        }
        pred = [
            "AND effective_from <= %(as_of)s",
            "AND (effective_until IS NULL OR effective_until > %(as_of)s)",
            "AND (status = 'active'"
            " OR (status = 'superseded' AND effective_until > %(as_of)s))",
            "AND namespace = %(ns)s",
        ]
        for field, value in (
            ("user_id", scope.user_id),
            ("agent_id", scope.agent_id),
            ("app_id", scope.app_id),
            ("session_id", scope.session_id),
        ):
            if value is not None:
                pred.append(f"AND {field} = %({field})s")
                params[field] = value
        if source_ref_filter is not None:
            pred.append(
                "AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(source_refs) e"
                " WHERE e = %(sref)s)"
            )
            params["sref"] = source_ref_filter
        predicate = "\n          ".join(pred)
        sql = f"""
            WITH kw AS (
              SELECT id, row_number() OVER (
                ORDER BY ts_rank_cd(search_tsv, plainto_tsquery('english', %(q)s)) DESC
              ) AS rk
              FROM memories
              WHERE search_tsv @@ plainto_tsquery('english', %(q)s)
              {predicate}
            ),
            vec AS (
              SELECT id, row_number() OVER (
                ORDER BY embedding <=> %(qvec)s::vector
              ) AS rk
              FROM memories
              WHERE embedding IS NOT NULL
              {predicate}
              ORDER BY embedding <=> %(qvec)s::vector
              LIMIT %(cand)s
            )
            SELECT COALESCE(kw.id, vec.id) AS id,
                   COALESCE(1.0 / ({_RRF_K} + kw.rk), 0)
                 + COALESCE(1.0 / ({_RRF_K} + vec.rk), 0) AS raw_score
            FROM kw FULL OUTER JOIN vec ON kw.id = vec.id
            ORDER BY raw_score DESC
            LIMIT %(lim)s
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return self._finalize_hits(rows)

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
