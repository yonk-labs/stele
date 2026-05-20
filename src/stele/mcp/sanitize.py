"""Label sanitization for MCP-bound free-text fields.

Strips ANSI escapes, control chars, and clamps to a fixed max length to
neutralize prompt-injection payloads inside LLM-derived or
externally-sourced strings before they cross the MCP transport.
"""

from __future__ import annotations

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_LEN = 256


def sanitize_label(value: str) -> str:
    """Strip ANSI, control chars, and clamp to 256 chars."""
    if not value:
        return ""
    stripped = _ANSI_RE.sub("", value)
    stripped = _CTRL_RE.sub("", stripped)
    return stripped[:_MAX_LEN]
