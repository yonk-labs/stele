from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stele.mcp.tools import TOOLS, ToolSpec, bind_handlers

EXPECTED_TOOLS = {
    # core artifact + memory + extract + recall (Phase 1-5, 18 tools)
    "stele_store",
    "stele_fetch",
    "stele_search",
    "stele_query",
    "stele_list",
    "stele_delete",
    "stele_read_bounded",
    "stele_memory_add",
    "stele_memory_get",
    "stele_memory_search",
    "stele_memory_list",
    "stele_memory_update",
    "stele_memory_delete",
    "stele_memory_retract",
    "stele_extract_from_text",
    "stele_extract_from_messages",
    "stele_extract_from_artifact",
    "stele_recall",
    "stele_stash_tool_result",
    # lifecycle + bulk-write (#21, #22) — 5 new tools
    "stele_purge_namespace",
    "stele_export_namespace",
    "stele_import_namespace",
    "stele_store_many",
    "stele_memory_add_many",
    # distill (#11)
    "stele_distill",
}


def test_all_tools_registered() -> None:
    assert {t.name for t in TOOLS} == EXPECTED_TOOLS


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_every_tool_has_complete_spec(tool: ToolSpec) -> None:
    assert tool.name.startswith("stele_")
    assert tool.description
    assert isinstance(tool.input_schema, dict)
    assert tool.input_schema.get("type") == "object"
    assert "properties" in tool.input_schema


def test_tool_names_unique() -> None:
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names))


def test_bind_handlers_returns_callable_per_tool() -> None:
    fake_stele = MagicMock()
    bound = bind_handlers(fake_stele)
    assert {t.name for t in bound} == EXPECTED_TOOLS
    for spec in bound:
        assert callable(spec.handler), f"{spec.name} has no handler"


def test_bind_handlers_wires_store() -> None:
    fake_stele = MagicMock()
    fake_ref = MagicMock()
    fake_ref.__str__ = lambda self: "stele://x/abc"  # type: ignore[assignment,misc]
    fake_stele.store.return_value = MagicMock(reference=fake_ref)

    bound = bind_handlers(fake_stele)
    handler = next(b for b in bound if b.name == "stele_store").handler
    assert handler is not None
    result = handler(payload="hello", content_type="text/plain")
    fake_stele.store.assert_called_once()
    assert result == {"ref": "stele://x/abc"}


def test_query_handler_passes_filters_and_parses_dates() -> None:
    import datetime as dt

    fake_stele = MagicMock()
    fake_stele.query.return_value = []
    bound = bind_handlers(fake_stele)
    handler = next(b for b in bound if b.name == "stele_query").handler
    assert handler is not None
    handler(
        query="auth bug last week",
        namespace="sess",
        session_id="s1",
        filters={
            "metadata.git_branch": "auth",
            "created_after": "2026-05-18T00:00:00Z",
        },
        now="2026-05-29T12:00:00Z",
    )
    _args, kwargs = fake_stele.query.call_args
    assert kwargs["session_id"] == "s1"
    # ISO date strings on created_* / now are coerced to datetimes for the facade.
    assert isinstance(kwargs["filters"]["created_after"], dt.datetime)
    assert kwargs["filters"]["metadata.git_branch"] == "auth"
    assert isinstance(kwargs["now"], dt.datetime)


def test_query_tool_schema_exposes_filters() -> None:
    spec = next(t for t in TOOLS if t.name == "stele_query")
    props = spec.input_schema["properties"]
    assert {"filters", "session_id", "now"} <= set(props)


def test_bind_handlers_wires_memory_add() -> None:
    fake_stele = MagicMock()
    fake_record = MagicMock()
    fake_record.id = "m-123"
    fake_stele.memory.add.return_value = MagicMock(record=fake_record)

    bound = bind_handlers(fake_stele)
    handler = next(b for b in bound if b.name == "stele_memory_add").handler
    assert handler is not None
    result = handler(text="t", source_refs=["stele://x/a"])
    fake_stele.memory.add.assert_called_once()
    # Don't over-constrain the kwarg shape — different facades may accept None vs missing
    assert result.get("memory_id") == "m-123"


def test_bind_handlers_routes_pii_blocked() -> None:
    from stele.core.exceptions import PIIBlockedError
    fake_stele = MagicMock()
    fake_stele.fetch.side_effect = PIIBlockedError("nope")

    bound = bind_handlers(fake_stele)
    handler = next(b for b in bound if b.name == "stele_fetch").handler
    assert handler is not None
    result = handler(ref="stele://x/a")
    assert result == {"error": {"code": "PII_BLOCKED", "message": "nope", "context": {}}}
