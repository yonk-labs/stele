"""Tool-result serialization and content detection."""

from __future__ import annotations

import json
from typing import Any

from stele.core.types import ContentType


def serialize_tool_result(result: Any) -> tuple[str, ContentType]:
    if isinstance(result, str):
        return result, _detect_string_type(result)
    if isinstance(result, bytes):
        return result.decode("utf-8", errors="replace"), "blob"
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2, sort_keys=True, default=str), "json"
    return str(result), "text"


def _detect_string_type(value: str) -> ContentType:
    stripped = value.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(value)
            return "json"
        except json.JSONDecodeError:
            pass
    if "\n+++" in value or "\n---" in value or stripped.startswith("diff --git"):
        return "code_diff"
    if "Traceback " in value or " ERROR " in value or stripped.startswith("[ERROR]"):
        return "log"
    if stripped.startswith("<!DOCTYPE html") or stripped.startswith("<html"):
        return "html"
    return "text"

