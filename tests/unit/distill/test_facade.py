from __future__ import annotations

import asyncio

from stele import Stele
from stele.distill.models import DistilledView


def test_distill_facade_attaches_with_seven_methods():
    s = Stele.from_config({"backend": {"type": "memory"}})
    d = s.distill
    for m in (
        "facts", "precedents", "state", "skills", "best_practices", "rules",
        "episodes",
    ):
        assert callable(getattr(d, m))


def test_distill_methods_are_awaitable_and_return_a_view():
    s = Stele.from_config({"backend": {"type": "memory"}})
    from stele.core.memory_record import MemoryScope
    view = asyncio.run(s.distill.facts(MemoryScope(namespace="t")))
    assert isinstance(view, DistilledView)
    assert view.mode == "facts"
