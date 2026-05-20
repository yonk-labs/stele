"""MariaDB exact artifact storage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from stele.core.artifact import Artifact, ArtifactRecord, CleanupResult, Page
from stele.core.capabilities import StorageCapabilities
from stele.core.exceptions import (
    ArtifactNotFound,
    BackendError,
    OptionalDependencyError,
)
from stele.core.reference import Reference

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ModuleNotFoundError:  # pragma: no cover - exercised without mariadb extra
    pymysql = None
    DictCursor = None


class MariaDBStorageBackend:
    def __init__(self, dsn: str, *, table: str = "artifacts") -> None:
        if pymysql is None or DictCursor is None:
            raise OptionalDependencyError("MariaDB backend requires the 'mariadb' extra")
        self.dsn = dsn
        self.table = _safe_identifier(table)
        self.conn = pymysql.connect(
            **_parse_mysql_dsn(dsn),
            cursorclass=DictCursor,
            autocommit=True,
            charset="utf8mb4",
        )

    def initialize(self) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{self.table}` (
                  artifact_id VARCHAR(64) PRIMARY KEY,
                  reference VARCHAR(512) NOT NULL UNIQUE,
                  namespace VARCHAR(255) NOT NULL,
                  session_id VARCHAR(255) NULL,
                  content LONGBLOB NOT NULL,
                  search_text LONGTEXT NOT NULL,
                  content_encoding VARCHAR(32) NOT NULL,
                  content_type VARCHAR(64) NOT NULL,
                  metadata_json JSON NOT NULL,
                  summary LONGTEXT NOT NULL,
                  raw_summary LONGTEXT NULL,
                  digest_sha256 VARCHAR(64) NOT NULL,
                  byte_size BIGINT NOT NULL,
                  token_estimate BIGINT NOT NULL,
                  lifecycle VARCHAR(32) NOT NULL,
                  expires_at DATETIME(6) NULL,
                  created_at DATETIME(6) NOT NULL,
                  updated_at DATETIME(6) NOT NULL,
                  INDEX idx_artifacts_namespace(namespace),
                  INDEX idx_artifacts_session(session_id),
                  INDEX idx_artifacts_expires(expires_at),
                  FULLTEXT INDEX idx_artifacts_text(search_text, summary)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

    def store(self, artifact: Artifact) -> ArtifactRecord:
        content = (
            artifact.content
            if isinstance(artifact.content, bytes)
            else artifact.content.encode("utf-8")
        )
        with self.conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO `{self.table}` (
                  artifact_id, reference, namespace, session_id, content, search_text,
                  content_encoding, content_type, metadata_json, summary, raw_summary,
                  digest_sha256, byte_size, token_estimate, lifecycle, expires_at,
                  created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  reference = VALUES(reference),
                  namespace = VALUES(namespace),
                  session_id = VALUES(session_id),
                  content = VALUES(content),
                  search_text = VALUES(search_text),
                  content_encoding = VALUES(content_encoding),
                  content_type = VALUES(content_type),
                  metadata_json = VALUES(metadata_json),
                  summary = VALUES(summary),
                  raw_summary = VALUES(raw_summary),
                  digest_sha256 = VALUES(digest_sha256),
                  byte_size = VALUES(byte_size),
                  token_estimate = VALUES(token_estimate),
                  lifecycle = VALUES(lifecycle),
                  expires_at = VALUES(expires_at),
                  updated_at = VALUES(updated_at)
                """,
                (
                    artifact.artifact_id,
                    artifact.reference,
                    artifact.namespace,
                    artifact.session_id,
                    content,
                    artifact.content_as_text(),
                    artifact.content_encoding,
                    artifact.content_type,
                    json.dumps(artifact.metadata),
                    artifact.summary,
                    artifact.raw_summary,
                    artifact.digest_sha256,
                    artifact.byte_size,
                    artifact.token_estimate,
                    artifact.lifecycle,
                    artifact.expires_at,
                    artifact.created_at,
                    artifact.updated_at,
                ),
            )
        return ArtifactRecord.model_validate(artifact.model_dump())

    def store_many(self, artifacts: list[Artifact]) -> list[ArtifactRecord]:
        if not artifacts:
            return []
        rows = []
        for a in artifacts:
            content = a.content if isinstance(a.content, bytes) else a.content.encode("utf-8")
            rows.append((
                a.artifact_id, a.reference, a.namespace, a.session_id,
                content, a.content_as_text(),
                a.content_encoding, a.content_type,
                json.dumps(a.metadata),
                a.summary, a.raw_summary,
                a.digest_sha256, a.byte_size, a.token_estimate,
                a.lifecycle, a.expires_at, a.created_at, a.updated_at,
            ))
        with self.conn.cursor() as cursor:
            cursor.executemany(
                f"""
                INSERT INTO `{self.table}` (
                  artifact_id, reference, namespace, session_id, content, search_text,
                  content_encoding, content_type, metadata_json, summary, raw_summary,
                  digest_sha256, byte_size, token_estimate, lifecycle, expires_at,
                  created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  reference = VALUES(reference),
                  namespace = VALUES(namespace),
                  session_id = VALUES(session_id),
                  content = VALUES(content),
                  search_text = VALUES(search_text),
                  content_encoding = VALUES(content_encoding),
                  content_type = VALUES(content_type),
                  metadata_json = VALUES(metadata_json),
                  summary = VALUES(summary),
                  raw_summary = VALUES(raw_summary),
                  digest_sha256 = VALUES(digest_sha256),
                  byte_size = VALUES(byte_size),
                  token_estimate = VALUES(token_estimate),
                  lifecycle = VALUES(lifecycle),
                  expires_at = VALUES(expires_at),
                  updated_at = VALUES(updated_at)
                """,
                rows,
            )
        return [ArtifactRecord.model_validate(a.model_dump()) for a in artifacts]

    def fetch(self, reference: Reference) -> ArtifactRecord:
        record = self.try_fetch(reference)
        if record is None:
            raise ArtifactNotFound(f"Artifact not found: {reference.canonical}")
        return record

    def try_fetch(self, reference: Reference) -> ArtifactRecord | None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM `{self.table}` WHERE reference = %s LIMIT 1",
                (reference.canonical_without_params,),
            )
            row = cursor.fetchone()
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
        params: list[Any] = []
        if namespace is not None:
            clauses.append("namespace = %s")
            params.append(namespace)
        if session_id is not None:
            clauses.append("session_id = %s")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.conn.cursor() as db_cursor:
            db_cursor.execute(
                f"SELECT * FROM `{self.table}` {where} ORDER BY created_at LIMIT %s",
                (*params, limit),
            )
            rows = db_cursor.fetchall()
        return Page[ArtifactRecord](items=[_row_to_record(row) for row in rows], next_cursor=None)

    def delete(self, reference: Reference) -> bool:
        record = self.try_fetch(reference)
        if record is None:
            return False
        with self.conn.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM `{self.table}` WHERE artifact_id = %s",
                (record.artifact_id,),
            )
            return bool(cursor.rowcount)

    def delete_namespace(self, namespace: str) -> int:
        with self.conn.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM `{self.table}` WHERE namespace = %s",
                (namespace,),
            )
            return int(cursor.rowcount or 0)

    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult:
        with self.conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT artifact_id FROM `{self.table}`
                WHERE expires_at IS NOT NULL AND expires_at <= UTC_TIMESTAMP(6)
                LIMIT %s
                """,
                (limit,),
            )
            ids = [row["artifact_id"] for row in cursor.fetchall()]
            for artifact_id in ids:
                cursor.execute(f"DELETE FROM `{self.table}` WHERE artifact_id = %s", (artifact_id,))
        return CleanupResult(deleted_count=len(ids))

    def capabilities(self) -> StorageCapabilities:
        return StorageCapabilities(backend_type="mariadb", durable=True)

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
    if isinstance(metadata, (bytes, bytearray)):
        metadata = metadata.decode("utf-8")
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


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mariadb"}:
        raise BackendError("MariaDB DSN must use mysql:// or mariadb://")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/") or None,
        "connect_timeout": int(query.get("connect_timeout", ["10"])[0]),
    }


def _safe_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise BackendError(f"Unsafe SQL identifier: {value!r}")
    return value


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise BackendError(f"Invalid datetime stored in MariaDB: {value}") from exc
    raise BackendError(f"Invalid datetime stored in MariaDB: {value!r}")
