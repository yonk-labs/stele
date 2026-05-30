"""Hybrid retrieval facade — score fusion only (SC-013, SC-022).

Merges the chunk store's keyword + vector hits via Reciprocal Rank Fusion
(default) or weighted sum. Degrades-with-flag: if one path raises, returns
the surviving path's hits tagged ``metadata['hybrid_degraded']=True``; if
both raise, returns ``[]``. No reranking (out of scope). No chunkshop import.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from stele.core.artifact import SearchHit

if TYPE_CHECKING:
    from stele.storage.chunk_store.base import ChunkStore

_DEFAULT_WEIGHTS = {"keyword": 0.5, "vector": 0.5}


_SearchFn = Callable[..., list[SearchHit]]


def _safe(
    call: _SearchFn, query: str, limit: int, reference: str | None
) -> list[SearchHit] | None:
    """Run a search path; ``None`` signals the path raised (degrade)."""
    try:
        return call(query, limit=limit, reference=reference)
    except Exception:  # noqa: BLE001 - degrade-with-flag is the contract
        return None


def _key(hit: SearchHit) -> tuple[str, str | None]:
    return (hit.artifact_id, hit.chunk_id)


def hybrid_search(
    chunk_store: ChunkStore,
    query: str,
    *,
    limit: int,
    reference: str | None = None,
    method: Literal["rrf", "weighted_sum"] = "rrf",
    weights: dict[str, float] | None = None,
    rrf_k: int = 60,
) -> list[SearchHit]:
    over = max(1, limit) * 2
    kw = _safe(chunk_store.keyword_search, query, over, reference)
    vec = _safe(chunk_store.vector_search, query, over, reference)

    if kw is None and vec is None:
        return []
    degraded = kw is None or vec is None
    sources = [
        name
        for name, hits in (("keyword", kw), ("vector", vec))
        if hits is not None
    ]
    kw = kw or []
    vec = vec or []

    # Representative hit per chunk: vector carries the full chunk text while the
    # keyword path only carries a ~500-char snippet, so insert vector first and
    # let setdefault keep it — a chunk matched by both must surface full text.
    rep: dict[tuple[str, str | None], SearchHit] = {}
    for hit in [*vec, *kw]:
        rep.setdefault(_key(hit), hit)

    fused: dict[tuple[str, str | None], float] = {}
    if method == "weighted_sum":
        w = weights or _DEFAULT_WEIGHTS
        for name, hits in (("keyword", kw), ("vector", vec)):
            top = max((h.score for h in hits), default=0.0) or 1.0
            for h in hits:
                fused[_key(h)] = fused.get(_key(h), 0.0) + w.get(name, 0.0) * (
                    h.score / top
                )
    else:  # rrf
        for hits in (kw, vec):
            for rank, h in enumerate(hits, start=1):
                fused[_key(h)] = fused.get(_key(h), 0.0) + 1.0 / (rrf_k + rank)

    merged: list[SearchHit] = []
    for key, score in fused.items():
        base = rep[key]
        meta = dict(base.metadata)
        meta["sources"] = sources
        if degraded:
            meta["hybrid_degraded"] = True
        merged.append(
            base.model_copy(
                update={
                    "score": score,
                    "retrieval_mode": "hybrid",
                    "metadata": meta,
                }
            )
        )
    merged.sort(key=lambda h: h.score, reverse=True)
    return merged[:limit]
