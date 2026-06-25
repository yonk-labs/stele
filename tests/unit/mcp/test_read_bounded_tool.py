"""MCP round-trip for stele_read_bounded (CodeGraph merge, slice D)."""

from __future__ import annotations

from typing import Any

from stele import Stele
from stele.mcp.tools import bind_handlers

SRC = "def helper(n):\n    return n + 1\n\n\ndef main(x):\n    return helper(x)\n"


def _stele() -> Stele:
    return Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"raw_fetch_enabled": True}}
    )


def _handler(s: Stele, name: str) -> Any:
    return {t.name: t.handler for t in bind_handlers(s) if t.handler}[name]


def test_read_bounded_tool_registered() -> None:
    assert "stele_read_bounded" in {t.name for t in bind_handlers(_stele())}


def test_read_bounded_tool_symbol() -> None:
    out = _handler(_stele(), "stele_read_bounded")(source=SRC, want="main")
    assert "def main(x):" in out["view"]
    assert "def helper(n):" in out["view"]  # dependency resolved


def test_read_bounded_tool_line_range() -> None:
    out = _handler(_stele(), "stele_read_bounded")(source=SRC, want="1-2")
    assert "def helper(n):" in out["view"]  # "1-2" parsed to a line range
