"""MCP tool contract tests parametrized across backends.

These tests bind real ``Stele`` instances (not mocks) to ``bind_handlers`` and
exercise the wire shape of the MCP tool surface. The goal is to catch facade
signature drift before it ships — unit tests mock the facade, but a real
``Stele`` can reveal mismatches (e.g., missing kwargs, return-shape changes)
that mocks can't.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from stele import Stele
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


def _handlers(stele: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in bind_handlers(stele):
        assert t.handler is not None
        out[t.name] = t.handler
    return out


@pytest.mark.parametrize("backend", BACKENDS)
def test_store_then_fetch_roundtrip(tmp_path: Path, backend: str) -> None:
    h = _handlers(_stele(tmp_path, backend))

    stored = h["stele_store"](payload="hello world", content_type="text")
    assert "error" not in stored, stored
    ref = stored["ref"]
    assert ref.startswith("stele://")

    fetched = h["stele_fetch"](ref=ref)
    assert "error" not in fetched, fetched
    assert "hello" in str(fetched.get("content", ""))


@pytest.mark.parametrize("backend", BACKENDS)
def test_memory_add_then_search(tmp_path: Path, backend: str) -> None:
    h = _handlers(_stele(tmp_path, backend))

    stored = h["stele_store"](payload="evidence body")
    assert "error" not in stored, stored
    ref = stored["ref"]

    added = h["stele_memory_add"](text="user prefers tabs", source_refs=[ref])
    assert "error" not in added, added
    assert added.get("memory_id")

    hits = h["stele_memory_search"](query="tabs")
    assert "error" not in hits, hits
    assert len(hits["hits"]) >= 1


def test_unknown_facade_method_returns_internal_error() -> None:
    """A handler that raises an unmapped exception surfaces as INTERNAL."""

    class Broken:
        def store(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("boom")

    h = _handlers(Broken())
    out = h["stele_store"](payload="x")
    assert out.get("error", {}).get("code") == "INTERNAL"
