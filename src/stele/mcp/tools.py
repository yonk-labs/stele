"""MCP tool registry and handler binding.

ToolSpec is the unit shipped to the MCP transport. TOOLS is the immutable
catalog; bind_handlers(stele) returns a new list with handlers closed over
a concrete Stele instance, each wrapped by the errors.guard decorator so
exceptions surface as structured JSON.

The MCP-facing schemas are intentionally simpler than the underlying Stele
facade signatures. Handlers translate MCP-friendly inputs (e.g., a
``namespace`` string + free-text query) into the typed facade calls
(``MemoryScope``, ``MemoryQuery``, ``datetime`` instances, etc.). This keeps
the wire surface stable while the internal facade can evolve.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from stele.mcp.errors import guard

HandlerFn = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: HandlerFn | None = field(default=None)


def _obj(
    properties: dict[str, dict[str, Any]],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_INT = {"type": "integer"}
_OBJ_ANY: dict[str, Any] = {"type": "object", "additionalProperties": True}
_STR_LIST: dict[str, Any] = {"type": "array", "items": _STR}


TOOLS: list[ToolSpec] = [
    # ---- artifact surface ----
    ToolSpec(
        "stele_store",
        "Store bytes/text behind a stele:// reference and return the ref.",
        _obj(
            {
                "payload": _STR,
                "content_type": _STR,
                "namespace": _STR,
                "metadata": _OBJ_ANY,
            },
            ["payload"],
        ),
    ),
    ToolSpec(
        "stele_fetch",
        "Resolve a stele:// reference to its bytes/text + summary.",
        _obj({"ref": _STR}, ["ref"]),
    ),
    ToolSpec(
        "stele_search",
        "Search artifacts via the configured retrieval backend.",
        _obj(
            {"ref": _STR, "query": _STR, "mode": _STR, "limit": _INT},
            ["ref", "query"],
        ),
    ),
    ToolSpec(
        "stele_query",
        "Targeted query against the chunk index (vector/hybrid when configured).",
        _obj(
            {"query": _STR, "namespace": _STR, "mode": _STR, "limit": _INT},
            ["query"],
        ),
    ),
    ToolSpec(
        "stele_list",
        "List stored artifacts.",
        _obj({"namespace": _STR, "limit": _INT}),
    ),
    ToolSpec(
        "stele_delete",
        "Delete a stored artifact by reference.",
        _obj({"ref": _STR}, ["ref"]),
    ),
    # ---- memory surface ----
    ToolSpec(
        "stele_memory_add",
        "Add a memory record citing its source_refs.",
        _obj(
            {
                "text": _STR,
                "source_refs": _STR_LIST,
                "kind": _STR,
                "namespace": _STR,
                "supersedes": _STR_LIST,
                "confidence": {"type": "number"},
                "metadata": _OBJ_ANY,
            },
            ["text", "source_refs"],
        ),
    ),
    ToolSpec(
        "stele_memory_get",
        "Fetch a single memory record by id.",
        _obj({"memory_id": _STR}, ["memory_id"]),
    ),
    ToolSpec(
        "stele_memory_search",
        "Search memory with optional as_of time travel.",
        _obj(
            {
                "query": _STR,
                "namespace": _STR,
                "as_of": _STR,
                "limit": _INT,
                "include_superseded": {"type": "boolean"},
            },
            ["query"],
        ),
    ),
    ToolSpec(
        "stele_memory_list",
        "List memory records, optionally at a past point in time.",
        _obj(
            {
                "namespace": _STR,
                "as_of": _STR,
                "limit": _INT,
                "status_filter": _STR_LIST,
            },
        ),
    ),
    ToolSpec(
        "stele_memory_update",
        "Update metadata of a memory record. Text changes are rejected; use add(supersedes=).",
        _obj({"memory_id": _STR, "metadata": _OBJ_ANY}, ["memory_id"]),
    ),
    ToolSpec(
        "stele_memory_delete",
        "Soft-delete a memory record.",
        _obj({"memory_id": _STR}, ["memory_id"]),
    ),
    ToolSpec(
        "stele_memory_retract",
        "Retract a memory record with a reason (preserves audit).",
        _obj({"memory_id": _STR, "reason": _STR}, ["memory_id", "reason"]),
    ),
    # ---- extraction ----
    ToolSpec(
        "stele_extract_from_text",
        "Run deterministic extraction on free text; commits via memory.add.",
        _obj(
            {"text": _STR, "source_refs": _STR_LIST, "namespace": _STR},
            ["text", "source_refs"],
        ),
    ),
    ToolSpec(
        "stele_extract_from_messages",
        "Extract from a list of chat messages.",
        _obj(
            {
                "messages": {"type": "array", "items": _OBJ_ANY},
                "namespace": _STR,
            },
            ["messages"],
        ),
    ),
    ToolSpec(
        "stele_extract_from_artifact",
        "Extract from a stored artifact by reference.",
        _obj({"ref": _STR, "namespace": _STR}, ["ref"]),
    ),
    # ---- recall ----
    ToolSpec(
        "stele_recall",
        "Run a recall strategy; supports as_of, version_filter, retracted_behavior.",
        _obj(
            {
                "query": _STR,
                "namespace": _STR,
                "strategy": _STR,
                "as_of": _STR,
                "version_filter": _STR,
                "retracted_behavior": _STR,
                "max_memory_hits": _INT,
                "max_artifact_hits": _INT,
            },
            ["query"],
        ),
    ),
    # ---- interception ----
    ToolSpec(
        "stele_stash_tool_result",
        (
            "Route a tool's raw output through interception; returns a stele:// ref + "
            "summary if oversize, else passthrough."
        ),
        _obj(
            {
                "tool_name": _STR,
                "raw_output": _STR,
                "namespace": _STR,
                "metadata": _OBJ_ANY,
            },
            ["tool_name", "raw_output"],
        ),
    ),
]


def _to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return _to_jsonable(dump(mode="json") if _accepts_mode(dump) else dump())
    if hasattr(obj, "__dict__"):
        return {
            k: _to_jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")
        }
    return str(obj)


def _accepts_mode(dump: Callable[..., Any]) -> bool:
    """Pydantic v2's model_dump accepts mode=; raw objects' may not."""
    try:
        import inspect

        return "mode" in inspect.signature(dump).parameters
    except (TypeError, ValueError):
        return False


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    # Accept ISO 8601 (with or without trailing Z)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _build_scope(namespace: str | None) -> Any:
    from stele.core.memory_record import MemoryScope

    return MemoryScope(namespace=namespace or "default")


def bind_handlers(stele: Any) -> list[ToolSpec]:
    """Return TOOLS with each handler bound to the given Stele instance.

    Every handler is wrapped by ``guard`` so exceptions become structured JSON.
    """

    @guard
    def store(
        payload: str,
        content_type: str | None = None,
        namespace: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if content_type is not None:
            kwargs["content_type"] = content_type
        if namespace is not None:
            kwargs["namespace"] = namespace
        if metadata is not None:
            kwargs["metadata"] = metadata
        result = stele.store(payload, **kwargs)
        return {"ref": str(result.reference)}

    @guard
    def fetch(ref: str) -> dict[str, Any]:
        result = stele.fetch(ref)
        return {
            "content": getattr(result, "content", None),
            "content_type": getattr(result, "content_type", None),
            "scrubbed": bool(getattr(result, "scrubbed", False)),
            "pii": _to_jsonable(getattr(result, "pii", None)),
            "byte_size": getattr(result, "byte_size", None),
        }

    @guard
    def search(
        ref: str,
        query: str,
        mode: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        if mode is not None:
            kwargs["mode"] = mode
        hits = stele.search(ref, query, **kwargs)
        return {"hits": [_to_jsonable(h) for h in hits]}

    @guard
    def query(
        query: str,
        namespace: str | None = None,
        mode: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        if mode is not None:
            kwargs["mode"] = mode
        hits = stele.query(namespace or "default", query, **kwargs)
        return {"hits": [_to_jsonable(h) for h in hits]}

    @guard
    def list_(namespace: str | None = None, limit: int = 100) -> dict[str, Any]:
        page = stele.list(namespace=namespace, limit=limit)
        return {"page": _to_jsonable(page)}

    @guard
    def delete(ref: str) -> dict[str, Any]:
        ok = stele.delete(ref)
        return {"ok": bool(ok)}

    @guard
    def memory_add(
        text: str,
        source_refs: list[str],
        kind: str = "fact",
        namespace: str | None = None,
        supersedes: list[str] | None = None,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "text": text,
            "kind": kind,
            "source_refs": source_refs,
            "scope": _build_scope(namespace),
            "confidence": confidence,
        }
        if supersedes is not None:
            kwargs["supersedes"] = supersedes
        if metadata is not None:
            kwargs["metadata"] = metadata
        result = stele.memory.add(**kwargs)
        record = getattr(result, "record", None)
        memory_id = getattr(record, "id", None) if record is not None else None
        return {
            "memory_id": memory_id,
            "duplicate_of": getattr(result, "duplicate_of", None),
            "superseded_ids": list(getattr(result, "superseded_ids", []) or []),
        }

    @guard
    def memory_get(memory_id: str) -> dict[str, Any]:
        return {"record": _to_jsonable(stele.memory.get(memory_id))}

    @guard
    def memory_search(
        query: str,
        namespace: str | None = None,
        as_of: str | None = None,
        limit: int = 10,
        include_superseded: bool = False,
    ) -> dict[str, Any]:
        from stele.core.memory_record import MemoryQuery

        mq = MemoryQuery(
            query=query,
            scope=_build_scope(namespace),
            as_of=_parse_dt(as_of),
            include_superseded=include_superseded,
            limit=limit,
        )
        hits = stele.memory.search(mq)
        return {"hits": [_to_jsonable(h) for h in hits]}

    @guard
    def memory_list(
        namespace: str | None = None,
        as_of: str | None = None,
        limit: int = 100,
        status_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"limit": limit}
        as_of_dt = _parse_dt(as_of)
        if as_of_dt is not None:
            kwargs["as_of"] = as_of_dt
        records = stele.memory.list(
            _build_scope(namespace),
            status_filter,
            **kwargs,
        )
        return {"records": [_to_jsonable(r) for r in records]}

    @guard
    def memory_update(
        memory_id: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        record = stele.memory.update(memory_id, text=None, metadata=metadata)
        return {"record": _to_jsonable(record)}

    @guard
    def memory_delete(memory_id: str) -> dict[str, Any]:
        stele.memory.delete(memory_id)
        return {"ok": True}

    @guard
    def memory_retract(memory_id: str, reason: str) -> dict[str, Any]:
        record = stele.memory.retract(memory_id, reason=reason)
        return {"record": _to_jsonable(record)}

    @guard
    def extract_from_text(
        text: str,
        source_refs: list[str],
        namespace: str | None = None,
    ) -> dict[str, Any]:
        report = stele.extract.from_text(
            text=text,
            source_refs=source_refs,
            scope=_build_scope(namespace),
        )
        return {"report": _to_jsonable(report)}

    @guard
    def extract_from_messages(
        messages: list[dict[str, Any]],
        namespace: str | None = None,
    ) -> dict[str, Any]:
        report = stele.extract.from_messages(
            messages=messages,
            scope=_build_scope(namespace),
        )
        return {"report": _to_jsonable(report)}

    @guard
    def extract_from_artifact(
        ref: str, namespace: str | None = None
    ) -> dict[str, Any]:
        # Pass the full stele:// ref through; the facade parses it and
        # resolves the correct namespace. (Previously we stripped to a bare
        # artifact_id, which made the facade fall back to namespace="default"
        # and silently miss non-default artifacts.)
        report = stele.extract.from_artifact(
            artifact_id=ref,
            scope=_build_scope(namespace),
        )
        return {"report": _to_jsonable(report)}

    @guard
    def recall(
        query: str,
        namespace: str | None = None,
        strategy: str | None = None,
        as_of: str | None = None,
        version_filter: str | None = None,
        retracted_behavior: str | None = None,
        max_memory_hits: int | None = None,
        max_artifact_hits: int | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "query": query,
            "scope": _build_scope(namespace),
        }
        if strategy is not None:
            kwargs["strategy"] = strategy
        if as_of is not None:
            kwargs["as_of"] = _parse_dt(as_of)
        if version_filter is not None:
            kwargs["version_filter"] = version_filter
        if retracted_behavior is not None:
            kwargs["retracted_behavior"] = retracted_behavior
        if max_memory_hits is not None:
            kwargs["max_memory_hits"] = max_memory_hits
        if max_artifact_hits is not None:
            kwargs["max_artifact_hits"] = max_artifact_hits
        response = stele.recall(**kwargs)
        return {"response": _to_jsonable(response)}

    @guard
    def stash_tool_result(
        tool_name: str,
        raw_output: str,
        namespace: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from stele.interception.wrapper import stash_tool_result as _stash

        result = _stash(
            raw_output,
            stash=stele,
            namespace=namespace,
            tool_name=tool_name,
            metadata=metadata,
        )
        return {"result": _to_jsonable(result)}

    by_name: dict[str, HandlerFn] = {
        "stele_store": store,
        "stele_fetch": fetch,
        "stele_search": search,
        "stele_query": query,
        "stele_list": list_,
        "stele_delete": delete,
        "stele_memory_add": memory_add,
        "stele_memory_get": memory_get,
        "stele_memory_search": memory_search,
        "stele_memory_list": memory_list,
        "stele_memory_update": memory_update,
        "stele_memory_delete": memory_delete,
        "stele_memory_retract": memory_retract,
        "stele_extract_from_text": extract_from_text,
        "stele_extract_from_messages": extract_from_messages,
        "stele_extract_from_artifact": extract_from_artifact,
        "stele_recall": recall,
        "stele_stash_tool_result": stash_tool_result,
    }
    return [replace(t, handler=by_name[t.name]) for t in TOOLS]
