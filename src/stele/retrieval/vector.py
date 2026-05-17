"""Backend-agnostic vector retrieval facade (SC-012).

Thin: the ``ChunkStore`` already owns query embedding + vector search +
``SearchHit`` hydration. This module is the retrieval-layer entry point so
``stash``/recall never touch a chunk store (and chunkshop never leaks into
``retrieval/`` — see DC-001).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stele.core.artifact import SearchHit

if TYPE_CHECKING:
    from stele.storage.chunk_store.base import ChunkStore


def vector_search(
    chunk_store: ChunkStore,
    query: str,
    *,
    limit: int,
    reference: str | None = None,
) -> list[SearchHit]:
    """Top-K vector hits (``retrieval_mode='vector'``)."""
    return chunk_store.vector_search(query, limit=limit, reference=reference)
