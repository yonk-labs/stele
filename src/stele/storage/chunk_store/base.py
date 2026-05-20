"""ChunkStore Protocol — write + read + vector + embed surface."""

from __future__ import annotations

from typing import Literal, Protocol

from stele.core.artifact import ArtifactRecord, SearchHit


class ChunkStore(Protocol):
    # Read-only property (like ``dim``/``similarity`` below) so it is
    # covariant under Protocol matching: concrete stores narrow it to a
    # backend Literal class attr. A mutable data attribute here would be
    # invariant and reject the narrowed impls.
    @property
    def name(self) -> str: ...

    @property
    def dim(self) -> int: ...

    @property
    def similarity(self) -> Literal["cosine", "ip", "l2"]: ...

    def write(self, artifact: ArtifactRecord) -> int:
        """Chunk + embed + persist. Returns number of chunks written."""
        ...

    def delete(self, reference: str) -> None: ...

    def delete_namespace(self, namespace: str) -> int:
        """Drop every chunk whose source artifact lives in ``namespace``.
        Returns the count of artifact references whose chunks were removed.

        Used by :meth:`Stele.purge_namespace` (#8b) to ensure namespace
        deletion reaches the chunk index, not just the artifact store."""
        ...

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
