"""Lossless compaction for structured payloads (tier 1 of compact-return).

See docs/specs/compact-return.md. Only top-level JSON containers (dict/list)
are minified; everything else passes through unchanged. Never raises into the
summary path: any failure returns the input verbatim.
"""

from __future__ import annotations

import json


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
