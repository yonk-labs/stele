"""Shared metadata/time filter predicate for retrieval backends.

`query(filters=...)` historically honored only `session_id`. This widens the
contract so the same dict can express time-range and metadata constraints —
the filter half of the filter-then-rank pattern in
``docs/session-memory-metadata-design.md``.

Supported filter keys (all optional, AND-combined):

    session_id                     eq on record.session_id
    created_after / created_before inclusive range on record.created_at
    metadata.<key>                 eq on record.metadata[key]
    metadata.<key>__in             membership (value is a list/tuple/set)
    metadata.<key>__gte / __lte    range on record.metadata[key]
                                   (works for ISO date strings + numbers)

Backends that can push these into SQL should; this Python predicate is the
reference semantics and the implementation for in-memory retrieval.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any, Protocol


class _Record(Protocol):
    # Read-only members so both frozen dataclasses (FilterableRow) and Pydantic
    # models (ArtifactRecord) satisfy the protocol.
    @property
    def session_id(self) -> str | None: ...
    @property
    def created_at(self) -> dt.datetime: ...
    @property
    def metadata(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FilterableRow:
    """Minimal shim so SQL backends can reuse ``record_matches_filters`` by
    SELECTing ``session_id``, ``created_at``, ``metadata`` alongside the hit —
    no extra per-candidate fetch, one tested predicate across all backends."""

    session_id: str | None
    created_at: dt.datetime
    metadata: dict[str, Any]

    @classmethod
    def from_sql(
        cls,
        session_id: str | None,
        created_at: str | dt.datetime | None,
        metadata: str | dict[str, Any] | None,
    ) -> FilterableRow:
        if isinstance(created_at, str):
            ts = dt.datetime.fromisoformat(created_at)
        elif isinstance(created_at, dt.datetime):
            ts = created_at
        else:
            ts = dt.datetime.min
        meta: dict[str, Any]
        if isinstance(metadata, str):
            meta = json.loads(metadata) if metadata else {}
        elif isinstance(metadata, dict):
            meta = metadata
        else:
            meta = {}
        return cls(session_id=session_id, created_at=ts, metadata=meta)


def _as_naive(value: dt.datetime) -> dt.datetime:
    """Drop tzinfo so naive (parser) and aware (stored UTC) datetimes compare."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def record_matches_filters(record: _Record, filters: dict[str, Any] | None) -> bool:
    """Return True if `record` satisfies every key in `filters`."""
    if not filters:
        return True
    for key, want in filters.items():
        if want is None:
            continue
        if key == "session_id":
            if record.session_id != want:
                return False
        elif key == "created_after":
            if _as_naive(record.created_at) < _as_naive(want):
                return False
        elif key == "created_before":
            if _as_naive(record.created_at) > _as_naive(want):
                return False
        elif key.startswith("metadata.") and not _metadata_match(
            record.metadata, key[len("metadata."):], want
        ):
            return False
        # Unknown keys are ignored (forward-compatible).
    return True


def _metadata_match(meta: dict[str, Any], spec: str, want: Any) -> bool:
    if spec.endswith("__in"):
        return meta.get(spec[:-4]) in want
    if spec.endswith("__gte"):
        got = meta.get(spec[:-5])
        return got is not None and bool(got >= want)
    if spec.endswith("__lte"):
        got = meta.get(spec[:-5])
        return got is not None and bool(got <= want)
    return bool(meta.get(spec) == want)
