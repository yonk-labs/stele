"""Tests for the type-based classifier defaults."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from stele.extraction.classifier import classify_kind


@pytest.mark.parametrize(
    "lede_source,expected_kind,expected_confidence",
    [
        ("key_fact", "fact", 0.7),
        ("stat", "fact", 0.8),
        ("metadata", "fact", 0.7),
        ("phrase", "fact", 0.5),
        ("summary", "summary", 0.9),
    ],
)
def test_type_based_defaults(
    lede_source: str, expected_kind: str, expected_confidence: float
) -> None:
    out = classify_kind(
        text="The capital of France is Paris.",
        lede_source=lede_source,  # type: ignore[arg-type]
        overlay_enabled=False,
    )
    assert out.kind == expected_kind
    assert out.confidence == pytest.approx(expected_confidence)
    assert out.classifier_path == "type_based"
    assert out.pattern_match is None


def test_classifier_output_is_frozen() -> None:
    out = classify_kind(
        text="x",
        lede_source="stat",
        overlay_enabled=False,
    )
    with pytest.raises(FrozenInstanceError):
        out.kind = "preference"  # type: ignore[misc]


def test_overlay_wins_when_pattern_matches_with_higher_weight() -> None:
    out = classify_kind(
        text="I prefer dark mode.",
        lede_source="key_fact",  # default confidence 0.7
        overlay_enabled=True,
    )
    assert out.kind == "preference"
    assert out.confidence == pytest.approx(0.85)
    assert out.classifier_path == "pattern_overlay"
    assert out.pattern_match == "preference"


def test_overlay_loses_when_default_confidence_already_higher() -> None:
    # summary defaults to 0.9; issue weight is only 0.65, so overlay must
    # not override.
    out = classify_kind(
        text="The login page is broken.",
        lede_source="summary",
        overlay_enabled=True,
    )
    assert out.kind == "summary"
    assert out.confidence == pytest.approx(0.9)
    assert out.classifier_path == "type_based"


def test_overlay_tie_break_by_declaration_order() -> None:
    # "we decided to do it by Friday" matches both decision (0.85) and
    # commitment (0.75). decision wins on higher kind_weight.
    out = classify_kind(
        text="We decided to ship it by Friday.",
        lede_source="key_fact",
        overlay_enabled=True,
    )
    assert out.kind == "decision"
    assert out.pattern_match == "decision"


def test_overlay_disabled_falls_back_to_type_based() -> None:
    # Same text as the first overlay test, but with the flag off.
    out = classify_kind(
        text="I prefer dark mode.",
        lede_source="key_fact",
        overlay_enabled=False,
    )
    assert out.kind == "fact"
    assert out.classifier_path == "type_based"
    assert out.pattern_match is None
