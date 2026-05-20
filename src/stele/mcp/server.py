"""Stdio MCP server bootstrap for stele.

Loads config (walk-up + user-global fallback), instantiates a single Stele,
binds tool handlers, and exposes them over stdio.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from stele.core.stash import Stele
from stele.mcp.config import config_path, load_raw_config
from stele.mcp.sanitize import sanitize_label
from stele.mcp.tools import ToolSpec, bind_handlers


def _build_stele() -> Stele:
    cfg = config_path()
    if cfg is None:
        return Stele.from_config({"backend": {"type": "memory"}})
    raw = load_raw_config(cfg)
    return Stele.from_config(raw)


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_label(value)
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    return value


async def _serve() -> None:
    stele = _build_stele()
    tools: list[ToolSpec] = bind_handlers(stele)
    by_name = {t.name: t for t in tools}

    server: Server[Any, Any] = Server("stele")

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
            )
            for t in tools
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[TextContent]:
        spec = by_name.get(name)
        if spec is None or spec.handler is None:
            payload: Any = {
                "error": {
                    "code": "VALIDATION",
                    "message": f"unknown tool {name!r}",
                    "context": {},
                }
            }
        else:
            payload = spec.handler(**(arguments or {}))
            payload = _sanitize(payload)
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve())


if __name__ == "__main__":
    main()
