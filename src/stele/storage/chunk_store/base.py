"""ChunkStore Protocol — write + read + vector + embed surface."""

from __future__ import annotations

from typing import Literal, Protocol

from stele.core.artifact import ArtifactRecord, SearchHit


class ChunkStore(Protocol):
    name: Literal["memory", "sqlite", "postgres", "mariadb", "clickhouse"]

    @property
    def dim(self) -> int: ...

    @property
    def similarity(self) -> Literal["cosine", "ip", "l2"]: ...

    def write(self, artifact: ArtifactRecord) -> int:
        """Chunk + embed + persist. Returns number of chunks written."""
        ...

    def delete(self, reference: str) -> None: ...

    def keyword_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]: ...

    def vector_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]: ...

    def embed(self, text: str) -> list[float]:
        """Probe embedder. Used for dim auto-detection + query embedding."""
        ...

    def close(self) -> None: ...
