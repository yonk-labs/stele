"""Tests for extraction models — field validation and defaults."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.extraction.models import (
    AcceptedCandidate,
    ExtractionReport,
    ExtractionStats,
    MemoryCandidate,
    RejectedCandidate,
)


def test_memory_candidate_required_fields() -> None:
    cand = MemoryCandidate(
        text="users prefer dark mode",
        kind="preference",
        confidence=0.85,
        lede_source="key_fact",
        classifier_path="pattern_overlay",
        pattern_match="preference",
    )
    assert cand.text == "users prefer dark mode"
    assert cand.kind == "preference"
    assert cand.confidence == 0.85
    assert cand.lede_source == "key_fact"
    assert cand.classifier_path == "pattern_overlay"
    assert cand.pattern_match == "preference"


def test_memory_candidate_pattern_match_optional() -> None:
    cand = MemoryCandidate(
        text="The capital is Paris.",
        kind="fact",
        confidence=0.7,
        lede_source="key_fact",
        classifier_path="type_based",
    )
    assert cand.pattern_match is None


def test_memory_candidate_rejects_unknown_kind() -> None:
    with pytest.raises(PydanticValidationError):
        MemoryCandidate(
            text="x",
            kind="not_a_kind",  # type: ignore[arg-type]
            confidence=0.5,
            lede_source="key_fact",
            classifier_path="type_based",
        )


def test_accepted_candidate_carries_stored_id() -> None:
    cand = MemoryCandidate(
        text="x",
        kind="fact",
        confidence=0.8,
        lede_source="stat",
        classifier_path="type_based",
    )
    acc = AcceptedCandidate(candidate=cand, stored_id="mem_abc123")
    assert acc.stored_id == "mem_abc123"
    assert acc.candidate.text == "x"


def test_rejected_candidate_with_duplicate_reason() -> None:
    cand = MemoryCandidate(
        text="x",
        kind="fact",
        confidence=0.8,
        lede_source="stat",
        classifier_path="type_based",
    )
    rej = RejectedCandidate(candidate=cand, reason="duplicate", duplicate_of="mem_old")
    assert rej.reason == "duplicate"
    assert rej.duplicate_of == "mem_old"
    assert rej.error_message is None


def test_rejected_candidate_with_validation_error() -> None:
    cand = MemoryCandidate(
        text="x",
        kind="fact",
        confidence=0.8,
        lede_source="stat",
        classifier_path="type_based",
    )
    rej = RejectedCandidate(
        candidate=cand,
        reason="validation_error",
        error_message="some pydantic complaint",
    )
    assert rej.reason == "validation_error"
    assert rej.error_message == "some pydantic complaint"


def test_extraction_stats_defaults_to_zero() -> None:
    stats = ExtractionStats(candidate_count=0, accepted_count=0, rejected_count=0)
    assert stats.candidate_count == 0
    assert stats.accepted_count == 0


def test_extraction_report_empty_run() -> None:
    report = ExtractionReport(
        candidates=[],
        accepted=[],
        rejected=[],
        pii_flags=[],
        source_refs=["stele://default/abc"],
        stats=ExtractionStats(candidate_count=0, accepted_count=0, rejected_count=0),
        config_fingerprint="x" * 64,
    )
    assert report.candidates == []
    assert report.accepted == []
    assert report.source_refs == ["stele://default/abc"]
