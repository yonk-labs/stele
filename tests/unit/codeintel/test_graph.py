"""GraphResolver: cross-file resolution over pg-raggraph's code graph (slice E).

The query function is injected, so these run without Postgres or pg-raggraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stele.codeintel.graph import GraphResolver


@dataclass
class _Edge:
    fqn: str


@dataclass
class _Impact:
    callees: list[_Edge] = field(default_factory=list)
    callers: list[_Edge] = field(default_factory=list)


def test_no_db_degrades_to_empty() -> None:
    r = GraphResolver(db=None)
    assert r.callees("pkg.main") == []
    assert r.callers("pkg.main") == []


def test_callees_resolved_from_graph() -> None:
    async def fake(db: Any, fqn: str, *, namespace: str, depth: int) -> _Impact:
        assert fqn == "pkg.main" and namespace == "ns"
        return _Impact(callees=[_Edge("pkg.helper"), _Edge("other.util")])

    r = GraphResolver(db=object(), namespace="ns", impact_fn=fake)
    assert r.callees("pkg.main") == ["pkg.helper", "other.util"]


def test_callers_resolved_from_graph() -> None:
    async def fake(db: Any, fqn: str, *, namespace: str, depth: int) -> _Impact:
        return _Impact(callers=[_Edge("pkg.caller")])

    r = GraphResolver(db=object(), impact_fn=fake)
    assert r.callers("pkg.helper") == ["pkg.caller"]


def test_depth_passed_through() -> None:
    seen: dict[str, int] = {}

    async def fake(db: Any, fqn: str, *, namespace: str, depth: int) -> _Impact:
        seen["depth"] = depth
        return _Impact()

    GraphResolver(db=object(), impact_fn=fake).callees("x", depth=3)
    assert seen["depth"] == 3
