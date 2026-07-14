from __future__ import annotations

from stele.core.memory_record import MemoryScope
from stele.distill.base import active_memories
from stele.distill.models import DistilledItem, DistilledView


async def distill_facts(d: object, scope: MemoryScope) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    items: list[DistilledItem] = []
    seen: set[str] = set()
    for m in active_memories(memory, scope):
        if m.kind != "fact":
            continue
        key = (m.summary or m.text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            DistilledItem(
                summary=m.summary or m.text,
                detail=m.detail or "",
                confidence=m.confidence,
                source_refs=list(m.source_refs),
                memory_id=m.id,
            )
        )
    return DistilledView(
        mode="facts",
        items=items,
        used_llm=False,
        stats={"n": float(len(items))},
    )
