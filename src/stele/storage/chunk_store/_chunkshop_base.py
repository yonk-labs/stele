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

import logging
import re
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

_DEFAULT_DIM = 768  # bge-base-en-v1.5
_PIP_HINT = "pip install 'stele-core[chunkshop]'"


def _resolve_embed_dim(model_name: str) -> int:
    """Native output dim for a fastembed model (so callers don't hand-set it)."""
    try:
        from fastembed import TextEmbedding

        for m in TextEmbedding.list_supported_models():
            if m["model"] == model_name:
                return int(m["dim"])
    except Exception:  # pragma: no cover - fastembed optional/env-dependent
        pass
    return _DEFAULT_DIM
# A consolidator that resolves relative dates emits "[date: 2023-05-05]" (ISO,
# or a bare year) in the fact span; we lift it into a filterable fact_date field.
_FACT_DATE = re.compile(r"\[date:\s*(\d{4}(?:-\d{2}-\d{2})?)\]")

_logger = logging.getLogger("stele.retrieval")


def _warn_vector_recall_shortfall(
    *,
    rows_returned: int,
    top_k_requested: int,
    seed_size: int,
    has_reference_filter: bool,
) -> None:
    """Emit a structured WARNING when vector search returns fewer rows than
    requested. Mirrors pg-raggraph's vector_first guard: surfaces the
    silent-failure mode where the HNSW seed missed the predicate-matching
    candidates. See docs/retrieval-tuning-guide.md#vector-recall-shortfall.
    """
    mitigation = (
        "increase IndexingConfig.chunk_overlap_words or oversample factor; "
        "try keyword/hybrid mode; broaden the reference filter"
        if has_reference_filter
        else "the corpus may be smaller than top_k; otherwise increase oversample "
        "factor or try keyword/hybrid mode"
    )
    _logger.warning(
        "vector recall shortfall: returned=%d requested=%d seed_size=%d "
        "has_reference_filter=%s — %s "
        "(see docs/retrieval-tuning-guide.md#vector-recall-shortfall)",
        rows_returned,
        top_k_requested,
        seed_size,
        has_reference_filter,
        mitigation,
    )


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
            CallableConsolidator,
            ConsolidationChunker,
            FastembedEmbedder,
            FixedOverlapChunker,
            NeighborExpandChunker,
            SentenceAwareChunker,
            TargetConfig,
        )
        from chunkshop.embedders import load_embedder
        from chunkshop.sinks import load_sink

        self._config = config
        self._sim: Literal["cosine", "ip", "l2"] = config.similarity
        dim = config.vector_dim or _resolve_embed_dim(config.embed_model)
        self._embedder = load_embedder(
            FastembedEmbedder(
                type="fastembed",
                model_name=config.embed_model,
                dim=dim,
            )
        )
        base_chunker_cfg = FixedOverlapChunker(
            type="fixed_overlap",
            window_words=config.chunk_words,
            step_words=max(1, config.chunk_words - config.chunk_overlap_words),
        )
        if config.chunker == "consolidation":
            # Validated by IndexingConfig._check_task_backend_dsn that
            # consolidator_module is set when chunker == "consolidation".
            assert config.consolidator_module is not None
            self._chunker = load_chunker(
                ConsolidationChunker(
                    type="consolidation",
                    base=base_chunker_cfg,
                    consolidator=CallableConsolidator(
                        mode="callable",
                        module=config.consolidator_module,
                        function=config.consolidator_function,
                        kwargs=config.consolidator_kwargs,
                    ),
                    fact_max_chars=config.fact_max_chars,
                )
            )
        elif config.chunker == "sentence_aware":
            # Full-sentence boundaries (never mid-sentence); optional ±N
            # neighbor expansion gives each chunk surrounding-sentence context.
            sent_cfg = SentenceAwareChunker(
                type="sentence_aware",
                max_chars=config.sentence_max_chars,
                min_chars=config.sentence_min_chars,
            )
            if config.neighbor_window > 0:
                self._chunker = load_chunker(
                    NeighborExpandChunker(
                        type="neighbor_expand",
                        base=sent_cfg,
                        window=config.neighbor_window,
                    )
                )
            else:
                self._chunker = load_chunker(sent_cfg)
        else:
            self._chunker = load_chunker(base_chunker_cfg)
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
        artifact_meta: dict[str, Any] = {
            # artifact custom metadata first so reserved keys below take
            # precedence; created_at enables time-range filtering on vector hits.
            **(artifact.metadata or {}),
            "namespace": artifact.namespace,
            "session_id": artifact.session_id,
            "created_at": artifact.created_at.isoformat(),
        }
        for chunk in chunks:
            cid = stele_chunk_id(artifact.artifact_id, chunk.seq_num)
            # Use embedded_content (post-distillation view) rather than
            # original_content as the surface text. For FixedOverlap these
            # are identical; for ConsolidationChunker, episodes' embedded
            # content is the compressed summary while original is the full
            # pre-distill text. The model should see the compressed view.
            # The chunkshop chunk-level metadata (kind, subject, predicate,
            # object, support_span, ...) is layered onto artifact_meta so
            # consumers can distinguish episode vs fact via SearchHit.metadata.
            chunk_meta = {**artifact_meta}
            if chunk.metadata:
                for k, v in chunk.metadata.items():
                    if k.startswith("_"):
                        continue
                    chunk_meta.setdefault(k, v)
            # Promote a resolved per-fact date ("[date: 2023-05-05]", emitted by
            # a date-resolving consolidator) into a filterable fact_date field.
            # chunkshop's fact schema doesn't propagate arbitrary keys, so the
            # date rides in the span text; we lift it back out here so temporal
            # range filters (metadata.fact_date__gte/__lte) work on facts.
            fd = _FACT_DATE.search(chunk.embedded_content)
            if fd:
                chunk_meta.setdefault("fact_date", fd.group(1))
            self._chunks[cid] = (chunk.embedded_content, artifact.reference, chunk_meta)
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

    def delete_namespace(self, namespace: str) -> int:
        # Walk the retained-chunks map to collect refs whose metadata
        # records this namespace. The metadata dict is shared per ref
        # (set at write()), so any chunk's meta represents its ref.
        refs: set[str] = {
            ref for _cid, (_text, ref, meta) in self._chunks.items()
            if meta.get("namespace") == namespace
        }
        for ref in refs:
            self.delete(ref)
        return len(refs)

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
        if len(hits) < limit:
            _warn_vector_recall_shortfall(
                rows_returned=len(hits),
                top_k_requested=limit,
                seed_size=k,
                has_reference_filter=reference is not None,
            )
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
