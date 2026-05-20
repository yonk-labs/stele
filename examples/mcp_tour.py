"""Runnable tour of every MCP tool stele exposes.

Calls each of the 18 tools in `bind_handlers(stele)` against an in-memory
Stele, prints the request and response. Useful as documentation, a smoke
test, and a starting point for new integrations.

Run:
    .venv/bin/python examples/mcp_tour.py

This does NOT use the MCP transport — it calls handlers directly. The
handler closures are the same code path the stdio server invokes; only the
JSON-RPC framing differs.
"""

from __future__ import annotations

import json
from typing import Any

from stele.core.stash import Stele
from stele.mcp.tools import bind_handlers


def _call(handlers: dict[str, Any], name: str, **kwargs: Any) -> Any:
    print(f"\n>>> {name}({', '.join(f'{k}={v!r}' for k, v in kwargs.items())[:100]})")
    result = handlers[name](**kwargs)
    print(json.dumps(result, default=str, indent=2)[:600])
    return result


def main() -> None:
    stele = Stele.from_config({"backend": {"type": "memory"}})
    handlers = {t.name: t.handler for t in bind_handlers(stele)}

    print("=== Artifact surface ===")
    stored = _call(
        handlers,
        "stele_store",
        payload="User prefers tabs over spaces.",
        content_type="text",
        namespace="tour",
    )
    ref = stored["ref"]

    second = _call(
        handlers,
        "stele_store",
        payload=(
            "Project decisions log:\n"
            "- 2026-05-01: chose Postgres 15 for prod\n"
            "- 2026-05-15: upgraded to Postgres 17"
        ),
        content_type="markdown",
        namespace="tour",
    )
    second_ref = second["ref"]

    _call(handlers, "stele_fetch", ref=ref)
    _call(handlers, "stele_search", ref=second_ref, query="Postgres")
    _call(handlers, "stele_query", query="postgres", namespace="tour")
    _call(handlers, "stele_list", namespace="tour")

    print("\n=== Memory surface ===")
    added = _call(
        handlers,
        "stele_memory_add",
        text="Project uses Postgres 15",
        source_refs=[second_ref],
        kind="fact",
        namespace="tour",
    )
    mem_id_old = added["memory_id"]

    _call(handlers, "stele_memory_get", memory_id=mem_id_old)

    # Supersede with the newer version
    superseded = _call(
        handlers,
        "stele_memory_add",
        text="Project uses Postgres 17",
        source_refs=[second_ref],
        kind="fact",
        namespace="tour",
        supersedes=[mem_id_old],
    )
    mem_id_new = superseded["memory_id"]

    _call(handlers, "stele_memory_search", query="Postgres", namespace="tour")
    _call(handlers, "stele_memory_list", namespace="tour")
    _call(
        handlers,
        "stele_memory_update",
        memory_id=mem_id_new,
        metadata={"reviewed_by": "tour"},
    )

    print("\n=== Extraction surface ===")
    _call(
        handlers,
        "stele_extract_from_text",
        text=(
            "Decision: we will use Postgres 17 going forward. "
            "Owner: infra team."
        ),
        source_refs=[second_ref],
        namespace="tour",
    )
    _call(
        handlers,
        "stele_extract_from_messages",
        messages=[
            {"role": "user", "content": "What database do we use?"},
            {"role": "assistant", "content": "We use Postgres 17 in production."},
        ],
        namespace="tour",
    )
    _call(handlers, "stele_extract_from_artifact", ref=second_ref, namespace="tour")

    print("\n=== Recall ===")
    _call(
        handlers,
        "stele_recall",
        query="What Postgres version do we use?",
        namespace="tour",
        strategy="memory_search",
    )

    print("\n=== Interception ===")
    _call(
        handlers,
        "stele_stash_tool_result",
        tool_name="Bash",
        raw_output="x" * 8192,  # comfortably over the 4096-byte threshold
        namespace="tour",
    )

    print("\n=== Retract + cleanup ===")
    _call(
        handlers,
        "stele_memory_retract",
        memory_id=mem_id_new,
        reason="example complete",
    )
    _call(handlers, "stele_memory_delete", memory_id=mem_id_old)
    _call(handlers, "stele_delete", ref=ref)
    _call(handlers, "stele_delete", ref=second_ref)

    print("\nTour complete. Every tool exercised.")


if __name__ == "__main__":
    main()
