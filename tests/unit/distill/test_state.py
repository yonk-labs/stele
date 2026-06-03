from __future__ import annotations

import asyncio

from stele import Stele
from stele.core.memory_record import MemoryScope


def _add(s: Stele, ns: str, entity: str, text: str, supersedes=None):
    scope = MemoryScope(namespace=ns)
    ref = str(s.store(text, namespace=ns).reference)
    res = s.memory.add(text=text, kind="decision", source_refs=[ref], scope=scope,
                       summary=entity, detail=text, metadata={"entity": entity},
                       supersedes=[supersedes] if supersedes else None)
    return res.record.id


def test_distill_state_returns_current_truth_per_entity():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-state"
    first = _add(s, ns, "headroom-hypothesis", "exploring the headroom hypothesis")
    _add(s, ns, "headroom-hypothesis", "retracted the headroom hypothesis, descoped",
         supersedes=first)
    _add(s, ns, "pg-lexicon-phase-f", "phase F shipped to prod, complete")
    view = asyncio.run(s.distill.state(MemoryScope(namespace=ns)))
    assert view.mode == "state"
    states = {it.summary: it.detail for it in view.items}
    # current truth: the supersession head won
    assert states["headroom-hypothesis"] == "abandoned"
    assert states["pg-lexicon-phase-f"] == "done"
    assert all(it.source_refs for it in view.items)
