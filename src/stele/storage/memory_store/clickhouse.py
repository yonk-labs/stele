"""ClickHouse memory stub — memory support lands in a later slice."""

from __future__ import annotations

from typing import Any

from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope, ScoredMemoryHit

_MSG = (
    "memory support on the ClickHouse backend is not yet implemented; "
    "use the SQLite or Postgres backend, or wait for a later phase"
)


class ClickHouseMemoryStore:
    def initialize(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        if name in {
            "add", "search", "list", "get",
            "update_metadata", "soft_delete", "set_retracted",
            "find_duplicate", "close",
        }:
            def _raise(*_args: object, **_kwargs: object) -> None:
                raise CapabilityError(_MSG)

            return _raise
        raise AttributeError(name)

    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        del query, scope, limit, source_ref_filter
        raise CapabilityError(
            "memory.search_with_score is not implemented for the ClickHouse backend"
        )
