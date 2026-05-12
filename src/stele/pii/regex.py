"""Lightweight deterministic regex PII scrubber."""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern

from stele.core.artifact import PIIDetection, ScrubResult


@dataclass(frozen=True)
class PIIPattern:
    entity_type: str
    pattern: Pattern[str]


DEFAULT_PATTERNS = [
    PIIPattern("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    PIIPattern("PHONE", re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")),
    PIIPattern("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    PIIPattern("CREDIT_CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    PIIPattern(
        "SECRET",
        re.compile(
            r"\b(?:(?:sk|pk|api|token|secret|key)[_-][A-Za-z0-9][A-Za-z0-9_-]{12,})\b",
            re.I,
        ),
    ),
]


class RegexPIIScrubber:
    def __init__(self, patterns: list[PIIPattern] | None = None) -> None:
        self.patterns = patterns or DEFAULT_PATTERNS

    def scrub(self, text: str, *, context: dict[str, object] | None = None) -> ScrubResult:
        del context
        detections: list[PIIDetection] = []
        spans: list[tuple[int, int, str]] = []
        counters: dict[str, int] = {}
        occupied: list[tuple[int, int]] = []
        for pii_pattern in self.patterns:
            for match in pii_pattern.pattern.finditer(text):
                start, end = match.span()
                overlaps = any(
                    start < taken_end and end > taken_start
                    for taken_start, taken_end in occupied
                )
                if overlaps:
                    continue
                counters[pii_pattern.entity_type] = counters.get(pii_pattern.entity_type, 0) + 1
                replacement = f"[{pii_pattern.entity_type}_{counters[pii_pattern.entity_type]}]"
                spans.append((start, end, replacement))
                occupied.append((start, end))
                detections.append(
                    PIIDetection(
                        entity_type=pii_pattern.entity_type,
                        start=start,
                        end=end,
                        replacement=replacement,
                        detector="regex",
                    )
                )
        if not spans:
            return ScrubResult(text=text, detections=[])
        scrubbed_parts: list[str] = []
        cursor = 0
        for start, end, replacement in sorted(spans):
            scrubbed_parts.append(text[cursor:start])
            scrubbed_parts.append(replacement)
            cursor = end
        scrubbed_parts.append(text[cursor:])
        return ScrubResult(text="".join(scrubbed_parts), detections=detections)
