"""Tests for the type-based classifier defaults."""

from __future__ import annotations

import pytest

from stele.extraction.classifier import ClassifierOutput, classify_kind


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
    with pytest.raises(Exception):
        out.kind = "preference"  # type: ignore[misc]
