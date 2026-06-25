"""Compaction for structured payloads (compact-return, tiers 1-2).

See docs/specs/compact-return.md. ``compact_json`` is the lossless tier-1
primitive (minify JSON containers, passthrough everything else).
``compact_or_digest`` is the summary policy: minified-if-it-fits (lossless),
else a bounded structural digest (lossy hint, recoverable via the stele:// ref).
Neither raises into the summary path: any failure yields the input or ``None``.
"""

from __future__ import annotations

import json
from typing import Any

_MAX_KEYS = 40
_NOTE = "(digest; fetch the stele:// ref for full content)"


def compact_json(text: str) -> str:
    """Return ``text`` with structural JSON whitespace stripped, losslessly.

    Applies only when ``text`` parses as a JSON object or array. Prose, scalars,
    and malformed JSON are returned unchanged.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return text
    if not isinstance(parsed, (dict, list)):
        # ponytail: top-level scalars carry no whitespace worth removing.
        return text
    return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)


def compact_or_digest(text: str, *, max_chars: int = 1200) -> str | None:
    """Best compact summary for a JSON container, or ``None`` if not one.

    Tier 1: if the losslessly-minified payload fits ``max_chars``, return it
    verbatim (no information loss). Tier 2: otherwise return a bounded structural
    digest (top-level keys/types, array lengths, a sample, and a fetch marker).
    Returns ``None`` for prose, scalars, and malformed JSON so the caller can
    fall back to its prose summarizer.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, (dict, list)):
        return None
    minified = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
    if len(minified) <= max_chars:
        return minified
    return _structural_digest(parsed, max_chars=max_chars)


def _type_label(value: Any) -> str:
    if isinstance(value, dict):
        return f"object({len(value)} keys)"
    if isinstance(value, list):
        return f"array[{len(value)}]"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    return "unknown"


def _schema_block(parsed: dict[str, Any] | list[Any]) -> str:
    lines: list[str] = []
    if isinstance(parsed, dict):
        lines.append(f"JSON object, {len(parsed)} keys:")
        for i, (key, value) in enumerate(parsed.items()):
            if i >= _MAX_KEYS:
                lines.append(f"  (+{len(parsed) - _MAX_KEYS} more keys)")
                break
            lines.append(f"  {key}: {_type_label(value)}")
    else:
        lines.append(f"JSON array, {len(parsed)} elements")
        if parsed and isinstance(parsed[0], dict):
            keys = list(parsed[0].keys())
            shown = ", ".join(str(k) for k in keys[:_MAX_KEYS])
            more = f" (+{len(keys) - _MAX_KEYS} more)" if len(keys) > _MAX_KEYS else ""
            lines.append(f"  element keys: {shown}{more}")
        elif parsed:
            lines.append(f"  element type: {_type_label(parsed[0])}")
    return "\n".join(lines)


def _structural_digest(parsed: dict[str, Any] | list[Any], *, max_chars: int) -> str:
    # Order matters: schema + fetch marker first (load-bearing), sample last, so
    # a tight budget trims the sample, never the marker that points to the truth.
    head = _schema_block(parsed) + "\n" + _NOTE
    parts = [head]
    remaining = max_chars - len(head) - 1
    if remaining > len("sample: ") + 8:
        sample_obj = parsed if isinstance(parsed, dict) else parsed[:1]
        sample = json.dumps(sample_obj, separators=(",", ":"), ensure_ascii=False)
        budget = remaining - len("sample: ")
        if len(sample) > budget:
            sample = sample[: max(0, budget - 3)].rstrip() + "..."
        parts.append("sample: " + sample)
    digest = "\n".join(parts)
    if len(digest) > max_chars:
        digest = digest[: max_chars - 3].rstrip() + "..."
    return digest
