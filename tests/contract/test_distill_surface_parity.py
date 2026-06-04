"""Parity: the distill MCP handler output matches the Stele.distill facade.

Agents always call stele_distill over MCP (or CLI, which routes through the
same bound handler). This test pins the invariant that the MCP surface returns
the same DistilledView the facade produces directly.
"""

from __future__ import annotations

import asyncio

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.mcp.tools import bind_handlers


def _handlers(stele: Stele) -> dict[str, object]:
    return {t.name: t.handler for t in bind_handlers(stele) if t.handler}


def _populate(s: Stele, ns: str) -> None:
    scope = MemoryScope(namespace=ns)
    ref = str(s.store("rulebook", namespace=ns).reference)
    s.memory.add(
        text="gpt-4o is outdated, do not use it",
        kind="pitfall",
        source_refs=[ref],
        scope=scope,
        summary="gpt-4o is outdated",
        metadata={"do_instead": "use gpt-5-mini", "domain": "config"},
    )


def test_distill_rules_mcp_matches_facade() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "parity-distill"
    _populate(s, ns)
    facade_view = asyncio.run(s.distill.rules(MemoryScope(namespace=ns)))
    h = _handlers(s)
    out = h["stele_distill"](mode="rules", namespace=ns)  # type: ignore[operator]
    assert "error" not in out, out
    mcp_items = out["view"]["items"]
    assert len(mcp_items) == len(facade_view.items)
    assert any(it.get("do_instead") == "use gpt-5-mini" for it in mcp_items)
    # every distilled item carries evidence (SC-011 / DC-004)
    assert all(it["source_refs"] for it in mcp_items)


def test_distill_rejects_unknown_mode() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    h = _handlers(s)
    out = h["stele_distill"](mode="bogus", namespace="x")  # type: ignore[operator]
    assert out.get("error", {}).get("code") == "VALIDATION"


def _populate_episode(s: Stele, ns: str) -> None:
    scope = MemoryScope(namespace=ns)
    ref = str(
        s.store(
            "auth session",
            namespace=ns,
            session_id="sess-a",
            metadata={"source": "session-ingest"},
        ).reference
    )
    s.memory.add(
        text="switched to keep120",
        kind="decision",
        source_refs=[ref],
        scope=scope,
        summary="switch to keep120",
    )


def test_distill_episodes_mcp_matches_facade() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "parity-distill-episodes"
    _populate_episode(s, ns)
    facade_view = asyncio.run(s.distill.episodes(MemoryScope(namespace=ns)))
    h = _handlers(s)
    out = h["stele_distill"](mode="episodes", namespace=ns)  # type: ignore[operator]
    assert "error" not in out, out
    mcp_items = out["view"]["items"]
    assert len(mcp_items) == len(facade_view.items) == 1
    assert all(it["source_refs"] for it in mcp_items)  # evidence carried
    assert "switch to keep120" in mcp_items[0]["decisions"]


def test_distill_timeline_mcp_matches_facade() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "parity-distill-timeline"
    _populate_episode(s, ns)
    facade_view = asyncio.run(s.distill.timeline(MemoryScope(namespace=ns)))
    h = _handlers(s)
    out = h["stele_distill"](mode="timeline", namespace=ns)  # type: ignore[operator]
    assert "error" not in out, out
    mcp_items = out["view"]["items"]
    assert out["view"]["mode"] == "timeline"
    assert len(mcp_items) == len(facade_view.items) == 1
    assert all(it["source_refs"] for it in mcp_items)  # evidence carried


def test_distill_spans_mcp_matches_facade() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "parity-distill-spans"
    _populate_episode(s, ns)
    facade_view = asyncio.run(s.distill.spans(MemoryScope(namespace=ns)))
    h = _handlers(s)
    out = h["stele_distill"](mode="spans", namespace=ns)  # type: ignore[operator]
    assert "error" not in out, out
    mcp_items = out["view"]["items"]
    assert out["view"]["mode"] == "spans"
    # no embedder -> one-per-span fallback: one episode -> one span
    assert len(mcp_items) == len(facade_view.items) == 1
    assert all(it["source_refs"] for it in mcp_items)  # evidence carried
    assert mcp_items[0]["span_id"].startswith("span-")
