"""Pure entity-identity helpers for evolving-fact consolidation.

The LLM emits a human-visible subject_label + aspect; deterministic code turns
them into stable keys, so inconsistent LLM identifiers (test1/Test 1/test-1)
collapse without trusting an opaque LLM slug. No LLM, no I/O.
"""

from __future__ import annotations

import re
import unicodedata

# Aspect vocabulary the extractor is asked to prefer. Synonyms fold in; unknown
# aspects are kept DISTINCT (never folded to a shared bucket), biasing toward
# false-negatives over false merges.
SEEDED_ASPECTS: tuple[str, ...] = (
    "status", "coverage", "version", "owner", "location", "config",
)
_ASPECT_SYNONYMS: dict[str, str] = {
    "result": "status", "outcome": "status", "state": "status",
    "reliability": "status", "health": "status",
    "scope": "coverage", "covers": "coverage",
    "path": "location", "dir": "location", "directory": "location",
    "ver": "version", "assignee": "owner", "responsible": "owner",
    "configuration": "config", "settings": "config",
}

_PUNCT = re.compile(r"[^\w\s]")
_ALNUM_SPLIT = re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")
_WS = re.compile(r"\s+")


def canonical_subject(label: str) -> str:
    """Stable key for an entity subject. NFKC-normalize, casefold, split
    alpha/digit boundaries, strip punctuation, collapse whitespace. So 'test1',
    'Test 1', 'test-1' all map to 'test 1', but 'Test 2' stays distinct.
    Empty/whitespace -> '' (no slot)."""
    s = unicodedata.normalize("NFKC", label or "").strip()
    if not s:
        return ""
    s = _ALNUM_SPLIT.sub(" ", s)   # test1 -> test 1
    s = _PUNCT.sub(" ", s)          # test-1 -> test 1
    return _WS.sub(" ", s).strip().casefold()


def canonical_aspect(aspect: str) -> str:
    """Map a raw aspect to a canonical one. Seeded aspects pass through; known
    synonyms fold in; anything else is canonicalized but kept DISTINCT (a single
    lowercase token). Empty -> '' (no slot)."""
    s = unicodedata.normalize("NFKC", aspect or "").strip().casefold()
    if not s:
        return ""
    s = _WS.sub(" ", _PUNCT.sub(" ", s)).strip().replace(" ", "_")
    return _ASPECT_SYNONYMS.get(s, s)
