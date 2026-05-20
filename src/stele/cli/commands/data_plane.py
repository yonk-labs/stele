"""Shared engine for data-plane CLI commands.

Every data-plane CLI command builds kwargs, calls a bound MCP handler,
and prints JSON. One code path; the CLI cannot drift from the MCP.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from stele.core.stash import Stele
from stele.mcp.config import config_path, load_raw_config
from stele.mcp.tools import HandlerFn, bind_handlers

_HANDLERS: dict[str, HandlerFn] | None = None


def _build_handlers() -> dict[str, HandlerFn]:
    """Build (and cache) MCP handlers bound to a single Stele instance.

    Cached so a single CLI invocation reuses one Stele; tests that change
    config between invocations should call ``reset_handlers()``.
    """
    global _HANDLERS
    if _HANDLERS is None:
        cfg = config_path()
        raw: dict[str, Any] = (
            load_raw_config(cfg) if cfg else {"backend": {"type": "memory"}}
        )
        stele = Stele.from_config(raw)
        _HANDLERS = {t.name: t.handler for t in bind_handlers(stele) if t.handler}
    return _HANDLERS


def reset_handlers() -> None:
    """Drop the cached handlers; the next invoke() rebuilds them.

    Used by tests that switch config between CLI calls in the same process.
    """
    global _HANDLERS
    _HANDLERS = None


def read_stdin_if_dash(value: str | None) -> str | None:
    """Return stdin contents when value is '-', else value unchanged."""
    if value == "-":
        return sys.stdin.read()
    return value


def invoke(tool_name: str, kwargs: dict[str, Any], *, pretty: bool = False) -> int:
    """Run a bound MCP handler and write its JSON result to stdout."""
    handlers = _build_handlers()
    handler = handlers.get(tool_name)
    if handler is None:
        result: dict[str, Any] = {
            "error": {
                "code": "VALIDATION",
                "message": f"unknown tool {tool_name!r}",
                "context": {},
            }
        }
    else:
        result = handler(**kwargs)
    if pretty:
        sys.stdout.write(json.dumps(result, indent=2, default=str) + "\n")
    else:
        sys.stdout.write(json.dumps(result, default=str) + "\n")
    return 1 if isinstance(result, dict) and "error" in result else 0
