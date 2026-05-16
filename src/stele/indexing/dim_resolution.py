"""Vector dim + similarity resolution cascade.

Order (highest priority first):

1. ``bakeoff_file``  — ``config.bakeoff_path`` set and loads cleanly.
2. ``auto_detected`` — probe ``store.embed("__stele_probe__")`` for the dim.
3. ``default``       — hard fallback: dim 384, cosine.

Returns a :class:`BakeoffSummary` whose ``embedder.dim`` is the resolved
vector dimension (synthetic embedder for the auto/default paths so the
resolved dim is always reachable; ``chunker`` is populated only for the
``bakeoff_file`` path).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stele.core.config import IndexingConfig
from stele.indexing.bakeoff import BakeoffEmbedder, BakeoffSummary, load_bakeoff_file

if TYPE_CHECKING:
    from stele.storage.chunk_store.base import ChunkStore

_PROBE = "__stele_probe__"
_DEFAULT_DIM = 384


def resolve_dim_and_similarity(
    config: IndexingConfig, *, store: ChunkStore | None
) -> BakeoffSummary:
    """Resolve the vector dim + similarity per the 3-path cascade."""
    if config.bakeoff_path:
        bakeoff = load_bakeoff_file(config.bakeoff_path)
        return BakeoffSummary(
            source="bakeoff_file",
            chunker=bakeoff.chunker,
            embedder=bakeoff.embedder,
            similarity=bakeoff.similarity,
            file_path=config.bakeoff_path,
        )

    if store is not None:
        try:
            dim = len(store.embed(_PROBE))
        except Exception:  # noqa: BLE001 - any probe failure -> hard default
            dim = 0
        if dim > 0:
            return BakeoffSummary(
                source="auto_detected",
                chunker=None,
                embedder=BakeoffEmbedder(name="auto-detected", dim=dim),
                similarity=config.similarity,
            )

    return BakeoffSummary(
        source="default",
        chunker=None,
        embedder=BakeoffEmbedder(name="default", dim=_DEFAULT_DIM),
        similarity="cosine",
    )
