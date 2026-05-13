"""Pure classifier: lede output type → MemoryKind, with optional pattern overlay."""

from __future__ import annotations

from dataclasses import dataclass

from stele.core.memory_record import MemoryKind
from stele.extraction.models import ClassifierPath, LedeSource

_TYPE_BASED_DEFAULTS: dict[LedeSource, tuple[MemoryKind, float]] = {
    "key_fact": ("fact", 0.7),
    "stat": ("fact", 0.8),
    "metadata": ("fact", 0.7),
    "phrase": ("fact", 0.5),
    "summary": ("summary", 0.9),
}


@dataclass(frozen=True)
class ClassifierOutput:
    kind: MemoryKind
    confidence: float
    classifier_path: ClassifierPath
    pattern_match: str | None


def classify_kind(
    *,
    text: str,
    lede_source: LedeSource,
    overlay_enabled: bool,
) -> ClassifierOutput:
    """Deterministically classify a candidate's kind.

    The lede output type provides a default kind + confidence. When
    overlay_enabled is True, a regex pack may override the default with a
    higher-confidence agent-loop kind.

    Args are keyword-only so callers can't accidentally swap text and
    lede_source.
    """
    default_kind, default_confidence = _TYPE_BASED_DEFAULTS[lede_source]
    if not overlay_enabled:
        return ClassifierOutput(
            kind=default_kind,
            confidence=default_confidence,
            classifier_path="type_based",
            pattern_match=None,
        )

    from stele.extraction.patterns import match_first_kind

    pack = match_first_kind(text)
    if pack is None or pack.kind_weight <= default_confidence:
        return ClassifierOutput(
            kind=default_kind,
            confidence=default_confidence,
            classifier_path="type_based",
            pattern_match=None,
        )

    return ClassifierOutput(
        kind=pack.kind,
        confidence=pack.kind_weight,
        classifier_path="pattern_overlay",
        pattern_match=pack.kind,
    )
