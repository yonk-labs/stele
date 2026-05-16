"""Shared base for chunkshop-backed chunk stores (sqlite/pg/mariadb/clickhouse).

chunkshop is **vector-only** and ``query_top_k`` returns bare
``(doc_id, seq_num, distance)`` tuples — no text, no metadata. So this base:

* owns one Embedder + one chunker + one Sink, all synthesized internally
  from Stele's ``IndexingConfig`` (users never see chunkshop config);
* uses chunkshop 0.4.3 ``TargetConfig(dsn=...)`` — never mutates os.environ;
* retains ``{chunk_id: (text, reference, metadata)}`` locally at write so
  vector hits can be hydrated into ``SearchHit`` (no chunkshop object leaks);
* does keyword search Stele-locally over the retained text;
* asserts text is already PII-scrubbed at the write boundary (fail-loud).

Per-backend subclasses only set ``name`` + ``_target_type`` and translate
their documented ctor param into ``dsn``.
"""

from __future__ import annotations

from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, Literal

from stele.core.artifact import ArtifactRecord, SearchHit
from stele.core.config import IndexingConfig
from stele.core.exceptions import BackendError, OptionalDependencyError
from stele.indexing.chunkshop_adapter import score_from_distance, stele_chunk_id
from stele.pii.regex import DEFAULT_PATTERNS
from stele.retrieval.rank import keyword_score, snippet_around

if TYPE_CHECKING:
    import numpy as np

_DEFAULT_DIM = 384
_PIP_HINT = "pip install 'stele-core[chunkshop]'"


def _assert_no_pii(text: str) -> None:
    """Defensive write-boundary check. Text must already be scrubbed."""
    for pattern in DEFAULT_PATTERNS:
        if pattern.pattern.search(text):
            raise BackendError(
                f"unscrubbed PII ({pattern.entity_type}) reached the chunk "
                f"store write boundary — text must be scrubbed upstream"
            )


class ChunkshopChunkStore:
    """Base class. Subclasses set ``name`` and ``_target_type``."""

    name: str = "chunkshop"
    _target_type: Literal["sqlite", "postgres", "mariadb", "clickhouse"]

    def __init__(
        self, config: IndexingConfig, *, dsn: str, table: str = "chunks"
    ) -> None:
        if find_spec("chunkshop") is None:  # pragma: no cover - env-dependent
            raise OptionalDependencyError(
                f"chunkshop required for the {self._target_type} chunk store; "
                f"{_PIP_HINT}"
            )
        from chunkshop.chunkers import load_chunker
        from chunkshop.config import (
            FastembedEmbedder,
            FixedOverlapChunker,
            TargetConfig,
        )
        from chunkshop.embedders import load_embedder
        from chunkshop.sinks import load_sink

        self._config = config
        self._sim: Literal["cosine", "ip", "l2"] = config.similarity
        dim = config.vector_dim or _DEFAULT_DIM
        self._embedder = load_embedder(
            FastembedEmbedder(
                type="fastembed",
                model_name="sentence-transformers/all-MiniLM-L6-v2",
                dim=dim,
            )
        )
        self._chunker = load_chunker(
            FixedOverlapChunker(
                type="fixed_overlap",
                window_words=config.chunk_words,
                step_words=max(1, config.chunk_words - config.chunk_overlap_words),
            )
        )
        target = TargetConfig(
            type=self._target_type,
            dsn=dsn,
            database="stele",
            table=table,
            hnsw=True,
            mode="overwrite",
        )
        self._sink = load_sink(target, self._embedder.dim)
        self._sink.create_table()
        # chunk_id -> (text, reference, metadata)
        self._chunks: dict[str, tuple[str, str, dict[str, Any]]] = {}
        # reference -> set of chunkshop doc_ids (artifact_ids)
        self._ref_docs: dict[str, set[str]] = {}

    @property
    def dim(self) -> int:
        return int(self._embedder.dim)

    @property
    def similarity(self) -> Literal["cosine", "ip", "l2"]:
        return self._sim

    def write(self, artifact: ArtifactRecord) -> int:
        from chunkshop.sources.base import Document

        text = artifact.content_as_text()
        chunks = self._chunker.chunk(
            Document(id=artifact.artifact_id, content=text, metadata={})
        )
        if not chunks:
            return 0
        for chunk in chunks:
            _assert_no_pii(chunk.original_content)
        embeddings = self._embedder.embed([c.embedded_content for c in chunks])
        self._sink.write_document(
            artifact.artifact_id, chunks, embeddings, [[] for _ in chunks]
        )
        meta: dict[str, Any] = {
            "namespace": artifact.namespace,
            "session_id": artifact.session_id,
        }
        for chunk in chunks:
            cid = stele_chunk_id(artifact.artifact_id, chunk.seq_num)
            self._chunks[cid] = (chunk.original_content, artifact.reference, meta)
        self._ref_docs.setdefault(artifact.reference, set()).add(
            artifact.artifact_id
        )
        return len(chunks)

    def delete(self, reference: str) -> None:
        for doc_id in self._ref_docs.pop(reference, set()):
            self._sink.delete_document(doc_id)
        self._chunks = {
            cid: rec
            for cid, rec in self._chunks.items()
            if rec[1] != reference
        }

    def vector_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]:
        qvec: np.ndarray = self._embedder.embed([query])[0]
        # Over-fetch when filtering: query_top_k is global (no ref filter).
        k = limit if reference is None else max(limit, len(self._chunks))
        if k <= 0:
            return []
        hits: list[SearchHit] = []
        for doc_id, seq_num, distance in self._sink.query_top_k(qvec, k):
            cid = stele_chunk_id(doc_id, seq_num)
            retained = self._chunks.get(cid)
            if retained is None:
                continue
            chunk_text, ref, meta = retained
            if reference is not None and ref != reference:
                continue
            hits.append(
                SearchHit(
                    artifact_id=doc_id,
                    reference=ref,
                    chunk_id=cid,
                    text=chunk_text,
                    score=score_from_distance(distance),
                    retrieval_mode="vector",
                    metadata=dict(meta),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def keyword_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for cid, (chunk_text, ref, meta) in self._chunks.items():
            if reference is not None and ref != reference:
                continue
            score = keyword_score(query, chunk_text)
            if score <= 0:
                continue
            artifact_id, _, _ = cid.rpartition(":")
            hits.append(
                SearchHit(
                    artifact_id=artifact_id,
                    reference=ref,
                    chunk_id=cid,
                    text=snippet_around(chunk_text, query),
                    score=score,
                    retrieval_mode="keyword",
                    metadata=dict(meta),
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def embed(self, text: str) -> list[float]:
        return [float(x) for x in self._embedder.embed([text])[0]]

    def close(self) -> None:
        self._chunks.clear()
        self._ref_docs.clear()
