"""Public and internal artifact models."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from stele.core.types import (
    ContentEncoding,
    ContentType,
    IndexStatus,
    Lifecycle,
    RetrievalMode,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def content_to_bytes(content: str | bytes, encoding: ContentEncoding = "utf-8") -> bytes:
    if isinstance(content, bytes):
        return content
    if encoding == "base64":
        return base64.b64decode(content.encode("ascii"))
    return content.encode("utf-8")


def digest_content(content: str | bytes, encoding: ContentEncoding = "utf-8") -> str:
    return hashlib.sha256(content_to_bytes(content, encoding)).hexdigest()


def estimate_tokens(text: str | bytes) -> int:
    if isinstance(text, bytes):
        return max(1, len(text) // 4)
    return max(1, len(text.encode("utf-8")) // 4)


class PIIDetection(BaseModel):
    entity_type: str
    start: int
    end: int
    replacement: str
    confidence: float = 1.0
    detector: str = "regex"


class PIIScrubSummary(BaseModel):
    enabled: bool = True
    scrubbed: bool = False
    detection_count: int = 0
    entity_types: list[str] = Field(default_factory=list)


class ScrubResult(BaseModel):
    text: str
    detections: list[PIIDetection] = Field(default_factory=list)

    @property
    def summary(self) -> PIIScrubSummary:
        entity_types = sorted({d.entity_type for d in self.detections})
        return PIIScrubSummary(
            enabled=True,
            scrubbed=bool(self.detections),
            detection_count=len(self.detections),
            entity_types=entity_types,
        )


class Artifact(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    artifact_id: str
    reference: str
    namespace: str
    session_id: str | None = None
    content: str | bytes
    content_encoding: ContentEncoding = "utf-8"
    content_type: ContentType = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)
    summary: str
    raw_summary: str | None = None
    digest_sha256: str
    byte_size: int
    token_estimate: int
    lifecycle: Lifecycle = "manual"
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def content_as_text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return self.content.decode("utf-8", errors="replace")


class ArtifactRecord(Artifact):
    pass


class StoredResult(BaseModel):
    artifact_id: str
    reference: str
    namespace: str
    session_id: str | None = None
    summary: str
    content_type: ContentType
    byte_size: int
    token_estimate: int
    replacement_char_count: int
    estimated_token_savings: int
    estimated_token_savings_pct: float
    index_status: IndexStatus
    pii: PIIScrubSummary
    created_at: datetime


class FetchResult(BaseModel):
    artifact_id: str
    reference: str
    content: str | bytes
    content_type: ContentType
    raw: bool
    scrubbed: bool
    pii: PIIScrubSummary
    metadata: dict[str, Any]
    digest_sha256: str
    byte_size: int
    created_at: datetime


class SearchHit(BaseModel):
    artifact_id: str
    reference: str
    chunk_id: str | None = None
    text: str
    score: float
    retrieval_mode: RetrievalMode = "keyword"
    scrubbed: bool = True
    pii: PIIScrubSummary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class CleanupResult(BaseModel):
    deleted_count: int


class CleanupReport(BaseModel):
    """Result of the umbrella :meth:`Stele.cleanup` entrypoint.

    ``superseded_memories_purged`` is 0 unless the caller passes an
    explicit retention horizon — the default is a no-op so ``as_of``
    time-travel history is never silently destroyed.
    """

    artifacts_expired: int
    superseded_memories_purged: int


class ImportResult(BaseModel):
    imported_count: int


class ExportResult(BaseModel):
    exported_count: int
    path: str


class PurgeReport(BaseModel):
    """Result of :meth:`Stele.purge_namespace`.

    Counts are per-subsystem. ``artifacts`` and ``memories`` are always
    populated; ``chunks`` is the number of artifact references whose
    chunks were removed from the chunk index (0 when no chunk index is
    configured); ``graph_evidence`` is the document count removed from
    the Revisor projection (0 when no Revisor is active).

    A ``dry_run`` purge returns the same shape but mutates nothing.
    """

    namespace: str
    dry_run: bool
    artifacts: int
    memories: int
    chunks: int = 0
    graph_evidence: int = 0


class StoreRequest(BaseModel):
    """One row in a :meth:`Stele.store_many` batch.

    Mirrors the per-row :meth:`Stele.store` kwargs exactly. ``content``
    is required; everything else has the same default as ``store()``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    content: str | bytes
    namespace: str = "default"
    session_id: str | None = None
    content_type: ContentType | str | None = None
    metadata: dict[str, Any] | None = None
    lifecycle: Lifecycle | str = "manual"
    ttl_seconds: int | None = None


