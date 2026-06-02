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
    # cq lifecycle kinds (L1->L4). The L4 tool_gap *synthesis* (clustering
    # workarounds into a missing-tool signal) is a consumer concern; stele
    # only needs to store the kinds. See issue #38.
    "pitfall",  # L1: a sharp edge encountered
    "workaround",  # L2: how it was worked around
    "tool_recommendation",  # L3: a tool that addresses it
    "tool_gap",  # L4: synthesized "missing tool" signal
]

# The kind values a DB CHECK constraint must accept. Derived from the Literal
# so the schema and the model can never drift (one source of truth).
KIND_VALUES: tuple[str, ...] = tuple(MemoryKind.__args__)  # type: ignore[attr-defined]

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
    # Tripartite insight (all optional, back-compat preserved). `text` stays
    # the canonical/back-compat assertion; these carry the structured view:
    # what was observed, the supporting detail, and what to DO about it.
    summary: str | None = None
    detail: str | None = None
    action: str | None = None
    kind: MemoryKind
    scope: MemoryScope
    source_refs: list[str]
    source_chunk_ids: list[str] = Field(default_factory=list)
    # `confidence` may EVOLVE on re-observation (it is no longer write-time
    # immutable). The assertion text stays immutable; only this evidence about
    # it moves. See `evolved_confidence` and MemoryStore.confirm.
    confidence: float = 1.0
    # Evidence model: how strongly/recently this assertion is supported.
    confirmations: int = 1  # times re-observed (1 == first write)
    last_confirmed: datetime | None = None  # last re-observation
    last_queried: datetime | None = None  # last time recall surfaced this row
    status: MemoryStatus = "active"
    supersedes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    effective_from: datetime
    effective_until: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    pii_flags: list[str] = Field(default_factory=list)

    @property
    def indexable_text(self) -> str:
        """Text used for FTS/search and dedup-adjacent reads. Falls back to
        `text` when the tripartite fields are absent, so existing rows index
        identically to before this feature."""
        parts = [p for p in (self.summary, self.detail, self.action) if p]
        return "\n".join(parts) if parts else self.text

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
    summary: str | None = None
    detail: str | None = None
    action: str | None = None
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


def evolved_confidence(prior: float, confirmations: int) -> float:
    """Confidence after `confirmations` total observations of an assertion.

    Diminishing returns that never exceed 1.0: one observation leaves it at
    `prior`, repeated confirmation saturates toward 1.0. Pure math kept in
    core so every backend evolves confidence identically."""
    if confirmations <= 1:
        return min(1.0, prior)
    return min(1.0, prior + (1.0 - prior) * (1 - 1 / confirmations))
