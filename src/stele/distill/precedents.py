from __future__ import annotations

from stele.core.memory_record import MemoryScope
from stele.distill.base import active_memories
from stele.distill.models import DistilledItem, DistilledView


def _item(record: object) -> DistilledItem:
    return DistilledItem(
        summary=record.summary or record.text,  # type: ignore[attr-defined]
        detail=record.detail or "",             # type: ignore[attr-defined]
        confidence=record.confidence,           # type: ignore[attr-defined]
        source_refs=list(record.source_refs),   # type: ignore[attr-defined]
    )


async def distill_precedents(
    d: object, scope: MemoryScope, query: str | None = None
) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    if query:
        hits = memory.search_with_score(query, scope, limit=20)
        records = [h.record for h in hits if h.record.kind == "decision"]
    else:
        records = [m for m in active_memories(memory, scope) if m.kind == "decision"]
    items: list[DistilledItem] = []
    seen: set[str] = set()
    for r in records:
        key = (r.summary or r.text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(_item(r))
    return DistilledView(mode="precedents", items=items, used_llm=False,
                         stats={"n": float(len(items))})
