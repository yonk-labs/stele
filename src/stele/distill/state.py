from __future__ import annotations

import re

from stele.core.memory_record import MemoryScope
from stele.distill.base import active_memories
from stele.distill.models import DistilledItem, DistilledView


def _classify_state(text: str) -> str:
    """Deterministic 4-way state classifier based on keyword stems.

    Uses prefix anchors (\\b at word start, no word-end boundary) so that
    inflected forms ("retracted", "descoped", "shipped", "completed") all
    match their base stem without false positives on unrelated words."""
    t = text.lower()
    if re.search(r"\b(abandon|descop|retract|drop|cancel)", t):
        return "abandoned"
    if re.search(r"\b(ship|done|complet|finish|deploy|merg)", t):
        return "done"
    if re.search(r"\b(in.progress|underway|wip|reopen|rework|still|pending)", t):
        return "in_progress"
    return "in_progress"  # a live head with no terminal signal is still in flight


async def distill_state(d: object, scope: MemoryScope) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    # active_memories returns only status="active" records, so no extra filter needed.
    by_entity: dict[str, DistilledItem] = {}
    for m in active_memories(memory, scope):
        entity = (m.metadata or {}).get("entity") or m.summary or m.text
        by_entity[str(entity)] = DistilledItem(
            summary=str(entity),
            detail=_classify_state(m.text),
            confidence=m.confidence,
            source_refs=list(m.source_refs),
            memory_id=m.id,
        )
    items = list(by_entity.values())
    return DistilledView(mode="state", items=items, used_llm=False,
                         stats={"n": float(len(items))})
