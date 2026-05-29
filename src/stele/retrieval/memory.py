"""In-memory keyword retrieval."""

from __future__ import annotations

from stele.core.artifact import SearchHit
from stele.core.capabilities import RetrievalCapabilities
from stele.core.exceptions import CapabilityError
from stele.core.reference import Reference
from stele.core.types import RetrievalMode
from stele.retrieval._filters import record_matches_filters
from stele.retrieval.rank import keyword_score, snippet_around
from stele.storage.memory import MemoryStorageBackend


class MemoryRetrievalBackend:
    def __init__(self, storage: MemoryStorageBackend) -> None:
        self.storage = storage

    def search_artifact(
        self,
        reference: Reference,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | None = None,
        filters: dict[str, object] | None = None,
    ) -> list[SearchHit]:
        del filters
        self._validate_mode(mode)
        record = self.storage.fetch(reference)
        score = keyword_score(query, record.content_as_text())
        if score <= 0:
            return []
        return [
            SearchHit(
                artifact_id=record.artifact_id,
                reference=record.reference,
                chunk_id=None,
                text=snippet_around(record.content_as_text(), query),
                score=score,
                retrieval_mode="keyword",
                metadata={"namespace": record.namespace},
            )
        ][:limit]

    def query_namespace(
        self,
        namespace: str,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | None = None,
        filters: dict[str, object] | None = None,
    ) -> list[SearchHit]:
        self._validate_mode(mode)
        session_id = None
        if filters and isinstance(filters.get("session_id"), str):
            session_id = str(filters["session_id"])
        hits: list[SearchHit] = []
        page = self.storage.list(namespace=namespace, session_id=session_id, limit=10_000)
        for record in page.items:
            # Time-range + metadata filters (created_after/before, metadata.<key>).
            # session_id is already applied via storage.list above.
            if not record_matches_filters(record, filters):
                continue
            score = keyword_score(query, record.content_as_text())
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    artifact_id=record.artifact_id,
                    reference=record.reference,
                    chunk_id=None,
                    text=snippet_around(record.content_as_text(), query),
                    score=score,
                    retrieval_mode="keyword",
                    metadata={"namespace": record.namespace, **record.metadata},
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities(backend_type="memory", keyword=True, default_mode="keyword")

    def _validate_mode(self, mode: RetrievalMode | None) -> None:
        if mode in {None, "keyword"}:
            return
        raise CapabilityError(f"Memory backend does not support retrieval mode: {mode}")
