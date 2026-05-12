"""Replacement payload formatting."""

from stele.core.artifact import StoredResult


def build_replacement_payload(result: StoredResult, *, max_chars: int = 1800) -> str:
    payload = (
        "[stele]\n"
        f"reference: {result.reference}\n"
        f"content_type: {result.content_type}\n"
        f"bytes: {result.byte_size}\n"
        f"estimated_tokens: {result.token_estimate}\n"
        "summary:\n"
        f"{result.summary}\n\n"
        "Available actions:\n"
        "- fetch exact content by reference if needed\n"
        "- search this artifact by reference for targeted details\n"
        f"- query namespace \"{result.namespace}\" for related stored context\n"
        "[/stele]"
    )
    if len(payload) <= max_chars:
        return payload
    return payload[: max_chars - 3].rstrip() + "..."

