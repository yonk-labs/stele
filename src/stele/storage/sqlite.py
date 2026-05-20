"""SQLite exact artifact storage."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stele.core.artifact import Artifact, ArtifactRecord, CleanupResult, Page
from stele.core.capabilities import StorageCapabilities
from stele.core.exceptions import ArtifactNotFound, BackendError
from stele.core.reference import Reference


class SQLiteStorageBackend:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
              artifact_id TEXT PRIMARY KEY,
              reference TEXT NOT NULL UNIQUE,
              namespace TEXT NOT NULL,
              session_id TEXT,
              content BLOB NOT NULL,
              content_encoding TEXT NOT NULL,
              content_type TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              summary TEXT NOT NULL,
              raw_summary TEXT,
              digest_sha256 TEXT NOT NULL,
              byte_size INTEGER NOT NULL,
              token_estimate INTEGER NOT NULL,
              lifecycle TEXT NOT NULL,
              expires_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_namespace ON artifacts(namespace);
            CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_expires ON artifacts(expires_at);
            CREATE VIRTUAL TABLE IF NOT EXISTS artifact_fts
            USING fts5(artifact_id UNINDEXED, namespace UNINDEXED, reference UNINDEXED, content);
            """
        )
        self.conn.commit()

    def store(self, artifact: Artifact) -> ArtifactRecord:
        content = (
            artifact.content
            if isinstance(artifact.content, bytes)
            else artifact.content.encode("utf-8")
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO artifacts (
                  artifact_id, reference, namespace, session_id, content,
                  content_encoding, content_type, metadata_json, summary, raw_summary,
                  digest_sha256, byte_size, token_estimate, lifecycle, expires_at,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.reference,
                    artifact.namespace,
                    artifact.session_id,
                    content,
                    artifact.content_encoding,
                    artifact.content_type,
                    json.dumps(artifact.metadata),
                    artifact.summary,
                    artifact.raw_summary,
                    artifact.digest_sha256,
                    artifact.byte_size,
                    artifact.token_estimate,
                    artifact.lifecycle,
                    _dt_to_str(artifact.expires_at),
                    _dt_to_str(artifact.created_at),
                    _dt_to_str(artifact.updated_at),
                ),
            )
            self.conn.execute(
                "DELETE FROM artifact_fts WHERE artifact_id = ?",
                (artifact.artifact_id,),
            )
            self.conn.execute(
                """
                INSERT INTO artifact_fts(artifact_id, namespace, reference, content)
                VALUES (?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.namespace,
                    artifact.reference,
                    artifact.content_as_text(),
                ),
            )
        return ArtifactRecord.model_validate(artifact.model_dump())

    def store_many(self, artifacts: list[Artifact]) -> list[ArtifactRecord]:
        if not artifacts:
            return []
        rows = []
        fts_rows = []
        ids: list[str] = []
        for a in artifacts:
            content = a.content if isinstance(a.content, bytes) else a.content.encode("utf-8")
            rows.append((
                a.artifact_id, a.reference, a.namespace, a.session_id, content,
                a.content_encoding, a.content_type, json.dumps(a.metadata),
                a.summary, a.raw_summary, a.digest_sha256, a.byte_size,
                a.token_estimate, a.lifecycle,
                _dt_to_str(a.expires_at), _dt_to_str(a.created_at), _dt_to_str(a.updated_at),
            ))
            fts_rows.append((a.artifact_id, a.namespace, a.reference, a.content_as_text()))
            ids.append(a.artifact_id)
        with self.conn:
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO artifacts (
                  artifact_id, reference, namespace, session_id, content,
                  content_encoding, content_type, metadata_json, summary, raw_summary,
                  digest_sha256, byte_size, token_estimate, lifecycle, expires_at,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            # FTS upsert: clear-then-insert keeps the same OR-REPLACE semantics.
            self.conn.executemany(
                "DELETE FROM artifact_fts WHERE artifact_id = ?",
                [(aid,) for aid in ids],
            )
            self.conn.executemany(
                "INSERT INTO artifact_fts(artifact_id, namespace, reference, content) "
                "VALUES (?, ?, ?, ?)",
                fts_rows,
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
            WHERE reference = ?
            LIMIT 1
            """,
            (reference.canonical_without_params,),
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
        params: list[Any] = []
        if namespace is not None:
            clauses.append("namespace = ?")
            params.append(namespace)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM artifacts {where} ORDER BY created_at LIMIT ?",
            (*params, limit),
        ).fetchall()
        return Page[ArtifactRecord](items=[_row_to_record(row) for row in rows], next_cursor=None)

    def delete(self, reference: Reference) -> bool:
        record = self.try_fetch(reference)
        if record is None:
            return False
        with self.conn:
            self.conn.execute(
                "DELETE FROM artifact_fts WHERE artifact_id = ?",
                (record.artifact_id,),
            )
            self.conn.execute("DELETE FROM artifacts WHERE artifact_id = ?", (record.artifact_id,))
        return True

    def delete_namespace(self, namespace: str) -> int:
        with self.conn:
            self.conn.execute(
                "DELETE FROM artifact_fts WHERE namespace = ?", (namespace,)
            )
            cur = self.conn.execute(
                "DELETE FROM artifacts WHERE namespace = ?", (namespace,)
            )
        return int(cur.rowcount or 0)

    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult:
        now = datetime.now(UTC).isoformat()
        rows = self.conn.execute(
            """
            SELECT artifact_id FROM artifacts
            WHERE expires_at IS NOT NULL AND expires_at <= ?
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
        ids = [str(row["artifact_id"]) for row in rows]
        with self.conn:
            for artifact_id in ids:
                self.conn.execute("DELETE FROM artifact_fts WHERE artifact_id = ?", (artifact_id,))
                self.conn.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        return CleanupResult(deleted_count=len(ids))

    def capabilities(self) -> StorageCapabilities:
        return StorageCapabilities(backend_type="sqlite", durable=True)

    def close(self) -> None:
        self.conn.close()


def _row_to_record(row: sqlite3.Row) -> ArtifactRecord:
    content_blob = bytes(row["content"])
    content = (
        content_blob
        if row["content_encoding"] == "bytes"
        else content_blob.decode("utf-8", errors="replace")
    )
    return ArtifactRecord(
        artifact_id=row["artifact_id"],
        reference=row["reference"],
        namespace=row["namespace"],
        session_id=row["session_id"],
        content=content,
        content_encoding=row["content_encoding"],
        content_type=row["content_type"],
        metadata=json.loads(row["metadata_json"]),
        summary=row["summary"],
        raw_summary=row["raw_summary"],
        digest_sha256=row["digest_sha256"],
        byte_size=row["byte_size"],
        token_estimate=row["token_estimate"],
        lifecycle=row["lifecycle"],
        expires_at=_str_to_dt(row["expires_at"]),
        created_at=_str_to_dt(row["created_at"]) or datetime.now(UTC),
        updated_at=_str_to_dt(row["updated_at"]) or datetime.now(UTC),
    )


def _dt_to_str(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _str_to_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise BackendError(f"Invalid datetime stored in SQLite: {value}") from exc
