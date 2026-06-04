"""Recall report shapes — single source of truth."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stele.core.memory_record import MemoryRecord, MemoryScope

StrategyName = Literal[
    "summary_only",
    "memory_search",
    "artifact_search",
    "graph_search",
    "adaptive",
    "raw_fetch",
    "abstain",
    "digest",
    "episodic",
]

CitationKind = Literal["memory", "artifact", "chunk"]

EscalationReason = Literal[
    "tier_complete",
    "below_floor",
    "zero_hits",
    "sufficient_callback_false",
    "exhausted",
]


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: CitationKind
    id: str
    reference: str
    score: float
    snippet: str


class Escalation(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: StrategyName
    hit_count: int
    top_score: float | None
    reason: EscalationReason


class RecallStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_searches: int = 0
    artifact_searches: int = 0
    chunk_searches: int = 0
    fetches: int = 0
    estimated_context_tokens: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class RecallContext:
    """Snapshot of the in-flight adaptive escalation."""

    query: str
    scope: MemoryScope
    accumulated_citations: list[Citation]
    accumulated_text: str


class RecallRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    query: str
    scope: MemoryScope
    strategy: StrategyName = "adaptive"
    artifact_id: str | None = None
    sufficient: Callable[[RecallContext], bool] | None = None
    max_memory_hits: int = 5
    max_artifact_hits: int = 5
    confidence_floor: float | None = None
    # Phase 5 — optional, defaults preserve every existing caller's behavior.
    as_of: datetime | None = None
    version_filter: str | None = None
    retracted_behavior: Literal["hide", "flag", "surface_both"] | None = None
    supersession_behavior: Literal["hide", "prefer_new", "surface_both"] | None = None
    # Episodic recall (Phase 1) — temporal is a soft boost by default; opt in to
    # a hard window restriction. Default False preserves all existing callers.
    hard_temporal: bool = False


class EpisodeHit(BaseModel):
    """One recalled episode: a past session artifact plus the memories
    back-linked to it. ``when`` is the episode's temporal anchor
    (``metadata.session_mtime`` if present, else the artifact ``created_at``).
    ``score`` is the soft-boosted semantic rank of the session text."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str | None = None
    when: datetime | None = None
    summary: str
    ref: str
    score: float
    memories: list[MemoryRecord] = Field(default_factory=list)


class RecallResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    strategy_used: StrategyName
    context: str
    citations: list[Citation]
    escalations: list[Escalation]
    pii_flags: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    stats: RecallStats
    abstained: bool = False
    abstain_reason: str | None = None
    # Episodic recall (Phase 1): populated only by the episodic strategy;
    # every other strategy leaves it empty so the contract is unchanged.
    episodes: list[EpisodeHit] = Field(default_factory=list)
