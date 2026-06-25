"""Main public facade."""

from __future__ import annotations

import builtins
import uuid
import warnings
from collections.abc import Sequence
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from stele.core.artifact import (
    Artifact,
    ArtifactRecord,
    CleanupReport,
    CleanupResult,
    ExportResult,
    FetchResult,
    ImportResult,
    Page,
    PIIScrubSummary,
    PurgeReport,
    ScrubResult,
    SearchHit,
    StoredResult,
    StoreRequest,
    digest_content,
    estimate_tokens,
    utc_now,
)
from stele.core.capabilities import StashCapabilities
from stele.core.config import EmbeddingConfig, GraphConfig, StashConfig
from stele.core.exceptions import (
    CapabilityError,
    ConfigError,
    PIIBlockedError,
    SteleSecurityWarning,
)
from stele.core.jsonl import (
    read_jsonl,
    read_namespace_bundle,
    write_jsonl,
    write_namespace_bundle,
)
from stele.core.memory_record import MemoryScope
from stele.core.reference import make_reference
from stele.core.reference_auth import validate_reference_signature
from stele.core.types import ContentEncoding, ContentType, Lifecycle, RetrievalMode
from stele.indexing.async_queue import AsyncChunkIndexer
from stele.indexing.bakeoff import (
    BakeoffSummary,
    load_bakeoff_file,
    overlay_onto_indexing_config,
)
from stele.indexing.chunk_index import ChunkIndex
from stele.indexing.dim_resolution import resolve_dim_and_similarity
from stele.indexing.job import IndexJob, IndexResult
from stele.indexing.queue import NoOpIndexer, SyncChunkIndexer
from stele.indexing.task_backend.base import IndexTask
from stele.indexing.task_backend.in_process import InProcessTaskBackend
from stele.pii.scrubber import build_pii_scrubber
from stele.retrieval._filters import FilterableRow, record_matches_filters
from stele.retrieval.base import RetrievalBackend
from stele.retrieval.clickhouse import ClickHouseRetrievalBackend
from stele.retrieval.hybrid import hybrid_search
from stele.retrieval.mariadb import MariaDBRetrievalBackend
from stele.retrieval.memory import MemoryRetrievalBackend
from stele.retrieval.postgres import PostgresRetrievalBackend
from stele.retrieval.sqlite import SQLiteRetrievalBackend
from stele.retrieval.vector import vector_search
from stele.storage.base import StorageBackend
from stele.storage.chunk_store.base import ChunkStore
from stele.storage.clickhouse import ClickHouseStorageBackend
from stele.storage.mariadb import MariaDBStorageBackend
from stele.storage.memory import MemoryStorageBackend
from stele.storage.postgres import PostgresStorageBackend
from stele.storage.sqlite import SQLiteStorageBackend
from stele.summary.base import SummaryProvider
from stele.summary.compact import compact_or_digest
from stele.summary.lede_adapter import LedeSummaryProvider

if TYPE_CHECKING:
    from stele.core.memory import Memory
    from stele.distill.facade import Distill
    from stele.extraction.extractor import MemoryExtractor
    from stele.recall.facade import Recall
    from stele.revisor.base import Revisor


def _resolve_graph_embedding(
    graph: GraphConfig, embedding: EmbeddingConfig
) -> dict[str, Any]:
    """Effective graph-path embedding kwargs for the Revisor.

    Precedence: an explicitly-set graph-specific override (WS1 —
    ``graph.embedding_provider != 'local'``) wins; otherwise the core
    ``EmbeddingConfig`` (WS2) is the global default both paths read.

    ``EmbeddingConfig.provider='openai-compatible'`` maps to pg-raggraph
    ``'ollama'`` — NOT ``'openai'`` — because pg-raggraph 0.3.0a3's
    ``openai`` provider hardcodes ``api.openai.com`` and IGNORES
    ``base_url`` (caveat A), so a self-hosted OpenAI-compatible endpoint
    must go through the ``ollama`` provider, which honors ``llm_base_url``.
    """
    if graph.embedding_provider != "local":
        return {
            "embedding_provider": graph.embedding_provider,
            "embedding_model": graph.embedding_model,
            "embedding_dim": graph.embedding_dim,
            "embedding_base_url": graph.embedding_base_url,
            "embedding_api_key": graph.embedding_api_key,
        }
    if embedding.provider == "local":
        return {
            "embedding_provider": "local",
            "embedding_model": None,
            "embedding_dim": None,
            "embedding_base_url": None,
            "embedding_api_key": "",
        }
    return {
        "embedding_provider": "ollama",
        "embedding_model": embedding.model,
        "embedding_dim": embedding.dim,
        "embedding_base_url": embedding.base_url,
        "embedding_api_key": embedding.api_key,
    }


class Stele:
    def __init__(self, config: StashConfig) -> None:
        self.config = config
        if config.signing.mode == "disabled":
            # NOTE: if pytest `filterwarnings = error` is ever enabled in
            # pyproject, whitelist this category, else every default-config
            # construction reddens the suite:
            #   filterwarnings = ["error", "default::stele.core.exceptions.SteleSecurityWarning"]
            warnings.warn(
                "stele: reference signing is DISABLED — stele:// references "
                "are unsigned and forgeable. Safe for single-user/local. For any "
                "shared, multi-tenant, or networked deployment set "
                "signing.mode='required' with a strong secret. See "
                "docs/operations/SECURITY.md.",
                SteleSecurityWarning,
                stacklevel=2,
            )
        self.summary_provider = LedeSummaryProvider()
        self.pii_scrubber = build_pii_scrubber(config.pii)
        self.storage: StorageBackend
        self.retrieval: RetrievalBackend
        if config.backend.type == "memory":
            memory_storage = MemoryStorageBackend()
            self.storage = memory_storage
            self.retrieval = MemoryRetrievalBackend(memory_storage)
        elif config.backend.type == "sqlite":
            path = config.backend.path or ".stele/stele.db"
            sqlite_storage = SQLiteStorageBackend(path)
            self.storage = sqlite_storage
            self.retrieval = SQLiteRetrievalBackend(sqlite_storage)
        elif config.backend.type == "postgres":
            if not config.backend.dsn:
                raise ConfigError("Postgres backend requires backend.dsn")
            postgres_storage = PostgresStorageBackend(config.backend.dsn)
            self.storage = postgres_storage
            self.retrieval = PostgresRetrievalBackend(postgres_storage)
        elif config.backend.type == "mariadb":
            if not config.backend.dsn:
                raise ConfigError("MariaDB backend requires backend.dsn")
            mariadb_storage = MariaDBStorageBackend(config.backend.dsn, table=config.backend.table)
            self.storage = mariadb_storage
            self.retrieval = MariaDBRetrievalBackend(mariadb_storage)
        elif config.backend.type == "clickhouse":
            if not config.backend.dsn:
                raise ConfigError("ClickHouse backend requires backend.dsn")
            clickhouse_storage = ClickHouseStorageBackend(
                config.backend.dsn,
                database=config.backend.database,
                table=config.backend.table,
            )
            self.storage = clickhouse_storage
            self.retrieval = ClickHouseRetrievalBackend(clickhouse_storage)
        else:
            raise ConfigError(f"Backend is not implemented yet: {config.backend.type}")
        self.storage.initialize()
        self.chunk_index: ChunkIndex | None = None
        self._chunk_store: ChunkStore | None = None
        self._async_sync: SyncChunkIndexer | None = None
        # Submit-time capture for async indexing (avoids a worker-thread
        # re-fetch through the thread-affine SQLite artifact store).
        self._pending_records: dict[str, ArtifactRecord] = {}
        self.indexer: NoOpIndexer | SyncChunkIndexer | AsyncChunkIndexer
        self._apply_bakeoff_overlay()  # before _build_indexer: store uses overlaid dim
        self._build_indexer()
        self._bakeoff_summary: BakeoffSummary = resolve_dim_and_similarity(
            self.config.indexing, store=self._chunk_store
        )

    @classmethod
    def from_config(
        cls,
        config: StashConfig | dict[str, Any] | str | Path | None = None,
    ) -> Stele:
        return cls(StashConfig.load(config))

    # ----- Phase 4 indexing / chunk-store wiring -------------------------

    def _apply_bakeoff_overlay(self) -> None:
        """Load + overlay a bakeoff file at construction (SC-005).

        Missing/invalid file raises ConfigError (fail fast, SC-004).
        """
        path = self.config.indexing.bakeoff_path
        if not path:
            return
        bakeoff = load_bakeoff_file(path)
        self.config = self.config.model_copy(
            update={
                "indexing": overlay_onto_indexing_config(
                    self.config.indexing, bakeoff
                )
            }
        )

    def _build_chunk_store(self) -> ChunkStore:
        """Synthesize the backend chunk store from IndexingConfig only.

        Users never see chunkshop config; the DSN/path is reused from the
        artifact backend (chunkshop 0.4.3 ``TargetConfig(dsn=...)`` — no
        os.environ). sqlite uses a sibling file so the artifact DB is
        untouched.
        """
        bt = self.config.backend.type
        idx = self.config.indexing
        if bt == "memory":
            from stele.storage.chunk_store.memory import InProcessChunkStore

            return InProcessChunkStore(idx)
        if bt == "sqlite":
            from stele.storage.chunk_store.sqlite import SQLiteChunkStore

            path = self.config.backend.path or ".stele/stele.db"
            return SQLiteChunkStore(idx, db_path=f"{path}.chunks")
        if bt == "postgres":
            from stele.storage.chunk_store.postgres import PostgresChunkStore

            return PostgresChunkStore(idx, dsn=self.config.backend.dsn or "")
        if bt == "mariadb":
            from stele.storage.chunk_store.mariadb import MariaDBChunkStore

            return MariaDBChunkStore(idx, dsn=self.config.backend.dsn or "")
        if bt == "clickhouse":
            from stele.storage.chunk_store.clickhouse import ClickHouseChunkStore

            return ClickHouseChunkStore(idx, dsn=self.config.backend.dsn or "")
        raise ConfigError(f"no chunk store for backend {bt!r}")

    def _build_indexer(self) -> None:
        """Gate on ``indexing.mode != 'skip'`` (NOT on provider)."""
        if self.config.indexing.mode == "skip":
            self.indexer = NoOpIndexer()
            return
        self._chunk_store = self._build_chunk_store()
        # The chunk store's no-PII backstop only applies when we promise it
        # scrubbed text — i.e. when PII handling is on. With PII off (default)
        # raw content is indexed by design, so the guard must stand down.
        if hasattr(self._chunk_store, "_expect_scrubbed"):
            self._chunk_store._expect_scrubbed = self.config.pii.enabled
        # Keep the existing in-proc keyword path coherent for the memory
        # backend: expose the store's own ChunkIndex so search_reference /
        # delete stay consistent with what the indexer actually wrote.
        from stele.storage.chunk_store.memory import InProcessChunkStore

        if isinstance(self._chunk_store, InProcessChunkStore):
            self.chunk_index = self._chunk_store._index
        sync = SyncChunkIndexer(self._chunk_store)
        if self.config.indexing.mode == "async":
            self._async_sync = sync
            self.indexer = AsyncChunkIndexer(
                task_backend=InProcessTaskBackend(worker=self._index_task),
                sync=sync,
            )
        else:
            self.indexer = sync

    def _index_task(self, task: IndexTask) -> None:
        """Async worker: index the submitted artifact synchronously.

        The reference signature is still validated (recon's security
        intent). The record is taken from the submit-time capture rather
        than re-fetched: the Phase-1 SQLite artifact store caches a
        thread-affine connection (locked, must not modify), so a
        worker-thread ``storage.fetch`` raises a cross-thread error. The
        record is already in hand at submit, so no re-fetch is needed.
        """
        validate_reference_signature(task.reference, self.config.signing)
        record = self._pending_records.pop(task.artifact_id, None)
        if record is None:  # defensive: nothing to index
            return
        assert self._async_sync is not None
        self._async_sync.index_now(record)

    def indexing_status(self, artifact_id: str) -> IndexResult:
        return self.indexer.status(artifact_id)

    def _vector_hits(
        self, query: str, *, limit: int, reference: str | None
    ) -> list[SearchHit]:
        if self._chunk_store is None:
            raise CapabilityError(
                "vector retrieval requires indexing.mode != 'skip'"
            )
        # Over-fetch for namespace-scoped query() (post-filtered below).
        k = limit if reference is not None else max(limit, 50)
        return vector_search(self._chunk_store, query, limit=k, reference=reference)

    def _hybrid_hits(
        self, query: str, *, limit: int, reference: str | None
    ) -> list[SearchHit]:
        assert self._chunk_store is not None  # callers guard this
        idx = self.config.indexing
        k = limit if reference is not None else max(limit, 50)
        return hybrid_search(
            self._chunk_store,
            query,
            limit=k,
            reference=reference,
            method=idx.hybrid_method,
            weights=idx.hybrid_weights,
            rrf_k=idx.hybrid_rrf_k,
        )

    @staticmethod
    def _scope_namespace(
        hits: list[SearchHit],
        namespace: str,
        session_id: str | None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        # Vector/hybrid hits carry a flat metadata dict (namespace, session_id,
        # created_at, plus artifact + chunk metadata). Apply created_at/metadata
        # filters here via the shared predicate — the filter half of
        # filter-then-rank for the vector path. SPO fact fields (subject/
        # predicate/object) are filterable too since they're in the same dict.
        out: list[SearchHit] = []
        seen_text: set[str] = set()  # select-distinct: never return the same chunk twice
        for h in hits:
            if h.metadata.get("namespace") != namespace:
                continue
            if session_id is not None and h.metadata.get("session_id") != session_id:
                continue
            if filters:
                shim = FilterableRow.from_sql(
                    h.metadata.get("session_id"), h.metadata.get("created_at"), h.metadata
                )
                if not record_matches_filters(shim, filters):
                    continue
            if h.text in seen_text:  # dup from hybrid RRF merge / repeated spans
                continue
            seen_text.add(h.text)
            out.append(h)
        return out

    def store(
        self,
        content: str | bytes,
        *,
        namespace: str = "default",
        session_id: str | None = None,
        content_type: ContentType | str | None = None,
        metadata: dict[str, Any] | None = None,
        lifecycle: Lifecycle | str = "manual",
        ttl_seconds: int | None = None,
        index: str | None = None,
    ) -> StoredResult:
        del index
        artifact_id = uuid.uuid4().hex
        reference = make_reference(namespace, artifact_id).canonical_without_params
        raw_summary = _summarize_content(
            content, self.summary_provider, self.config.summary.max_chars
        )
        scrubbed_summary = self._scrub_text(raw_summary).text
        now = utc_now()
        expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        content_encoding: ContentEncoding = "bytes" if isinstance(content, bytes) else "utf-8"
        artifact = Artifact(
            artifact_id=artifact_id,
            reference=reference,
            namespace=namespace,
            session_id=session_id,
            content=content,
            content_encoding=content_encoding,
            content_type=_normalize_content_type(content_type),
            metadata=metadata or {},
            summary=scrubbed_summary,
            raw_summary=raw_summary,
            digest_sha256=digest_content(content, content_encoding),
            byte_size=len(content if isinstance(content, bytes) else content.encode("utf-8")),
            token_estimate=estimate_tokens(content),
            lifecycle=cast(Lifecycle, lifecycle),
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        record = self.storage.store(artifact)
        index_result = self._submit_index(record)
        if self.revisor.active:
            # Project the already-PII-scrubbed summary — source-backed and
            # PII-safe; the artifact's stele:// ref round-trips on every hit.
            self.revisor.ingest_evidence(
                stele_ref=record.reference,
                text=record.summary,
                namespace=record.namespace,
                effective_from=record.created_at,
                session_id=record.session_id,
            )
        replacement_char_count = len(record.summary) + len(record.reference)
        original_tokens = record.token_estimate
        replacement_tokens = estimate_tokens(record.summary) + estimate_tokens(record.reference)
        savings = max(0, original_tokens - replacement_tokens)
        pct = savings / original_tokens if original_tokens else 0.0
        return StoredResult(
            artifact_id=record.artifact_id,
            reference=record.reference,
            namespace=record.namespace,
            session_id=record.session_id,
            summary=record.summary,
            content_type=record.content_type,
            byte_size=record.byte_size,
            token_estimate=record.token_estimate,
            replacement_char_count=replacement_char_count,
            estimated_token_savings=savings,
            estimated_token_savings_pct=pct,
            index_status=index_result.status,
            pii=self._scrub_text(raw_summary).summary,
            created_at=record.created_at,
        )

    def store_many(self, items: list[StoreRequest]) -> list[StoredResult]:
        """Persist N artifacts in one transaction / one server round-trip.

        Returns per-row :class:`StoredResult` in input order. Empty input
        returns []. Observably equivalent to ``[store(...), store(...)]``
        for the same inputs — same dedup, same PII scrub, same indexer
        and revisor side-effects — but the storage write is batched.

        PII scrubbing remains per-row (deterministic, can't batch).
        Revisor projection (when active) is per-row in this slice;
        batching that surface is a follow-up. Indexer submission stays
        per-row but the existing AsyncChunkIndexer already batches its
        task backend.
        """
        if not items:
            return []
        artifacts: list[Artifact] = []
        raw_summaries: list[str] = []
        for item in items:
            artifact_id = uuid.uuid4().hex
            reference = make_reference(item.namespace, artifact_id).canonical_without_params
            raw_summary = _summarize_content(
                item.content, self.summary_provider, self.config.summary.max_chars
            )
            scrubbed_summary = self._scrub_text(raw_summary).text
            now = utc_now()
            expires_at = (
                now + timedelta(seconds=item.ttl_seconds) if item.ttl_seconds else None
            )
            content_encoding: ContentEncoding = (
                "bytes" if isinstance(item.content, bytes) else "utf-8"
            )
            artifact = Artifact(
                artifact_id=artifact_id,
                reference=reference,
                namespace=item.namespace,
                session_id=item.session_id,
                content=item.content,
                content_encoding=content_encoding,
                content_type=_normalize_content_type(item.content_type),
                metadata=item.metadata or {},
                summary=scrubbed_summary,
                raw_summary=raw_summary,
                digest_sha256=digest_content(item.content, content_encoding),
                byte_size=len(
                    item.content if isinstance(item.content, bytes)
                    else item.content.encode("utf-8")
                ),
                token_estimate=estimate_tokens(item.content),
                lifecycle=cast(Lifecycle, item.lifecycle),
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            artifacts.append(artifact)
            raw_summaries.append(raw_summary)
        records = self.storage.store_many(artifacts)
        results: list[StoredResult] = []
        for record, raw_summary in zip(records, raw_summaries, strict=True):
            index_result = self._submit_index(record)
            if self.revisor.active:
                self.revisor.ingest_evidence(
                    stele_ref=record.reference,
                    text=record.summary,
                    namespace=record.namespace,
                    effective_from=record.created_at,
                    session_id=record.session_id,
                )
            replacement_char_count = len(record.summary) + len(record.reference)
            original_tokens = record.token_estimate
            replacement_tokens = estimate_tokens(record.summary) + estimate_tokens(
                record.reference
            )
            savings = max(0, original_tokens - replacement_tokens)
            pct = savings / original_tokens if original_tokens else 0.0
            results.append(StoredResult(
                artifact_id=record.artifact_id,
                reference=record.reference,
                namespace=record.namespace,
                session_id=record.session_id,
                summary=record.summary,
                content_type=record.content_type,
                byte_size=record.byte_size,
                token_estimate=record.token_estimate,
                replacement_char_count=replacement_char_count,
                estimated_token_savings=savings,
                estimated_token_savings_pct=pct,
                index_status=index_result.status,
                pii=self._scrub_text(raw_summary).summary,
                created_at=record.created_at,
            ))
        return results

    def fetch(self, reference: str, *, raw: bool = False, scrub: bool | None = None) -> FetchResult:
        ref = validate_reference_signature(reference, self.config.signing)
        record = self.storage.fetch(ref)
        raw_allowed = raw and self.config.pii.raw_fetch_enabled
        if raw and not raw_allowed:
            raise PIIBlockedError("Raw fetch requires pii.raw_fetch_enabled=true")
        should_scrub = self._should_scrub(raw=raw_allowed, scrub=scrub)
        content = record.content
        scrub_summary = PIIScrubSummary(enabled=self.config.pii.enabled, scrubbed=False)
        if should_scrub and isinstance(content, str):
            scrubbed = self._scrub_text(content)
            content = scrubbed.text
            scrub_summary = scrubbed.summary
        return FetchResult(
            artifact_id=record.artifact_id,
            reference=record.reference,
            content=content,
            content_type=record.content_type,
            raw=raw_allowed,
            scrubbed=should_scrub,
            pii=scrub_summary,
            metadata=record.metadata,
            digest_sha256=record.digest_sha256,
            byte_size=record.byte_size,
            created_at=record.created_at,
        )

    def read_bounded(
        self,
        source: str,
        *,
        want: tuple[int, int] | str,
        language: str | None = None,
        max_chars: int = 2000,
    ) -> str:
        """Return a dependency-aware bounded view of code (the over-fetch fix).

        ``source`` may be a ``stele://`` reference (the artifact is fetched), a
        path to a file on disk, or raw source text. ``want`` is a 1-based
        inclusive ``(start, end)`` line range or a symbol name. The full content
        stays available via ``fetch``; the view advertises expansion handles so
        the agent keeps agency to escalate. See docs/specs/bounded-code-read-design.md.
        """
        from pathlib import Path

        from stele.codeview import bounded_view, language_for_path

        if source.startswith("stele://"):
            text = str(self.fetch(source).content)
        elif "\n" not in source and Path(source).is_file():
            text = Path(source).read_text(errors="replace")
            language = language or language_for_path(source)
        else:
            text = source
        return bounded_view(text, want=want, language=language or "python", max_chars=max_chars)

    def search(
        self,
        reference: str,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | str | None = None,
        raw: bool = False,
    ) -> list[SearchHit]:
        raw_allowed = self._validate_raw_output(raw)
        ref = validate_reference_signature(reference, self.config.signing)
        effective_mode = mode or self.config.retrieval.default_mode
        if effective_mode == "vector":
            hits = self._vector_hits(query, limit=limit, reference=ref.canonical_without_params)
            return self._prepare_hits(hits, raw=raw_allowed)
        if effective_mode == "hybrid" and self._chunk_store is not None:
            hits = self._hybrid_hits(query, limit=limit, reference=ref.canonical_without_params)
            return self._prepare_hits(hits, raw=raw_allowed)
        if self.chunk_index is not None and mode in {None, "keyword", "hybrid"}:
            chunk_hits = self.chunk_index.search_reference(
                ref.canonical_without_params,
                query,
                limit=limit,
            )
            if chunk_hits:
                return self._prepare_hits(chunk_hits, raw=raw_allowed)
        hits = self.retrieval.search_artifact(ref, query, limit=limit, mode=mode)  # type: ignore[arg-type]
        return self._prepare_hits(hits, raw=raw_allowed)

    def query(
        self,
        namespace: str,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | str | None = None,
        session_id: str | None = None,
        filters: dict[str, Any] | None = None,
        raw: bool = False,
        now: datetime | None = None,
    ) -> list[SearchHit]:
        raw_allowed = self._validate_raw_output(raw)
        merged_filters = dict(filters or {})
        if session_id is not None:
            merged_filters["session_id"] = session_id

        # Opt-in temporal routing: parse a NL recency window out of the query,
        # strip the phrase (sharpens the embed), add the date filter. `now`
        # defaults to wall-clock; pass it explicitly for replay-safe runs.
        window_keys: list[str] = []
        if self.config.retrieval.temporal_routing:
            from stele.retrieval.temporal import parse_temporal

            cleaned, tf = parse_temporal(query, now or utc_now())
            if tf is not None:
                field = self.config.retrieval.temporal_date_field
                window = tf.as_metadata_filters(field) if field else tf.as_filters()
                for key, value in window.items():
                    if key not in merged_filters:  # never override caller filters
                        merged_filters[key] = value
                        window_keys.append(key)
                query = cleaned

        hits = self._dispatch_query(
            namespace, query, mode, merged_filters, session_id, limit, raw_allowed
        )
        # Empty under the parsed window → retry without it so a bad/over-tight
        # parse can't silently hide the answer.
        if not hits and window_keys:
            for key in window_keys:
                merged_filters.pop(key, None)
            hits = self._dispatch_query(
                namespace, query, mode, merged_filters, session_id, limit, raw_allowed
            )
        return hits

    def _dispatch_query(
        self,
        namespace: str,
        query: str,
        mode: RetrievalMode | str | None,
        merged_filters: dict[str, Any],
        session_id: str | None,
        limit: int,
        raw_allowed: bool,
    ) -> list[SearchHit]:
        effective_mode = mode or self.config.retrieval.default_mode
        # Non-session filters need a larger candidate pool before post-filtering.
        extra_filter = any(k != "session_id" for k in merged_filters)
        scope_limit = limit * 16 if extra_filter else limit
        if effective_mode == "vector":
            hits = self._vector_hits(query, limit=scope_limit, reference=None)
            hits = self._scope_namespace(hits, namespace, session_id, merged_filters)[:limit]
            return self._prepare_hits(hits, raw=raw_allowed)
        if effective_mode == "hybrid" and self._chunk_store is not None:
            hits = self._hybrid_hits(query, limit=scope_limit, reference=None)
            hits = self._scope_namespace(hits, namespace, session_id, merged_filters)[:limit]
            return self._prepare_hits(hits, raw=raw_allowed)
        if self.chunk_index is not None and mode in {None, "keyword", "hybrid"}:
            chunk_hits = self.chunk_index.query_namespace(
                namespace,
                query,
                limit=scope_limit,
                session_id=session_id,
            )
            chunk_hits = self._scope_namespace(
                chunk_hits, namespace, session_id, merged_filters
            )[:limit]
            if chunk_hits:
                return self._prepare_hits(chunk_hits, raw=raw_allowed)
        hits = self.retrieval.query_namespace(
            namespace,
            query,
            limit=limit,
            mode=mode,  # type: ignore[arg-type]
            filters=merged_filters,
        )
        return self._prepare_hits(hits, raw=raw_allowed)

    def list(
        self,
        *,
        namespace: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[ArtifactRecord]:
        return self.storage.list(
            namespace=namespace,
            session_id=session_id,
            limit=limit,
            cursor=cursor,
        )

    def delete(self, reference: str) -> bool:
        ref = validate_reference_signature(reference, self.config.signing)
        deleted = self.storage.delete(ref)
        if deleted and self._chunk_store is not None:
            # For the memory backend chunk_index IS the store's own index,
            # so this keeps the existing keyword path consistent too.
            self._chunk_store.delete(ref.canonical_without_params)
        return deleted

    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult:
        return self.storage.cleanup_expired(limit=limit)

    def cleanup(
        self,
        *,
        expired_artifact_limit: int = 1000,
        superseded_memory_before: datetime | None = None,
    ) -> CleanupReport:
        """Umbrella retention entrypoint.

        Always runs the existing expired-artifact cleanup. The
        superseded-memory purge is OPT-IN and horizon-bounded:

        - ``superseded_memory_before is None`` (default) → purges ZERO
          superseded memories. This is default-safe: ``as_of``
          time-travel history is never silently destroyed.
        - a datetime → hard-deletes only memory records whose validity
          window ended strictly before that cutoff (status='superseded'
          AND effective_until < cutoff). Records still valid, active, or
          superseded-but-recent are kept, so time-travel after the
          horizon is preserved.

        Operators schedule this (cron / systemd timer) with an explicit
        retention horizon. There is deliberately no automatic default —
        an aggressive default would silently break ``as_of`` history.
        """
        expired = self.cleanup_expired(limit=expired_artifact_limit)
        purged = 0
        if superseded_memory_before is not None:
            purged = self.memory.purge_superseded(superseded_memory_before)
        return CleanupReport(
            artifacts_expired=expired.deleted_count,
            superseded_memories_purged=purged,
        )

    def purge_namespace(
        self, namespace: str, *, dry_run: bool = False
    ) -> PurgeReport:
        """Hard-delete every namespace-scoped row across all subsystems.

        Lifecycle / GDPR primitive. Other namespaces are never touched.
        ``dry_run=True`` returns the same shape with the counts that
        *would* be deleted, mutating nothing — useful for confirmation
        before invoking the destructive call.

        Covers four surfaces in one call:

        - **Artifact storage** — always.
        - **Memory rows** — when the backend supports memory.
        - **Chunk index** — when one is configured.
        - **Revisor-projected evidence** (pg-raggraph) — when active.

        On ``dry_run``, only artifact and memory counts are populated;
        chunk-index and revisor counts are best-effort 0 (the underlying
        surfaces don't expose a cheap pre-count). The real call returns
        accurate counts for every surface that ran.
        """
        if not namespace:
            raise ValueError("purge_namespace requires a non-empty namespace")
        if dry_run:
            artifact_count = 0
            cursor: str | None = None
            while True:
                page = self.storage.list(namespace=namespace, limit=1000, cursor=cursor)
                artifact_count += len(page.items)
                if page.next_cursor is None or not page.items:
                    break
                cursor = page.next_cursor
            memory_count = 0
            try:
                memory_count = len(
                    self.memory.list(
                        scope=MemoryScope(namespace=namespace),
                        status_filter=[
                            "active", "superseded", "retracted", "disputed", "deleted",
                        ],
                        limit=10_000,
                    )
                )
            except CapabilityError:
                memory_count = 0
            return PurgeReport(
                namespace=namespace,
                dry_run=True,
                artifacts=artifact_count,
                memories=memory_count,
            )

        artifacts = self.storage.delete_namespace(namespace)
        memories = 0
        try:
            memories = self.memory.delete_namespace(namespace)
        except CapabilityError:
            memories = 0
        chunks = 0
        if self._chunk_store is not None:
            chunks = self._chunk_store.delete_namespace(namespace)
        graph_evidence = 0
        if self.revisor.active:
            graph_evidence = self.revisor.purge_namespace(namespace)
        return PurgeReport(
            namespace=namespace,
            dry_run=False,
            artifacts=artifacts,
            memories=memories,
            chunks=chunks,
            graph_evidence=graph_evidence,
        )

    def export_jsonl(
        self,
        path: str | Path,
        *,
        namespace: str | None = None,
        session_id: str | None = None,
        limit: int = 100_000,
    ) -> ExportResult:
        page = self.storage.list(namespace=namespace, session_id=session_id, limit=limit)
        count = write_jsonl(page.items, path)
        return ExportResult(exported_count=count, path=str(path))

    def import_jsonl(self, path: str | Path) -> ImportResult:
        artifacts = read_jsonl(path)
        for artifact in artifacts:
            self.storage.store(artifact)
            self.indexer.submit(artifact)
        return ImportResult(imported_count=len(artifacts))

    def export_namespace(
        self, namespace: str, path: str | Path, *, limit: int = 100_000
    ) -> ExportResult:
        """Export every artifact + memory row in ``namespace`` as a
        portable JSONL bundle. The supersession chain on memory rows
        round-trips via ``MemoryRecord.supersedes``.

        Reuses the existing JSONL machinery with a v2 mixed-record
        format (one ``kind`` per line). Chunks and revisor projections
        are NOT bundled — both are derived state that rebuilds on
        import via the normal indexer / ingest paths.

        Round-trips via :meth:`Stele.import_namespace`.
        """
        if not namespace:
            raise ValueError("export_namespace requires a non-empty namespace")
        page = self.storage.list(namespace=namespace, limit=limit)
        artifact_records = page.items
        memories: list[Any] = []
        try:
            memories = self.memory.list(
                scope=MemoryScope(namespace=namespace),
                status_filter=[
                    "active", "superseded", "retracted", "disputed", "deleted",
                ],
                limit=limit,
            )
        except CapabilityError:
            memories = []
        count = write_namespace_bundle(artifact_records, memories, path)
        return ExportResult(exported_count=count, path=str(path))

    def import_namespace(self, path: str | Path) -> ImportResult:
        """Restore an export_namespace bundle. Re-runs the indexer on
        artifacts so the chunk index rebuilds. Memory rows insert
        directly via the memory_store with their original supersedes
        edges preserved."""
        artifacts, memories = read_namespace_bundle(path)
        for artifact in artifacts:
            self.storage.store(artifact)
            self.indexer.submit(artifact)
        if memories:
            # CRITICAL: pass supersedes=[] (NOT m.supersedes) so the
            # store inserts each record AS-IS without re-firing the
            # mark-old-superseded side-effect. The record itself already
            # carries supersedes=[...], status=..., effective_until=...
            # from the export — we want byte-identical restore, not
            # re-running business logic.
            try:
                for memory in memories:
                    self.memory._store.add(memory, [])
            except CapabilityError:
                # Backend has no memory support — skip silently. Artifacts
                # restored regardless.
                pass
        return ImportResult(imported_count=len(artifacts) + len(memories))

    def capabilities(self) -> StashCapabilities:
        try:
            cs_version: str | None = pkg_version("chunkshop")
        except PackageNotFoundError:
            cs_version = None
        store = self._chunk_store
        has_store = store is not None
        try:
            pgrg_version: str | None = pkg_version("pg-raggraph")
        except PackageNotFoundError:
            pgrg_version = None
        pgrg_installed = find_spec("pg_raggraph") is not None
        graph_active = self.revisor.active
        return StashCapabilities(
            storage=self.storage.capabilities(),
            retrieval=self.retrieval.capabilities().model_copy(
                update={"hybrid": self.chunk_index is not None}
            ),
            chunk_store_backend=store.name if store is not None else None,  # type: ignore[arg-type]
            vector_enabled=has_store,
            hybrid_enabled=has_store,
            chunkshop_installed=find_spec("chunkshop") is not None,
            chunkshop_version=cs_version,
            bakeoff_summary=self._bakeoff_summary,
            task_backend=(
                self.config.indexing.task_backend
                if self.config.indexing.mode == "async"
                else None
            ),
            graph_enabled=self.config.graph.enabled,
            living_knowledge=graph_active,
            pg_raggraph_installed=pgrg_installed,
            pg_raggraph_version=pgrg_version,
            memory_vector_search=(
                self.config.backend.type == "postgres"
                and self.config.retrieval.memory_vector
                and find_spec("chunkshop") is not None
            ),
        )

    def close(self) -> None:
        memory = getattr(self, "_memory", None)
        if memory is not None:
            memory.close()
        extractor = getattr(self, "_extractor", None)
        if extractor is not None:
            extractor.close()
        recall = getattr(self, "_recall", None)
        if recall is not None:
            recall.close()
        revisor = getattr(self, "_revisor", None)
        if revisor is not None:
            revisor.close()
        indexer = getattr(self, "indexer", None)
        if isinstance(indexer, AsyncChunkIndexer):
            indexer.close()
        chunk_store = getattr(self, "_chunk_store", None)
        if chunk_store is not None:
            chunk_store.close()
        self.storage.close()

    @property
    def memory(self) -> Memory:  # forward ref; imported below
        if not hasattr(self, "_memory"):
            from stele.core.memory import Memory
            from stele.storage.memory_store.memory import InProcessMemoryStore
            from stele.storage.memory_store.sqlite import SQLiteMemoryStore

            store: object
            if self.config.backend.type == "memory":
                store = InProcessMemoryStore()
            elif self.config.backend.type == "sqlite":
                path = self.config.backend.path or ".stele/stele.db"
                from pathlib import Path

                memory_db = str(Path(path).with_name("memory_" + Path(path).name))
                store = SQLiteMemoryStore(memory_db)
            elif self.config.backend.type == "postgres":
                from stele.storage.memory_store.postgres import (
                    PostgresMemoryStore,
                )

                if not self.config.backend.dsn:
                    raise ConfigError("Postgres memory store requires backend.dsn")
                embedder = None
                if self.config.retrieval.memory_vector:
                    from stele.storage.memory_store._embedder import (
                        build_memory_embedder,
                    )

                    embedder = build_memory_embedder(self.config.indexing)
                store = PostgresMemoryStore(
                    self.config.backend.dsn, embedder=embedder
                )
            elif self.config.backend.type == "mariadb":
                from stele.storage.memory_store.mariadb import (
                    MariaDBMemoryStore,
                )

                store = MariaDBMemoryStore()
            elif self.config.backend.type == "clickhouse":
                from stele.storage.memory_store.clickhouse import (
                    ClickHouseMemoryStore,
                )

                store = ClickHouseMemoryStore()
            else:
                raise ConfigError(
                    f"Memory store not implemented for backend: {self.config.backend.type}"
                )
            store.initialize()
            self._memory = Memory(
                store,  # type: ignore[arg-type]
                self.pii_scrubber,
                revisor=self.revisor,
            )
        return self._memory

    @property
    def extract(self) -> MemoryExtractor:  # forward ref imported below
        if not hasattr(self, "_extractor"):
            from stele.extraction.extractor import MemoryExtractor

            self._extractor = MemoryExtractor(
                stele=self,
                memory=self.memory,
                scrubber=self.pii_scrubber,
                config=self.config.extraction,
            )
        return self._extractor

    @property
    def recall(self) -> Recall:  # forward ref imported below
        if not hasattr(self, "_recall"):
            from stele.recall.facade import Recall
            from stele.summary.digest import DigestPacker

            recall_config = self.config.recall
            # When chunk indexing is enabled (hybrid search exists) and the
            # caller hasn't pinned a default, default to the `digest` packing
            # (lede summary + facts + top chunks) — the highest-accuracy
            # hybrid-search packing. Index-off deployments keep their default.
            if (
                self.config.indexing.mode != "skip"
                and "default_strategy" not in recall_config.model_fields_set
            ):
                recall_config = recall_config.model_copy(
                    update={"default_strategy": "digest"}
                )

            self._recall = Recall(
                stele=self,
                memory=self.memory,
                scrubber=self.pii_scrubber,
                config=recall_config,
                digest_packer=DigestPacker(),
            )
        return self._recall

    @property
    def distill(self) -> Distill:
        if not hasattr(self, "_distill"):
            from stele.distill.facade import Distill

            self._distill = Distill(
                stele=self,
                memory=self.memory,
                extract=self.extract,
                recall=self.recall,
                config=self.config.distill,
                llm=getattr(self, "_distill_llm", None),
                embedder=getattr(self, "_distill_embedder", None),
            )
        return self._distill

    @property
    def revisor(self) -> Revisor:
        if not hasattr(self, "_revisor"):
            from stele.revisor.base import NoOpRevisor

            if (
                not self.config.graph.enabled
                or self.config.backend.type != "postgres"
                or not self.config.backend.dsn
            ):
                self._revisor: Revisor = NoOpRevisor()
            else:
                from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

                emb = _resolve_graph_embedding(
                    self.config.graph, self.config.embedding
                )
                self._revisor = PgRaggraphRevisor(
                    dsn=self.config.backend.dsn,
                    namespace=self.config.graph.namespace,
                    evolution_tier=self.config.graph.evolution_tier,
                    fact_extractor=self.config.graph.fact_extractor,
                    llm_base_url=self.config.graph.llm_base_url,
                    llm_model=self.config.graph.llm_model,
                    llm_api_key=self.config.graph.llm_api_key,
                    query_mode=self.config.graph.query_mode,
                    rerank=self.config.graph.rerank,
                    **emb,
                )
        return self._revisor

    def _submit_index(self, record: ArtifactRecord) -> IndexResult | IndexJob:
        """Index a record under the PII policy; the raw artifact is untouched.

        PII off (default): index the raw record. PII on: a doc with no detected
        PII indexes as-is; one with PII is either masked (index a scrubbed copy,
        so no raw PII reaches the chunk index/embeddings) or skipped entirely,
        per ``pii.index_on_pii``. Model-visible hits are scrubbed again at read.
        """
        index_record = record
        if self.config.pii.enabled:
            scrubbed = self._scrub_text(record.content_as_text())
            if scrubbed.detections:
                if self.config.pii.index_on_pii == "skip":
                    return IndexResult(
                        artifact_id=record.artifact_id,
                        status="skipped",
                        message="PII present; index_on_pii=skip",
                    )
                index_record = record.model_copy(
                    update={"content": scrubbed.text, "content_encoding": "utf-8"}
                )
        if isinstance(self.indexer, AsyncChunkIndexer):
            self._pending_records[index_record.artifact_id] = index_record
        return self.indexer.submit(index_record)

    def _scrub_text(self, text: str) -> ScrubResult:
        if not self.config.pii.enabled:
            return ScrubResult(text=text, detections=[])
        return self.pii_scrubber.scrub(text)

    def _should_scrub(self, *, raw: bool, scrub: bool | None) -> bool:
        if scrub is not None:
            return scrub
        if raw:
            return False
        return self.config.pii.enabled and self.config.pii.default_surface_policy == "scrub"

    def _validate_raw_output(self, raw: bool) -> bool:
        if raw and not self.config.pii.raw_fetch_enabled:
            raise PIIBlockedError("Raw output requires pii.raw_fetch_enabled=true")
        return raw

    def _prepare_hits(
        self,
        hits: Sequence[SearchHit],
        *,
        raw: bool,
    ) -> builtins.list[SearchHit]:
        # Select-distinct: never hand back the same chunk text twice (dups can
        # arise from the hybrid RRF merge or repeated spans across artifacts).
        # Order-preserving, so the highest-ranked instance is kept.
        seen: set[str] = set()
        distinct: builtins.list[SearchHit] = []
        for h in hits:
            if h.text not in seen:
                seen.add(h.text)
                distinct.append(h)
        hits = distinct
        if raw or not self.config.pii.enabled:
            return [hit.model_copy(update={"scrubbed": False}) for hit in hits]
        prepared: builtins.list[SearchHit] = []
        for hit in hits:
            scrubbed = self._scrub_text(hit.text)
            prepared.append(
                hit.model_copy(
                    update={
                        "text": scrubbed.text,
                        "scrubbed": True,
                        "pii": scrubbed.summary,
                    }
                )
            )
        return prepared


def _normalize_content_type(value: ContentType | str | None) -> ContentType:
    if value is None:
        return "text"
    allowed = {
        "text",
        "json",
        "table",
        "csv",
        "sql",
        "code",
        "code_diff",
        "log",
        "html",
        "markdown",
        "blob",
    }
    if value not in allowed:
        raise CapabilityError(f"Unsupported content type: {value}")
    return cast(ContentType, value)


def _content_to_summary_text(content: str | bytes) -> str:
    if isinstance(content, str):
        return content
    return content.decode("utf-8", errors="replace")


def _summarize_content(
    content: str | bytes, provider: SummaryProvider, max_chars: int
) -> str:
    """Pick the summary for an artifact's content (compact-return dispatch).

    JSON containers get a compact form (minified-if-it-fits, else a bounded
    structural digest) and bypass the prose summarizer entirely; everything else
    goes to ``provider``. See docs/specs/compact-return.md.
    """
    raw_text = _content_to_summary_text(content)
    compact = compact_or_digest(raw_text, max_chars=max_chars)
    if compact is not None:
        return compact
    return provider.summarize(raw_text, max_chars=max_chars)
