"""Pure, deterministic subject-identity resolution. No DB, no LLM, no embeddings.
The LLM proposes a raw label; this resolves it to a stable subject_id keyed within
a scope. Over-merge is worse than under-merge: only an explicit alias or a
self-referential rule binds different labels; everything else stays distinct."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from stele.extraction.identity import (
    canonical_subject,
    canonical_subject_type,
    is_self_referential,
)


@dataclass(frozen=True)
class ExistingSubject:
    subject_id: str
    subject_type: str
    normalized_label: str


class SubjectDisambiguationError(Exception):
    """Raised when a label matches more than one existing subject in scope and
    the policy is to refuse rather than mint."""


def resolve_subject(
    *,
    scope_key: str,
    subject_type: str,
    raw_label: str,
    user_id: str | None,
    existing: list[ExistingSubject],
    aliases: dict[str, str],
    proposed_subject_id: str | None = None,
    on_ambiguous: Literal["refuse", "mint"] = "refuse",
) -> str:
    """Resolve a raw label to a canonical subject_id.

    Resolution order (highest to lowest priority):
    1. Self-referential rule: user_id binding
    2. Curated alias: authoritative deterministic override
    3. Validated LLM handoff: proposed_subject_id (select-only, never invent)
    4. Exact normalized-label match in existing subjects
    5. Mint new subject_id (or refuse if ambiguous)
    """
    stype = canonical_subject_type(subject_type)
    norm = canonical_subject(raw_label)
    if user_id and is_self_referential(raw_label):
        return f"user:{user_id}"
    if norm in aliases:
        return aliases[norm]
    if proposed_subject_id and proposed_subject_id in {e.subject_id for e in existing}:
        return proposed_subject_id   # validated LLM handoff (select-only, never invent)
    matches = [e for e in existing if e.subject_type == stype and e.normalized_label == norm]
    if len(matches) == 1:
        return matches[0].subject_id
    if len(matches) > 1:
        if on_ambiguous == "mint":
            return f"{stype}:{norm}"
        raise SubjectDisambiguationError(
            f"label {raw_label!r} ({stype}) is ambiguous in scope {scope_key!r}: "
            f"{[m.subject_id for m in matches]}"
        )
    return f"{stype}:{norm}"
