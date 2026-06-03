from __future__ import annotations

from stele.core.memory_record import MemoryScope
from stele.distill.models import DistilledView


async def distill_facts(d: object, scope: MemoryScope) -> DistilledView:
    return DistilledView(mode="facts", items=[])
