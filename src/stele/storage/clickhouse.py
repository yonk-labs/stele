"""ClickHouse exact artifact storage.

ClickHouse is append/analytics oriented, so deletes and TTL cleanup use mutations.
They are requested synchronously from this client, but cluster settings can still
make physical removal asynchronous.
"""

from __future__ import annotations

import base64
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
    import clickhouse_connect
except ModuleNotFoundError:  # pragma: no cover - exercised without clickhouse extra
    clickhouse_connect = None


class ClickHouseStorageBackend:
    def __init__(self, dsn: str, *, database: str | None = None, table: str = "artifacts") -> None:
        if clickhouse_connect is None:
            raise OptionalDependencyError("ClickHouse backend requires the 'clickhouse' extra")
        self.dsn = dsn
        self.database = _safe_identifier(database or _parse_clickhouse_dsn(dsn)["database"])
        self.table = _safe_identifier(table)
        self.client = clickhouse_connect.get_client(**_parse_clickhouse_dsn(dsn))

    @property
    def fq_table(self) -> str:
        return f"`{self.database}`.`{self.table}`"

    def initialize(self) -> None:
        self.client.command(f"CREATE DATABASE IF NOT EXISTS `{self.database}`")
        self.client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {self.fq_table} (
              artifact_id String,
              reference String,
              namespace String,
              session_id Nullable(String),
              content String,
              search_text String,
              content_encoding String,
              content_type String,
              metadata_json String,
              summary String,
              raw_summary Nullable(String),
              digest_sha256 String,
              byte_size UInt64,
              token_estimate UInt64,
              lifecycle String,
              expires_at Nullable(DateTime64(6, 'UTC')),
              created_at DateTime64(6, 'UTC'),
              updated_at DateTime64(6, 'UTC')
            )
            ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (namespace, reference, artifact_id)
            """
        )

    def store(self, artifact: Artifact) -> ArtifactRecord:
        content = _encode_content(artifact.content)
        self.client.insert(
            f"{self.database}.{self.table}",
            [
                [
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
                ]
            ],
            column_names=[
                "artifact_id",
                "reference",
                "namespace",
                "session_id",
                "content",
                "search_text",
                "content_encoding",
                "content_type",
                "metadata_json",
                "summary",
                "raw_summary",
                "digest_sha256",
                "byte_size",
                "token_estimate",
                "lifecycle",
                "expires_at",
                "created_at",
                "updated_at",
            ],
        )
        return ArtifactRecord.model_validate(artifact.model_dump())

    def store_many(self, artifacts: list[Artifact]) -> list[ArtifactRecord]:
        if not artifacts:
            return []
        rows = [
            [
                a.artifact_id, a.reference, a.namespace, a.session_id,
                _encode_content(a.content), a.content_as_text(),
                a.content_encoding, a.content_type, json.dumps(a.metadata),
                a.summary, a.raw_summary, a.digest_sha256, a.byte_size,
                a.token_estimate, a.lifecycle, a.expires_at, a.created_at,
                a.updated_at,
            ]
            for a in artifacts
        ]
        # ClickHouse's client.insert is already batch-shaped — one request,
        # one server-side append, idiomatic for the columnar engine.
        self.client.insert(
            f"{self.database}.{self.table}",
            rows,
            column_names=[
                "artifact_id", "reference", "namespace", "session_id",
                "content", "search_text", "content_encoding", "content_type",
                "metadata_json", "summary", "raw_summary", "digest_sha256",
                "byte_size", "token_estimate", "lifecycle", "expires_at",
                "created_at", "updated_at",
            ],
        )
        return [ArtifactRecord.model_validate(a.model_dump()) for a in artifacts]

    def fetch(self, reference: Reference) -> ArtifactRecord:
        record = self.try_fetch(reference)
        if record is None:
            raise ArtifactNotFound(f"Artifact not found: {reference.canonical}")
        return record

    def try_fetch(self, reference: Reference) -> ArtifactRecord | None:
        rows = list(self.client.query(
            f"""
            SELECT *
            FROM {self.fq_table} FINAL
            WHERE reference = %(reference)s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            parameters={"reference": reference.canonical_without_params},
        ).named_results())
        return _row_to_record(rows[0]) if rows else None

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
        rows = list(self.client.query(
            f"SELECT * FROM {self.fq_table} FINAL {where} ORDER BY created_at LIMIT %(limit)s",
            parameters=params,
        ).named_results())
        return Page[ArtifactRecord](items=[_row_to_record(row) for row in rows], next_cursor=None)

    def delete(self, reference: Reference) -> bool:
        record = self.try_fetch(reference)
        if record is None:
            return False
        self.client.command(
            f"""
            ALTER TABLE {self.fq_table}
            DELETE WHERE artifact_id = %(artifact_id)s
            SETTINGS mutations_sync = 1
            """,
            parameters={"artifact_id": record.artifact_id},
        )
        return True

    def delete_namespace(self, namespace: str) -> int:
        # ClickHouse ALTER ... DELETE returns no rowcount; count first.
        count_row = next(iter(self.client.query(
            f"SELECT count() AS c FROM {self.fq_table} FINAL "
            f"WHERE namespace = %(namespace)s",
            parameters={"namespace": namespace},
        ).named_results()))
        count = int(count_row["c"])
        if count:
            self.client.command(
                f"""
                ALTER TABLE {self.fq_table}
                DELETE WHERE namespace = %(namespace)s
                SETTINGS mutations_sync = 1
                """,
                parameters={"namespace": namespace},
            )
        return count

    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult:
        rows = list(self.client.query(
            f"""
            SELECT artifact_id FROM {self.fq_table} FINAL
            WHERE expires_at IS NOT NULL AND expires_at <= now64(6, 'UTC')
            LIMIT %(limit)s
            """,
            parameters={"limit": limit},
        ).named_results())
        ids = [row["artifact_id"] for row in rows]
        if ids:
            self.client.command(
                f"""
                ALTER TABLE {self.fq_table}
                DELETE WHERE artifact_id IN %(ids)s
                SETTINGS mutations_sync = 1
                """,
                parameters={"ids": ids},
            )
        return CleanupResult(deleted_count=len(ids))

    def capabilities(self) -> StorageCapabilities:
        return StorageCapabilities(
            backend_type="clickhouse",
            durable=True,
            ttl_cleanup=True,
            hard_delete=False,
        )

    def close(self) -> None:
        self.client.close()


def _row_to_record(row: dict[str, Any]) -> ArtifactRecord:
    content = _decode_content(row["content"], row["content_encoding"])
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
        expires_at=_coerce_dt(row["expires_at"]),
        created_at=_coerce_dt(row["created_at"]) or datetime.now(UTC),
        updated_at=_coerce_dt(row["updated_at"]) or datetime.now(UTC),
    )


def _encode_content(content: str | bytes) -> str:
    if isinstance(content, bytes):
        return base64.b64encode(content).decode("ascii")
    return content


def _decode_content(content: str, encoding: str) -> str | bytes:
    if encoding == "bytes":
        return base64.b64decode(content.encode("ascii"))
    return content


def _parse_clickhouse_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"clickhouse", "http", "https"}:
        raise BackendError("ClickHouse DSN must use clickhouse://, http://, or https://")
    query = parse_qs(parsed.query)
    secure = parsed.scheme == "https" or query.get("secure", ["false"])[0].lower() == "true"
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or (8443 if secure else 8123),
        "username": unquote(parsed.username or "default"),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/") or "default",
        "secure": secure,
    }


def _safe_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise BackendError(f"Unsafe ClickHouse identifier: {value!r}")
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
            raise BackendError(f"Invalid datetime stored in ClickHouse: {value}") from exc
    raise BackendError(f"Invalid datetime stored in ClickHouse: {value!r}")
