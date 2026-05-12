"""Postgres full-text retrieval."""

from __future__ import annotations

from typing import Any

from stele.core.artifact import SearchHit
from stele.core.capabilities import RetrievalCapabilities
from stele.core.exceptions import CapabilityError
from stele.core.reference import Reference
from stele.core.types import RetrievalMode
from stele.retrieval.rank import snippet_around
from stele.storage.postgres import PostgresStorageBackend


class PostgresRetrievalBackend:
    def __init__(self, storage: PostgresStorageBackend) -> None:
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
        rows = self.storage.conn.execute(
            """
            SELECT
              artifact_id,
              reference,
              namespace,
              search_text AS content_text,
              ts_rank_cd(
                to_tsvector('english', search_text || ' ' || summary),
                websearch_to_tsquery('english', %(query)s)
              ) AS rank
            FROM artifacts
            WHERE artifact_id = %(artifact_id)s
              AND to_tsvector('english', search_text || ' ' || summary)
                  @@ websearch_to_tsquery('english', %(query)s)
            ORDER BY rank DESC
            LIMIT %(limit)s
            """,
            {"artifact_id": record.artifact_id, "query": query, "limit": limit},
        ).fetchall()
        return [_row_to_hit(row, query) for row in rows]

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
        session_id = filters.get("session_id") if filters else None
        rows = self.storage.conn.execute(
            """
            SELECT
              artifact_id,
              reference,
              namespace,
              session_id,
              search_text AS content_text,
              ts_rank_cd(
                to_tsvector('english', search_text || ' ' || summary),
                websearch_to_tsquery('english', %(query)s)
              ) AS rank
            FROM artifacts
            WHERE namespace = %(namespace)s
              AND (%(session_id)s::text IS NULL OR session_id = %(session_id)s)
              AND to_tsvector('english', search_text || ' ' || summary)
                  @@ websearch_to_tsquery('english', %(query)s)
            ORDER BY rank DESC
            LIMIT %(limit)s
            """,
            {
                "namespace": namespace,
                "session_id": session_id,
                "query": query,
                "limit": limit,
            },
        ).fetchall()
        return [_row_to_hit(row, query) for row in rows]

    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities(backend_type="postgres", keyword=True, default_mode="keyword")

    def _validate_mode(self, mode: RetrievalMode | None) -> None:
        if mode in {None, "keyword"}:
            return
        raise CapabilityError(f"Postgres backend does not support retrieval mode: {mode}")


def _row_to_hit(row: dict[str, Any], query: str) -> SearchHit:
    return SearchHit(
        artifact_id=row["artifact_id"],
        reference=row["reference"],
        text=snippet_around(row["content_text"], query),
        score=float(row["rank"]),
        retrieval_mode="keyword",
        metadata={"namespace": row["namespace"]},
    )
