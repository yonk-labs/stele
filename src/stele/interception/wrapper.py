"""Plain Python structural interception wrapper."""

from __future__ import annotations

from typing import Any

from stele.core.stash import Stele
from stele.interception.detector import serialize_tool_result
from stele.interception.response import build_replacement_payload
from stele.interception.thresholds import should_intercept


def stash_tool_result(
    result: Any,
    *,
    stash: Stele,
    namespace: str = "default",
    session_id: str | None = None,
    tool_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    always_store: bool = False,
) -> Any:
    text, content_type = serialize_tool_result(result)
    if not should_intercept(text, stash.config.interception, always_store=always_store):
        return result
    merged_metadata = dict(metadata or {})
    if tool_name:
        merged_metadata["tool_name"] = tool_name
    stored = stash.store(
        text,
        namespace=namespace,
        session_id=session_id,
        content_type=content_type,
        metadata=merged_metadata,
    )
    return build_replacement_payload(
        stored,
        max_chars=stash.config.interception.max_replacement_chars,
    )
