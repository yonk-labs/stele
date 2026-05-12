"""Retrieval backend protocol."""

from typing import Protocol

from stele.core.artifact import SearchHit
from stele.core.capabilities import RetrievalCapabilities
from stele.core.reference import Reference
from stele.core.types import RetrievalMode


class RetrievalBackend(Protocol):
    def search_artifact(
        self,
        reference: Reference,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | None = None,
        filters: dict[str, object] | None = None,
    ) -> list[SearchHit]: ...

    def query_namespace(
        self,
        namespace: str,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | None = None,
        filters: dict[str, object] | None = None,
    ) -> list[SearchHit]: ...

    def capabilities(self) -> RetrievalCapabilities: ...

