"""Extraction report shapes — single source of truth."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stele.core.memory_record import MemoryKind

LedeSource = Literal["key_fact", "stat", "metadata", "phrase", "summary"]
ClassifierPath = Literal["type_based", "pattern_overlay"]
RejectionReason = Literal["below_threshold", "duplicate", "validation_error"]


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    kind: MemoryKind
    confidence: float
    lede_source: LedeSource
    classifier_path: ClassifierPath
    pattern_match: str | None = None


class AcceptedCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: MemoryCandidate
    stored_id: str


class RejectedCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: MemoryCandidate
    reason: RejectionReason
    duplicate_of: str | None = None
    error_message: str | None = None


class ExtractionStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_count: int
    accepted_count: int
    rejected_count: int


class ExtractionReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: list[MemoryCandidate]
    accepted: list[AcceptedCandidate]
    rejected: list[RejectedCandidate]
    pii_flags: list[str] = Field(default_factory=list)
    source_refs: list[str]
    stats: ExtractionStats
    config_fingerprint: str
