"""Regex pattern packs for the pattern-overlay classifier.

Each pack is a (kind, kind_weight, patterns) bundle. Matching is set-membership:
a kind matches if any pattern in its pack matches. Across kinds, declaration
order in this file is the deterministic tie-break.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stele.core.memory_record import MemoryKind


@dataclass(frozen=True)
class PatternPack:
    kind: MemoryKind
    kind_weight: float
    patterns: tuple[re.Pattern[str], ...]


def _compile(*sources: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(s) for s in sources)


PREFERENCE = PatternPack(
    kind="preference",
    kind_weight=0.85,
    patterns=_compile(
        r"(?i)\bi\s+(prefer|like|love|hate|dislike|enjoy)\b",
        r"(?i)\bmy\s+favou?rite\b",
        r"(?i)\bi(?:'m|\s+am)\s+(?:not\s+)?a\s+fan\s+of\b",
    ),
)

DECISION = PatternPack(
    kind="decision",
    kind_weight=0.85,
    patterns=_compile(
        r"(?i)\b(we|i)('ve|\s+have)?\s+decided\b",
        r"(?i)\blet'?s\s+go\s+with\b",
        r"(?i)\bwe(?:'re|\s+are)?\s+going\s+to\b",
        r"(?i)\bdecision\s*:\s*\S",
    ),
)

COMMITMENT = PatternPack(
    kind="commitment",
    kind_weight=0.75,
    patterns=_compile(
        r"(?i)\b(by|before)\s+\w+day\b",
        r"(?i)\b(TODO|FIXME)\b",
        r"(?i)\bi('ll|\s+will)\s+\w+",
        r"(?i)\bdue\s+(by|on)\b",
    ),
)

INSTRUCTION = PatternPack(
    kind="instruction",
    kind_weight=0.75,
    patterns=_compile(
        r"(?i)\b(please|always|never|don'?t)\b.*\b(do|use|avoid|commit|skip|run)\b",
        r"(?i)\b(always|never)\s+\w+",
    ),
)

ISSUE = PatternPack(
    kind="issue",
    kind_weight=0.65,
    patterns=_compile(
        r"(?i)\b(bug|broken|fails?|error|crash(?:es|ed|ing)?)\b",
        r"(?i)\bdoesn'?t\s+work\b",
        r"(?i)\bregression\b",
    ),
)

# Declaration order = deterministic tie-break across kinds.
PATTERN_PACKS: tuple[PatternPack, ...] = (
    PREFERENCE,
    DECISION,
    COMMITMENT,
    INSTRUCTION,
    ISSUE,
)


def match_first_kind(text: str) -> PatternPack | None:
    """Return the highest-priority matching pack, or None.

    Tie-break: highest kind_weight wins; on equal weight, declaration order
    in PATTERN_PACKS wins.
    """
    matches: list[PatternPack] = []
    for pack in PATTERN_PACKS:
        for pattern in pack.patterns:
            if pattern.search(text):
                matches.append(pack)
                break  # one pattern in the pack is enough; move to next pack
    if not matches:
        return None
    # Sort by (-kind_weight, declaration_index). Stable sort preserves
    # PATTERN_PACKS order for ties.
    index_of = {pack: i for i, pack in enumerate(PATTERN_PACKS)}
    matches.sort(key=lambda p: (-p.kind_weight, index_of[p]))
    return matches[0]
