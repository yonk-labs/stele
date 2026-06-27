"""Pure entity-identity helpers for evolving-fact consolidation.

The LLM emits a human-visible subject_label + aspect; deterministic code turns
them into stable keys, so inconsistent LLM identifiers (test1/Test 1/test-1)
collapse without trusting an opaque LLM slug. No LLM, no I/O.
"""

from __future__ import annotations

import re
import unicodedata

# Subject type vocabulary the extractor is asked to prefer. Unknown types stay
# distinct (lowercased), never folded, biasing to false-negatives.
SEEDED_SUBJECT_TYPES: tuple[str, ...] = (
    "service", "component", "project", "package", "person", "user", "config",
    "environment", "entity",
)

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
    # Implementation-identity cluster (#72): an entity's "what technology IS it"
    # attribute is the one the LLM most often relabels across sessions
    # (engine/runtime/framework/platform/technology/tool name the same slot), so a
    # value swap (Postgres->MySQL, unittest->pytest, Jenkins->GitHub Actions) lands
    # in one slot and supersedes instead of leaving a stale sibling. Safe under the
    # 0% over-merge gate: the slot still keys on subject_id, so genuinely-distinct
    # entities never collide on a shared aspect alone.
    "engine": "implementation", "runtime": "implementation",
    "framework": "implementation", "platform": "implementation",
    "technology": "implementation", "tech": "implementation",
    "tool": "implementation",
    # Scale synonyms (#72): replica_count vs replicas drifted across sessions.
    "replica_count": "replicas", "replica": "replicas",
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


_SELF_REFERENTIAL: frozenset[str] = frozenset({
    "i", "me", "my", "myself", "mine", "the user", "current user",
})


def canonical_subject_type(subject_type: str) -> str:
    """Normalize a subject_type. Empty -> 'entity'. Unknown types are kept
    distinct (lowercased token), never folded, biasing to false-negatives."""
    s = canonical_subject(subject_type)
    return s.replace(" ", "_") if s else "entity"


def is_self_referential(label: str) -> bool:
    """True when the subject label refers to the scope's user ('I', 'me', ...)."""
    return canonical_subject(label) in _SELF_REFERENTIAL
