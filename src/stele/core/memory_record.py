"""Memory record model — the single source of truth for memory shape."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from stele.core.exceptions import ValidationError

MemoryKind = Literal[
    "fact",
    "preference",
    "decision",
    "instruction",
    "commitment",
    "issue",
    "summary",
]

MemoryStatus = Literal[
    "active",
    "superseded",
    "retracted",
    "disputed",
    "deleted",
]


class MemoryScope(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str | None = None
    agent_id: str | None = None
    app_id: str | None = None
    session_id: str | None = None
    namespace: str = "default"


class MemoryRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    text: str
    kind: MemoryKind
    scope: MemoryScope
    source_refs: list[str]
    source_chunk_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    status: MemoryStatus = "active"
    supersedes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    effective_from: datetime
    effective_until: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    pii_flags: list[str] = Field(default_factory=list)

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValidationError(
                "every memory must cite at least one stele:// source_ref"
            )
        for ref in v:
            if not ref.startswith("stele://"):
                raise ValidationError(
                    f"source_refs entries must be stele:// URIs, got {ref!r}"
                )
        return v


class MemoryQuery(BaseModel):
    query: str
    scope: MemoryScope
    as_of: datetime | None = None
    include_superseded: bool = False
    limit: int = 10


class MemoryAddResult(BaseModel):
    record: MemoryRecord
    duplicate_of: str | None = None
    superseded_ids: list[str] = Field(default_factory=list)


class AddRequest(BaseModel):
    """One row in a :meth:`Memory.add_many` batch.

    Mirrors the per-row :meth:`Memory.add` kwargs exactly."""

    text: str
    kind: MemoryKind
    source_refs: list[str]
    scope: MemoryScope
    supersedes: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    metadata: dict[str, object] = Field(default_factory=dict)


class ScoredMemoryHit(BaseModel):
    """A memory record + a normalized retrieval score."""

    model_config = ConfigDict(frozen=True)

    record: MemoryRecord
    score: float


def canonical_scope_key(scope: MemoryScope) -> str:
    """Stable string for scope used in hashing."""
    return json.dumps(scope.model_dump(), sort_keys=True, separators=(",", ":"))


def memory_text_hash(text: str, scope: MemoryScope) -> str:
    """sha256(text || canonical(scope)) for duplicate detection."""
    payload = text.encode("utf-8") + b"|" + canonical_scope_key(scope).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
