"""In-process chunk store — numpy + dict; no chunkshop required."""

from __future__ import annotations

import hashlib
from typing import Literal

import numpy as np

from stele.core.artifact import ArtifactRecord, SearchHit
from stele.core.config import IndexingConfig
from stele.indexing.chunk_index import ChunkIndex, ChunkRecord
from stele.retrieval.rank import keyword_score, snippet_around


def _hash_embed(text: str, dim: int = 384) -> np.ndarray:
    """Deterministic hash embedder. Tokens -> bucketed +1 increments, L2-normalized."""
    vec = np.zeros(dim, dtype=np.float32)
    for token in text.lower().split():
        h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        bucket = h % dim
        vec[bucket] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


class InProcessChunkStore:
    name: Literal["memory"] = "memory"

    def __init__(self, config: IndexingConfig) -> None:
        self._config = config
        self._dim = config.vector_dim or 384
        self._sim: Literal["cosine", "ip", "l2"] = config.similarity
        self._chunks: dict[str, list[ChunkRecord]] = {}
        self._embeddings: dict[str, np.ndarray] = {}  # keyed by chunk_id
        # Reuse the existing ChunkIndex chunker logic.
        self._index = ChunkIndex(config)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def similarity(self) -> Literal["cosine", "ip", "l2"]:
        return self._sim

    def write(self, artifact: ArtifactRecord) -> int:
        n = self._index.index(artifact)
        chunks = self._index._chunks_by_ref.get(artifact.reference, [])
        self._chunks[artifact.reference] = chunks
        for chunk in chunks:
            self._embeddings[chunk.chunk_id] = _hash_embed(chunk.text, self._dim)
        return n

    def delete(self, reference: str) -> None:
        chunks = self._chunks.pop(reference, [])
        for chunk in chunks:
            self._embeddings.pop(chunk.chunk_id, None)
        self._index.delete(reference)

    def keyword_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for ref, chunks in self._chunks.items():
            if reference is not None and ref != reference:
                continue
            for chunk in chunks:
                score = keyword_score(query, chunk.text)
                if score <= 0:
                    continue
                hits.append(
                    SearchHit(
                        artifact_id=chunk.artifact_id,
                        reference=chunk.reference,
                        chunk_id=chunk.chunk_id,
                        text=snippet_around(chunk.text, query),
                        score=score,
                        retrieval_mode="keyword",
                        metadata=dict(chunk.metadata),
                    )
                )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def vector_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]:
        q_vec = _hash_embed(query, self._dim)
        candidates: list[tuple[ChunkRecord, float]] = []
        for ref, chunks in self._chunks.items():
            if reference is not None and ref != reference:
                continue
            for chunk in chunks:
                emb = self._embeddings.get(chunk.chunk_id)
                if emb is None:
                    continue
                score = float(np.dot(q_vec, emb))  # cosine, since both normalized
                if score > 0:
                    candidates.append((chunk, score))
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        top = candidates[:limit]
        if not top:
            return []
        max_score = max(s for _, s in top) or 1.0
        return [
            SearchHit(
                artifact_id=chunk.artifact_id,
                reference=chunk.reference,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                score=score / max_score,
                retrieval_mode="vector",
                metadata=dict(chunk.metadata),
            )
            for chunk, score in top
        ]

    def embed(self, text: str) -> list[float]:
        return [float(x) for x in _hash_embed(text, self._dim)]

    def close(self) -> None:
        self._chunks.clear()
        self._embeddings.clear()
