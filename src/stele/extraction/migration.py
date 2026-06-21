"""Additive backfill: give pre-registry (0.6.3) memories a subject_id without
rewriting immutable memory text. Idempotent: rows that already have subject_id are
skipped. Ambiguous legacy collisions are left as integrity warnings, never merged."""
from __future__ import annotations

import logging

from stele.core.memory_record import MemoryScope
from stele.extraction.identity import canonical_subject

_log = logging.getLogger(__name__)


def backfill_subject_ids(
    memory: object,
    scope: MemoryScope,
    *,
    default_subject_type: str = "entity",
) -> int:
    """Backfill ``subject_id`` + ``subject_type`` onto pre-registry memories.

    For each memory (active + superseded) that has ``canonical_subject`` and
    ``aspect`` metadata but no ``subject_id``, writes::

        subject_id   = "{default_subject_type}:{canonical_subject(label)}"
        subject_type = default_subject_type

    via metadata update only (memory text is never touched). Idempotent: rows
    that already carry ``subject_id`` are skipped, so re-running is a no-op.

    Returns the count of rows updated.
    """
    rows = memory.list(scope, status_filter=["active", "superseded"], limit=10_000)  # type: ignore[attr-defined]
    if len(rows) == 10_000:
        _log.warning(
            "backfill_subject_ids hit 10 000-record ceiling for scope=%s; "
            "records beyond the limit were not backfilled -- re-run with a filtered scope",
            scope,
        )
    n = 0
    for r in rows:
        meta = dict(r.metadata or {})
        if meta.get("subject_id") or not meta.get("canonical_subject") or not meta.get("aspect"):
            continue
        norm = canonical_subject(str(meta["canonical_subject"]))
        meta["subject_id"] = f"{default_subject_type}:{norm}"
        meta["subject_type"] = default_subject_type
        memory.update_metadata(r.id, meta)  # type: ignore[attr-defined]
        _log.debug("backfill: %s -> subject_id=%s", r.id, meta["subject_id"])
        n += 1
    return n
