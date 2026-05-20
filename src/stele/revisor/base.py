"""Revisor Protocol + package-owned hit type + inert default.

The Revisor projects Stele memory/artifact evidence into a living-knowledge
graph. It is INTERNAL: no pg-raggraph-native object ever crosses this
boundary (mirrors the Phase-4 chunkshop adapter rule). The Protocol surface
is SYNC; any async bridge lives only in a concrete impl.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

RetractedBehavior = Literal["hide", "flag", "surface_both"]
SupersessionBehavior = Literal["hide", "prefer_new", "surface_both"]


class GraphHit(BaseModel):
    """A living-knowledge hit. ``stele_ref`` ALWAYS recovers the source."""

    model_config = ConfigDict(frozen=True)

    stele_ref: str
    text: str
    score: float
    chunk_id: str | None = None
    retracted: bool = False
    version_label: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    superseded_by_id: int | None = None


class Revisor(Protocol):
    active: bool

    def ingest_evidence(
        self,
        *,
        stele_ref: str,
        text: str,
        namespace: str,
        effective_from: datetime | None = None,
        session_id: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None: ...

    def supersede(
        self, *, old_ref: str, new_ref: str, reason: str | None = None
    ) -> int: ...

    def retract(
        self, *, stele_ref: str, reason: str = "", retracted_at: datetime | None = None
    ) -> int: ...

    def purge_namespace(self, namespace: str) -> int:
        """Hard-delete every projected evidence row (documents, facts,
        relationships, entities, document_versions) in ``namespace``.
        Returns a count representative of the deletion (typically the
        document count). Used by :meth:`Stele.purge_namespace` (#8b)."""
        ...

    def search_current(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        retracted_behavior: RetractedBehavior,
        supersession_behavior: SupersessionBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]: ...

    def search_as_of(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        as_of: datetime,
        retracted_behavior: RetractedBehavior,
        supersession_behavior: SupersessionBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]: ...

    def close(self) -> None: ...


class NoOpRevisor:
    """Default. Memory still works; the graph projection is simply absent."""

    active = False

    def ingest_evidence(
        self,
        *,
        stele_ref: str,
        text: str,
        namespace: str,
        effective_from: datetime | None = None,
        session_id: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        return None

    def supersede(
        self, *, old_ref: str, new_ref: str, reason: str | None = None
    ) -> int:
        return 0

    def retract(
        self, *, stele_ref: str, reason: str = "", retracted_at: datetime | None = None
    ) -> int:
        return 0

    def purge_namespace(self, namespace: str) -> int:
        return 0

    def search_current(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        retracted_behavior: RetractedBehavior,
        supersession_behavior: SupersessionBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        return []

    def search_as_of(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        as_of: datetime,
        retracted_behavior: RetractedBehavior,
        supersession_behavior: SupersessionBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        return []

    def close(self) -> None:
        return None
