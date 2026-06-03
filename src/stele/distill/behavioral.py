from __future__ import annotations

from stele.core.memory_record import MemoryScope
from stele.distill.models import DistilledView


async def distill_skills(d: object, scope: MemoryScope) -> DistilledView:
    return DistilledView(mode="skills", items=[])


async def distill_best_practices(d: object, scope: MemoryScope) -> DistilledView:
    return DistilledView(mode="best_practices", items=[])


async def distill_rules(d: object, scope: MemoryScope) -> DistilledView:
    return DistilledView(mode="rules", items=[])
