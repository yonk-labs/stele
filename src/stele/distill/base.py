from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from stele.core.memory_record import MemoryRecord, MemoryScope

if TYPE_CHECKING:
    from stele.distill.models import DistilledItem


@runtime_checkable
class LLMSynthesizer(Protocol):
    """Optional, injected. The distill package imports no LLM client at module
    top (enforced by test_architecture). When None, distillation runs
    deterministically."""

    def __call__(self, prompt: str) -> str: ...


def _norm(text: str) -> str:
    """Normalize for dedup: lowercase, collapse whitespace, drop punctuation."""
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", text.lower())).strip()


def dedup_distilled(items: list[DistilledItem]) -> list[DistilledItem]:
    """Collapse cross-session duplicates by normalized summary, merging their
    source_refs (recurrence across sessions = stronger evidence). The first
    occurrence's concrete type (Rule/DistilledItem) and fields are kept. Applied
    AFTER the LLM refine, which normalizes wording so the same rule phrased two
    different ways across sessions becomes one item carrying both refs."""
    by_key: dict[str, DistilledItem] = {}
    for it in items:
        key = _norm(it.summary)
        if not key:
            continue
        if key not in by_key:
            by_key[key] = it
        else:
            kept = by_key[key]
            merged = list(dict.fromkeys([*kept.source_refs, *it.source_refs]))
            by_key[key] = kept.model_copy(update={"source_refs": merged})
    return list(by_key.values())


def active_memories(memory: object, scope: MemoryScope, limit: int = 1000) -> list[MemoryRecord]:
    """All ACTIVE (newest-valid) memories in scope, via the public Memory facade.

    `memory` is a stele.core.memory.Memory; typed as object to avoid a heavy
    import here. Passes status_filter=["active"] so superseded/retracted records
    are excluded -- callers that name themselves "active_memories" should only
    return current truth."""
    result = memory.list(scope, ["active"], limit=limit)  # type: ignore[attr-defined]
    return list(result)
