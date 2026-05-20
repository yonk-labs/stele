"""MCP tool round-trips for the lifecycle + bulk-write surfaces (#21, #22).

Each tool is exercised through ``bind_handlers`` so the same code path the
MCP server uses gets hit. CLI tests in test_cli_lifecycle_bulk.py cover the
parallel subcommand surface.
"""

from __future__ import annotations

import json
from pathlib import Path

from stele import Stele
from stele.mcp.tools import bind_handlers


def _stele() -> Stele:
    return Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"raw_fetch_enabled": True}}
    )


def _handler(s: Stele, name: str):
    by_name = {t.name: t.handler for t in bind_handlers(s) if t.handler}
    return by_name[name]


def test_purge_namespace_refuses_without_confirm() -> None:
    s = _stele()
    s.store("data", namespace="ns")
    h = _handler(s, "stele_purge_namespace")
    result = h(namespace="ns")  # no confirm, no dry_run
    assert "error" in result
    assert "destructive" in result["error"]["message"]
    # Data still present.
    assert len(s.list(namespace="ns").items) == 1
    s.close()


def test_purge_namespace_dry_run_no_confirm_required() -> None:
    s = _stele()
    s.store("data", namespace="ns")
    h = _handler(s, "stele_purge_namespace")
    result = h(namespace="ns", dry_run=True)
    assert "error" not in result
    assert result["result"]["dry_run"] is True
    assert result["result"]["artifacts"] == 1
    # Still present after dry_run.
    assert len(s.list(namespace="ns").items) == 1
    s.close()


def test_purge_namespace_with_confirm_deletes() -> None:
    s = _stele()
    s.store("data", namespace="ns")
    h = _handler(s, "stele_purge_namespace")
    result = h(namespace="ns", confirm=True)
    assert "error" not in result
    assert result["result"]["artifacts"] == 1
    assert s.list(namespace="ns").items == []
    s.close()


def test_export_then_import_round_trips(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.jsonl"
    s1 = _stele()
    stored = s1.store("evidence content", namespace="ex")
    h_export = _handler(s1, "stele_export_namespace")
    result = h_export(namespace="ex", path=str(bundle))
    assert "error" not in result
    assert result["result"]["exported_count"] == 1
    s1.close()

    s2 = _stele()
    h_import = _handler(s2, "stele_import_namespace")
    out = h_import(path=str(bundle))
    assert "error" not in out
    fetched = s2.fetch(stored.reference, raw=True)
    assert fetched.content == "evidence content"
    s2.close()


def test_store_many_persists_n_artifacts() -> None:
    s = _stele()
    h = _handler(s, "stele_store_many")
    items = [
        {"content": f"row {i}", "namespace": "bulk"}
        for i in range(5)
    ]
    result = h(items=items)
    assert "error" not in result
    assert len(result["results"]) == 5
    assert len(s.list(namespace="bulk").items) == 5
    s.close()


def test_memory_add_many_persists_with_scope() -> None:
    s = _stele()
    h = _handler(s, "stele_memory_add_many")
    items = [
        {
            "text": f"fact {i}",
            "kind": "fact",
            "source_refs": [f"stele://x/{i}"],
            "scope": {"namespace": "bulk-mem"},
        }
        for i in range(3)
    ]
    result = h(items=items)
    assert "error" not in result
    assert len(result["results"]) == 3
    from stele.core.memory_record import MemoryScope
    listed = s.memory.list(MemoryScope(namespace="bulk-mem"))
    assert len(listed) == 3
    s.close()


def test_tool_catalog_includes_new_tools() -> None:
    """All 5 new tools must register as ToolSpec entries."""
    s = _stele()
    names = {t.name for t in bind_handlers(s)}
    expected = {
        "stele_purge_namespace",
        "stele_export_namespace",
        "stele_import_namespace",
        "stele_store_many",
        "stele_memory_add_many",
    }
    assert expected <= names
    s.close()


def test_store_many_validates_request_shape() -> None:
    """Bad input shape should land as a structured error, not raise."""
    s = _stele()
    h = _handler(s, "stele_store_many")
    # Missing required 'content' field.
    result = h(items=[{"namespace": "ns"}])
    assert "error" in result
    s.close()


def test_export_namespace_writes_jsonl_file(tmp_path: Path) -> None:
    """Sanity-check the bundle has the right shape."""
    bundle = tmp_path / "bundle.jsonl"
    s = _stele()
    s.store("artifact alpha", namespace="ex")
    from stele.core.memory_record import MemoryScope
    s.memory.add(
        text="memo alpha",
        kind="fact",
        source_refs=["stele://ex/a"],
        scope=MemoryScope(namespace="ex"),
    )
    h = _handler(s, "stele_export_namespace")
    h(namespace="ex", path=str(bundle))
    lines = [json.loads(line) for line in bundle.read_text().splitlines()]
    kinds = [ln["kind"] for ln in lines]
    assert kinds.count("artifact") == 1
    assert kinds.count("memory") == 1
    s.close()
