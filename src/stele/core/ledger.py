"""Deterministic per-mode schema for Context & Protocol Ledger records. No I/O,
no LLM: the typed write API is the authority, the LLM only drafts. See
docs/specs/context-protocol-ledger-plan.md."""
from __future__ import annotations

from stele.core.exceptions import ValidationError

# mode -> required field names (beyond text/source_refs/scope, which Memory.add enforces)
LEDGER_REQUIRED: dict[str, tuple[str, ...]] = {
    "decision": ("rationale",),
    "dead_end": ("failure_reason",),
    "procedure": (),
    "constraint": (),
    "completion": (),
    "verification_method": ("method",),
    "observation": ("context",),  # a fact must name the process it belongs to,
                                  # so it is governance evidence, never free-floating truth
}


def validate_ledger_record(mode: str, fields: dict[str, object]) -> None:
    required = LEDGER_REQUIRED.get(mode)
    if required is None:
        return  # not a ledger mode
    missing = [f for f in required if not str(fields.get(f, "")).strip()]
    if missing:
        raise ValidationError(
            f"ledger mode {mode!r} requires non-empty fields: {missing}"
        )
