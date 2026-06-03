"""Parity: the agent-facing surfaces deliver what the memory-mode benchmarks rely on.

The six memory-mode benchmarks (``benchmarks/external/memory_modes/``) call the
``Stele`` Python facade directly. Real agents never touch the facade — they go
through the MCP server (``stele_*`` tools) or the ``stele`` CLI. The CLI routes
every data-plane verb through the *same* bound MCP handler (see
``stele.cli.commands.data_plane.invoke`` — "one code path; the CLI cannot drift
from the MCP"), so asserting handler-vs-facade parity here is authoritative for
both surfaces at once.

The two modes that are clean wins — fact_recall and precedent_recall — both
retrieve with ``memory.search_with_score``. Their agent-facing door is
``stele_memory_search`` (which calls ``memory.search``). This module pins the
invariant the benchmarks silently assumed: every record the mode's retrieval
surfaces is also surfaced by the door an agent actually calls.

It exists because that invariant was *false* on the in-memory backend until a
companion fix: ``search`` used a whole-phrase substring test while
``search_with_score`` tokenized, so multi-word queries missed evidence over the
wire that the benchmark found in-process.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.mcp.tools import bind_handlers

BACKENDS = ["memory", "sqlite"]
if os.environ.get("STELE_PG_DSN"):
    BACKENDS.append("postgres")


def _stele(tmp_path: Path, backend: str) -> Stele:
    if backend == "memory":
        return Stele.from_config({"backend": {"type": "memory"}})
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
        )
    return Stele.from_config(
        {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}}
    )


def _handlers(stele: Stele) -> dict[str, Any]:
    return {t.name: t.handler for t in bind_handlers(stele) if t.handler}


def _door_ids(handlers: dict[str, Any], query: str, namespace: str) -> set[str]:
    """Memory ids surfaced by the agent door (MCP/CLI stele_memory_search)."""
    out = handlers["stele_memory_search"](query=query, namespace=namespace, limit=10)
    assert "error" not in out, out
    return {h["id"] for h in out["hits"]}


def _facade_ids(stele: Stele, query: str, scope: MemoryScope) -> list[str]:
    """Memory ids the mode's retrieval surfaces, best-ranked first."""
    hits = stele.memory.search_with_score(query, scope, limit=10)
    return [h.record.id for h in hits]


@pytest.mark.parametrize("backend", BACKENDS)
def test_fact_recall_door_surfaces_what_the_mode_finds(
    tmp_path: Path, backend: str
) -> None:
    """fact_recall retrieves with search_with_score; the door must agree.

    The query is multi-word and its terms are present but non-adjacent in the
    stored fact — exactly the shape that exposed the in-memory divergence.
    """
    ns = "parity_fact"
    stele = _stele(tmp_path, backend)
    h = _handlers(stele)
    scope = MemoryScope(namespace=ns)

    ref = str(stele.store("evidence: kafka stores data in partitions").reference)
    stele.memory.add(
        text="kafka uses partitions for parallelism",
        kind="fact",
        source_refs=[ref],
        scope=scope,
    )

    facade = _facade_ids(stele, "kafka partitions", scope)
    assert facade, "precondition: the mode's own retrieval must find the fact"

    door = _door_ids(h, "kafka partitions", ns)
    # Every record the mode relies on is reachable through the agent surface.
    assert set(facade) <= door, (
        f"[{backend}] door dropped evidence the mode surfaced: "
        f"facade={facade} door={door}"
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_precedent_recall_door_surfaces_the_right_episode(
    tmp_path: Path, backend: str
) -> None:
    """precedent_recall recalls a prior episode by its task descriptor.

    Three near-twin episodes differing only by quarter; the door must surface
    the same episode the mode's search_with_score ranks first.
    """
    ns = "parity_precedent"
    stele = _stele(tmp_path, backend)
    h = _handlers(stele)
    scope = MemoryScope(namespace=ns)

    ref = str(stele.store("episode evidence").reference)
    for quarter in ("Q1", "Q2", "Q3"):
        stele.memory.add(
            text=f"ran the market-trends review for {quarter}",
            summary=f"market-trends review {quarter}",
            detail=f"used trend-scanner on the {quarter} export",
            action="left at draft",
            kind="decision",
            source_refs=[ref],
            scope=scope,
            metadata={"ep_id": f"trends-{quarter}"},
        )

    # The descriptor an agent holds when it sits down to repeat the job.
    descriptor = "market-trends review Q3"
    facade = _facade_ids(stele, descriptor, scope)
    assert facade, "precondition: the mode's retrieval must find an episode"
    top = facade[0]

    door = _door_ids(h, descriptor, ns)
    assert top in door, (
        f"[{backend}] door missed the precedent the mode ranked #1: "
        f"top={top} door={door}"
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_search_methods_do_not_diverge(tmp_path: Path, backend: str) -> None:
    """Guard the root cause directly: search and search_with_score must agree
    on membership for a multi-word query, on every backend.

    This is the invariant the in-memory backend violated. Keeping it as its own
    assertion means a future regression names itself instead of hiding behind a
    mode-level test.
    """
    ns = "parity_methods"
    stele = _stele(tmp_path, backend)
    scope = MemoryScope(namespace=ns)

    from stele.core.memory_record import MemoryQuery

    ref = str(stele.store("ev").reference)
    stele.memory.add(
        text="raft uses leader election to reach consensus",
        kind="fact",
        source_refs=[ref],
        scope=scope,
    )

    q = "raft consensus"  # both terms present, non-adjacent
    scored = {h.record.id for h in stele.memory.search_with_score(q, scope, limit=10)}
    plain = {
        r.id for r in stele.memory.search(MemoryQuery(query=q, scope=scope, limit=10))
    }
    assert scored == plain, (
        f"[{backend}] search_with_score and search disagree on membership: "
        f"scored={scored} plain={plain}"
    )
