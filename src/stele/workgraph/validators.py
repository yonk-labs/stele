"""WorkGraph validation — source-backed, no raw blobs, valid transitions.

Deterministic, no LLM. Wraps Stele's existing reference parser so a
WorkGraph ref is exactly a Stele ref.
"""

from __future__ import annotations

from collections.abc import Iterable

from stele.core.exceptions import ReferenceError, ValidationError
from stele.core.reference import parse_reference

# Raw tool output never lives in the graph; it is a Stele artifact and the
# node carries the ref. Human-readable fields stay compact.
RAW_CONTENT_MAX = 512

# Node lifecycle (spec §Validation Rules). Terminal states only leave via
# explicit supersession (handled by the store, not a transition).
_NODE_TERMINAL = {"done", "failed", "superseded", "abandoned"}
_NODE_ALLOWED: dict[str, set[str]] = {
    "pending": {"active", "blocked", "abandoned"},
    "active": {"done", "blocked", "failed", "abandoned"},
    "blocked": {"active", "abandoned"},
}


def validate_refs(refs: Iterable[str]) -> None:
    """Every ref must parse as a Stele reference."""
    for ref in refs:
        try:
            parse_reference(ref)
        except ReferenceError as exc:
            raise ValidationError(f"invalid WorkGraph ref {ref!r}: {exc}") from exc


def assert_no_raw_content(value: str, *, field: str = "value") -> None:
    """Reject raw blobs in human-readable fields."""
    if len(value) > RAW_CONTENT_MAX:
        raise ValidationError(
            f"{field} exceeds {RAW_CONTENT_MAX} chars ({len(value)}) — store "
            f"large content as a Stele artifact and reference it, not inline"
        )


def validate_status_transition(old: str, new: str) -> None:
    """Spec lifecycle. ``abandoned`` reachable from any non-terminal."""
    if old == new:
        return
    if old in _NODE_TERMINAL:
        raise ValidationError(
            f"{old!r} is terminal; transition to {new!r} requires explicit supersession"
        )
    allowed = _NODE_ALLOWED.get(old)
    if allowed is None or new not in allowed:
        raise ValidationError(f"invalid status transition {old!r} -> {new!r}")
