"""Main public facade."""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from stele.core.artifact import (
    Artifact,
    ArtifactRecord,
    CleanupResult,
    ExportResult,
    FetchResult,
    ImportResult,
    Page,
    PIIScrubSummary,
    ScrubResult,
    SearchHit,
    StoredResult,
    digest_content,
    estimate_tokens,
    utc_now,
)
from stele.core.capabilities import StashCapabilities
from stele.core.config import StashConfig
from stele.core.exceptions import CapabilityError, ConfigError, PIIBlockedError
from stele.core.jsonl import read_jsonl, write_jsonl
from stele.core.reference import make_reference
from stele.core.reference_auth import validate_reference_signature
from stele.core.types import ContentEncoding, ContentType, Lifecycle, RetrievalMode
from stele.indexing.chunk_index import ChunkIndex
from stele.indexing.queue import NoOpIndexer, SyncChunkIndexer
from stele.pii.scrubber import build_pii_scrubber
from stele.retrieval.base import RetrievalBackend
from stele.retrieval.clickhouse import ClickHouseRetrievalBackend
from stele.retrieval.mariadb import MariaDBRetrievalBackend
from stele.retrieval.memory import MemoryRetrievalBackend
from stele.retrieval.postgres import PostgresRetrievalBackend
from stele.retrieval.sqlite import SQLiteRetrievalBackend
from stele.storage.base import StorageBackend
from stele.storage.clickhouse import ClickHouseStorageBackend
from stele.storage.mariadb import MariaDBStorageBackend
from stele.storage.memory import MemoryStorageBackend
from stele.storage.postgres import PostgresStorageBackend
from stele.storage.sqlite import SQLiteStorageBackend
from stele.summary.lede_adapter import LedeSummaryProvider

if TYPE_CHECKING:
    from stele.core.memory import Memory
    from stele.extraction.extractor import MemoryExtractor


class Stele:
    def __init__(self, config: StashConfig) -> None:
        self.config = config
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
        self.indexer: NoOpIndexer | SyncChunkIndexer
        if config.indexing.provider == "chunkshop" and config.indexing.mode in {"sync", "async"}:
            self.chunk_index = ChunkIndex(config.indexing)
            self.indexer = SyncChunkIndexer(self.chunk_index)
        else:
            self.indexer = NoOpIndexer()

    @classmethod
    def from_config(
        cls,
        config: StashConfig | dict[str, Any] | str | Path | None = None,
    ) -> Stele:
        return cls(StashConfig.load(config))

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
        raw_text = _content_to_summary_text(content)
        raw_summary = self.summary_provider.summarize(
            raw_text,
            max_chars=self.config.summary.max_chars,
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
        index_result = self.indexer.submit(record)
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
    ) -> list[SearchHit]:
        raw_allowed = self._validate_raw_output(raw)
        merged_filters = dict(filters or {})
        if session_id is not None:
            merged_filters["session_id"] = session_id
        if self.chunk_index is not None and mode in {None, "keyword", "hybrid"}:
            chunk_hits = self.chunk_index.query_namespace(
                namespace,
                query,
                limit=limit,
                session_id=session_id,
            )
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
        if deleted and self.chunk_index is not None:
            self.chunk_index.delete(ref.canonical_without_params)
        return deleted

    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult:
        return self.storage.cleanup_expired(limit=limit)

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

    def capabilities(self) -> StashCapabilities:
        return StashCapabilities(
            storage=self.storage.capabilities(),
            retrieval=self.retrieval.capabilities().model_copy(
                update={"hybrid": self.chunk_index is not None}
            ),
        )

    def close(self) -> None:
        memory = getattr(self, "_memory", None)
        if memory is not None:
            memory.close()
        extractor = getattr(self, "_extractor", None)
        if extractor is not None:
            extractor.close()
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
                store = PostgresMemoryStore(self.config.backend.dsn)
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
            self._memory = Memory(store, self.pii_scrubber)  # type: ignore[arg-type]
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
