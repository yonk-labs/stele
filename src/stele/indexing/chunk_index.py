"""Process-local chunk index used by the Chunkshop adapter path."""

from __future__ import annotations

from dataclasses import dataclass

from stele.core.artifact import ArtifactRecord, SearchHit
from stele.core.config import IndexingConfig
from stele.retrieval.rank import keyword_score, snippet_around


@dataclass(frozen=True)
class ChunkRecord:
    artifact_id: str
    reference: str
    namespace: str
    session_id: str | None
    chunk_id: str
    text: str
    ordinal: int
    metadata: dict[str, object]


class ChunkIndex:
    def __init__(self, config: IndexingConfig) -> None:
        self.config = config
        self._chunks_by_ref: dict[str, list[ChunkRecord]] = {}

    def index(self, artifact: ArtifactRecord) -> int:
        text = artifact.content_as_text()
        chunks = [
            ChunkRecord(
                artifact_id=artifact.artifact_id,
                reference=artifact.reference,
                namespace=artifact.namespace,
                session_id=artifact.session_id,
                chunk_id=f"{artifact.artifact_id}:{ordinal}",
                text=chunk_text,
                ordinal=ordinal,
                metadata={
                    # artifact metadata first so reserved keys below win.
                    **(artifact.metadata or {}),
                    "namespace": artifact.namespace,
                    "session_id": artifact.session_id,
                    "created_at": artifact.created_at.isoformat(),
                    "chunker": self.config.chunker,
                },
            )
            for ordinal, chunk_text in enumerate(_chunk_text(text, self.config))
        ]
        self._chunks_by_ref[artifact.reference] = chunks
        return len(chunks)

    def delete(self, reference: str) -> None:
        self._chunks_by_ref.pop(reference, None)

    def search_reference(self, reference: str, query: str, *, limit: int) -> list[SearchHit]:
        chunks = self._chunks_by_ref.get(reference, [])
        return _rank_chunks(chunks, query, limit=limit)

    def query_namespace(
        self,
        namespace: str,
        query: str,
        *,
        limit: int,
        session_id: str | None = None,
    ) -> list[SearchHit]:
        chunks = [
            chunk
            for ref_chunks in self._chunks_by_ref.values()
            for chunk in ref_chunks
            if chunk.namespace == namespace
            and (session_id is None or chunk.session_id == session_id)
        ]
        return _rank_chunks(chunks, query, limit=limit)


def _rank_chunks(chunks: list[ChunkRecord], query: str, *, limit: int) -> list[SearchHit]:
    hits: list[SearchHit] = []
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
                retrieval_mode="hybrid",
                metadata=dict(chunk.metadata),
            )
        )
    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


def _chunk_text(text: str, config: IndexingConfig) -> list[str]:
    chunkshop_chunks = _try_chunkshop_chunks(text, config)
    if chunkshop_chunks is not None:
        return chunkshop_chunks
    words = text.split()
    if not words:
        return [text]
    window = max(1, config.chunk_words)
    overlap = min(max(0, config.chunk_overlap_words), window - 1)
    step = max(1, window - overlap)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + window]))
        if start + window >= len(words):
            break
    return chunks


def _try_chunkshop_chunks(text: str, config: IndexingConfig) -> list[str] | None:
    try:
        from chunkshop.chunkers import load_chunker
        from chunkshop.config import FixedOverlapChunker
        from chunkshop.sources.base import Document
    except ModuleNotFoundError:
        return None

    chunker = load_chunker(
        FixedOverlapChunker(
            type="fixed_overlap",
            window_words=config.chunk_words,
            step_words=max(1, config.chunk_words - config.chunk_overlap_words),
        )
    )
    chunks = chunker.chunk(Document(id="artifact", content=text, metadata={}))
    return [chunk.original_content for chunk in chunks]
