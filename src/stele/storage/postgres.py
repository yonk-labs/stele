"""Postgres exact artifact storage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from stele.core.artifact import Artifact, ArtifactRecord, CleanupResult, Page
from stele.core.capabilities import StorageCapabilities
from stele.core.exceptions import (
    ArtifactNotFound,
    BackendError,
    OptionalDependencyError,
)
from stele.core.reference import Reference

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ModuleNotFoundError:  # pragma: no cover - exercised without postgres extra
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


class PostgresStorageBackend:
    def __init__(self, dsn: str) -> None:
        if psycopg is None or dict_row is None:
            raise OptionalDependencyError("Postgres backend requires the 'postgres' extra")
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

    def initialize(self) -> None:
        with self.conn.transaction():
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                  artifact_id TEXT PRIMARY KEY,
                  reference TEXT NOT NULL UNIQUE,
                  namespace TEXT NOT NULL,
                  session_id TEXT,
                  content BYTEA NOT NULL,
                  search_text TEXT NOT NULL DEFAULT '',
                  content_encoding TEXT NOT NULL,
                  content_type TEXT NOT NULL,
                  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                  summary TEXT NOT NULL,
                  raw_summary TEXT,
                  digest_sha256 TEXT NOT NULL,
                  byte_size BIGINT NOT NULL,
                  token_estimate BIGINT NOT NULL,
                  lifecycle TEXT NOT NULL,
                  expires_at TIMESTAMPTZ,
                  created_at TIMESTAMPTZ NOT NULL,
                  updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_namespace ON artifacts(namespace)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_expires ON artifacts(expires_at)"
            )
            self.conn.execute("ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS search_text TEXT")
            self.conn.execute("UPDATE artifacts SET search_text = '' WHERE search_text IS NULL")
            self.conn.execute("ALTER TABLE artifacts ALTER COLUMN search_text SET DEFAULT ''")
            self.conn.execute("ALTER TABLE artifacts ALTER COLUMN search_text SET NOT NULL")
            self.conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifacts_fts
                ON artifacts USING GIN (
                  to_tsvector('english', search_text || ' ' || summary)
                )
                """
            )

    def store(self, artifact: Artifact) -> ArtifactRecord:
        content = (
            artifact.content
            if isinstance(artifact.content, bytes)
            else artifact.content.encode("utf-8")
        )
        search_text = artifact.content_as_text()
        metadata = Jsonb(artifact.metadata)
        with self.conn.transaction():
            self.conn.execute(
                """
                INSERT INTO artifacts (
                  artifact_id, reference, namespace, session_id, content,
                  search_text, content_encoding, content_type, metadata_json, summary, raw_summary,
                  digest_sha256, byte_size, token_estimate, lifecycle, expires_at,
                  created_at, updated_at
                )
                VALUES (
                  %(artifact_id)s, %(reference)s, %(namespace)s, %(session_id)s,
                  %(content)s, %(search_text)s, %(content_encoding)s,
                  %(content_type)s, %(metadata_json)s, %(summary)s, %(raw_summary)s,
                  %(digest_sha256)s, %(byte_size)s, %(token_estimate)s, %(lifecycle)s,
                  %(expires_at)s, %(created_at)s, %(updated_at)s
                )
                ON CONFLICT (artifact_id) DO UPDATE SET
                  reference = EXCLUDED.reference,
                  namespace = EXCLUDED.namespace,
                  session_id = EXCLUDED.session_id,
                  content = EXCLUDED.content,
                  search_text = EXCLUDED.search_text,
                  content_encoding = EXCLUDED.content_encoding,
                  content_type = EXCLUDED.content_type,
                  metadata_json = EXCLUDED.metadata_json,
                  summary = EXCLUDED.summary,
                  raw_summary = EXCLUDED.raw_summary,
                  digest_sha256 = EXCLUDED.digest_sha256,
                  byte_size = EXCLUDED.byte_size,
                  token_estimate = EXCLUDED.token_estimate,
                  lifecycle = EXCLUDED.lifecycle,
                  expires_at = EXCLUDED.expires_at,
                  updated_at = EXCLUDED.updated_at
                """,
                {
                    "artifact_id": artifact.artifact_id,
                    "reference": artifact.reference,
                    "namespace": artifact.namespace,
                    "session_id": artifact.session_id,
                    "content": content,
                    "search_text": search_text,
                    "content_encoding": artifact.content_encoding,
                    "content_type": artifact.content_type,
                    "metadata_json": metadata,
                    "summary": artifact.summary,
                    "raw_summary": artifact.raw_summary,
                    "digest_sha256": artifact.digest_sha256,
                    "byte_size": artifact.byte_size,
                    "token_estimate": artifact.token_estimate,
                    "lifecycle": artifact.lifecycle,
                    "expires_at": artifact.expires_at,
                    "created_at": artifact.created_at,
                    "updated_at": artifact.updated_at,
                },
            )
        return ArtifactRecord.model_validate(artifact.model_dump())

    def store_many(self, artifacts: list[Artifact]) -> list[ArtifactRecord]:
        if not artifacts:
            return []
        params: list[dict[str, Any]] = []
        for a in artifacts:
            content = a.content if isinstance(a.content, bytes) else a.content.encode("utf-8")
            params.append({
                "artifact_id": a.artifact_id,
                "reference": a.reference,
                "namespace": a.namespace,
                "session_id": a.session_id,
                "content": content,
                "search_text": a.content_as_text(),
                "content_encoding": a.content_encoding,
                "content_type": a.content_type,
                "metadata_json": Jsonb(a.metadata),
                "summary": a.summary,
                "raw_summary": a.raw_summary,
                "digest_sha256": a.digest_sha256,
                "byte_size": a.byte_size,
                "token_estimate": a.token_estimate,
                "lifecycle": a.lifecycle,
                "expires_at": a.expires_at,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
            })
        # One transaction, executemany — eliminates N commits and N
        # round-trips. UPSERT semantics preserved by reusing store()'s
        # ON CONFLICT clause.
        with self.conn.transaction():
            self.conn.cursor().executemany(
                """
                INSERT INTO artifacts (
                  artifact_id, reference, namespace, session_id, content,
                  search_text, content_encoding, content_type, metadata_json,
                  summary, raw_summary, digest_sha256, byte_size, token_estimate,
                  lifecycle, expires_at, created_at, updated_at
                )
                VALUES (
                  %(artifact_id)s, %(reference)s, %(namespace)s, %(session_id)s,
                  %(content)s, %(search_text)s, %(content_encoding)s,
                  %(content_type)s, %(metadata_json)s, %(summary)s, %(raw_summary)s,
                  %(digest_sha256)s, %(byte_size)s, %(token_estimate)s, %(lifecycle)s,
                  %(expires_at)s, %(created_at)s, %(updated_at)s
                )
                ON CONFLICT (artifact_id) DO UPDATE SET
                  reference = EXCLUDED.reference,
                  namespace = EXCLUDED.namespace,
                  session_id = EXCLUDED.session_id,
                  content = EXCLUDED.content,
                  search_text = EXCLUDED.search_text,
                  content_encoding = EXCLUDED.content_encoding,
                  content_type = EXCLUDED.content_type,
                  metadata_json = EXCLUDED.metadata_json,
                  summary = EXCLUDED.summary,
                  raw_summary = EXCLUDED.raw_summary,
                  digest_sha256 = EXCLUDED.digest_sha256,
                  byte_size = EXCLUDED.byte_size,
                  token_estimate = EXCLUDED.token_estimate,
                  lifecycle = EXCLUDED.lifecycle,
                  expires_at = EXCLUDED.expires_at,
                  updated_at = EXCLUDED.updated_at
                """,
                params,
            )
        return [ArtifactRecord.model_validate(a.model_dump()) for a in artifacts]

    def fetch(self, reference: Reference) -> ArtifactRecord:
        record = self.try_fetch(reference)
        if record is None:
            raise ArtifactNotFound(f"Artifact not found: {reference.canonical}")
        return record

    def try_fetch(self, reference: Reference) -> ArtifactRecord | None:
        row = self.conn.execute(
            """
            SELECT * FROM artifacts
            WHERE reference = %(ref)s
            LIMIT 1
            """,
            {"ref": reference.canonical_without_params},
        ).fetchone()
        return _row_to_record(row) if row else None

    def list(
        self,
        *,
        namespace: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[ArtifactRecord]:
        del cursor
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if namespace is not None:
            clauses.append("namespace = %(namespace)s")
            params["namespace"] = namespace
        if session_id is not None:
            clauses.append("session_id = %(session_id)s")
            params["session_id"] = session_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM artifacts {where} ORDER BY created_at LIMIT %(limit)s",
            params,
        ).fetchall()
        return Page[ArtifactRecord](items=[_row_to_record(row) for row in rows], next_cursor=None)

    def delete(self, reference: Reference) -> bool:
        record = self.try_fetch(reference)
        if record is None:
            return False
        with self.conn.transaction():
            cursor = self.conn.execute(
                "DELETE FROM artifacts WHERE artifact_id = %(artifact_id)s",
                {"artifact_id": record.artifact_id},
            )
        return bool(cursor.rowcount)

    def delete_namespace(self, namespace: str) -> int:
        with self.conn.transaction():
            cursor = self.conn.execute(
                "DELETE FROM artifacts WHERE namespace = %(namespace)s",
                {"namespace": namespace},
            )
        return int(cursor.rowcount or 0)

    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult:
        with self.conn.transaction():
            rows = self.conn.execute(
                """
                WITH doomed AS (
                  SELECT artifact_id FROM artifacts
                  WHERE expires_at IS NOT NULL AND expires_at <= now()
                  LIMIT %(limit)s
                )
                DELETE FROM artifacts
                USING doomed
                WHERE artifacts.artifact_id = doomed.artifact_id
                RETURNING artifacts.artifact_id
                """,
                {"limit": limit},
            ).fetchall()
        return CleanupResult(deleted_count=len(rows))

    def capabilities(self) -> StorageCapabilities:
        return StorageCapabilities(backend_type="postgres", durable=True)

    def close(self) -> None:
        self.conn.close()


def _row_to_record(row: dict[str, Any]) -> ArtifactRecord:
    content_blob = bytes(row["content"])
    content = (
        content_blob
        if row["content_encoding"] == "bytes"
        else content_blob.decode("utf-8", errors="replace")
    )
    metadata = row["metadata_json"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return ArtifactRecord(
        artifact_id=row["artifact_id"],
        reference=row["reference"],
        namespace=row["namespace"],
        session_id=row["session_id"],
        content=content,
        content_encoding=row["content_encoding"],
        content_type=row["content_type"],
        metadata=metadata,
        summary=row["summary"],
        raw_summary=row["raw_summary"],
        digest_sha256=row["digest_sha256"],
        byte_size=row["byte_size"],
        token_estimate=row["token_estimate"],
        lifecycle=row["lifecycle"],
        expires_at=_coerce_dt(row["expires_at"]),
        created_at=_coerce_dt(row["created_at"]) or datetime.now(UTC),
        updated_at=_coerce_dt(row["updated_at"]) or datetime.now(UTC),
    )


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise BackendError(f"Invalid datetime stored in Postgres: {value}") from exc
    raise BackendError(f"Invalid datetime stored in Postgres: {value!r}")
