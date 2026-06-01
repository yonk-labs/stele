"""Postgres full-text retrieval."""

from __future__ import annotations

from typing import Any

from stele.core.artifact import SearchHit
from stele.core.capabilities import RetrievalCapabilities
from stele.core.exceptions import CapabilityError
from stele.core.reference import Reference
from stele.core.types import RetrievalMode
from stele.retrieval._filters import FilterableRow, record_matches_filters
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
        # session_id stays in SQL; created_at/metadata filters are applied via
        # the shared predicate, so over-fetch when such filters are present.
        extra = any(k != "session_id" for k in (filters or {}))
        rows = self.storage.conn.execute(
            """
            SELECT
              artifact_id,
              reference,
              namespace,
              session_id,
              created_at,
              metadata_json,
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
                "limit": limit * 16 if extra else limit,
            },
        ).fetchall()
        hits: list[SearchHit] = []
        for row in rows:
            shim = FilterableRow.from_sql(
                row["session_id"], row["created_at"], row["metadata_json"]
            )
            if not record_matches_filters(shim, filters):
                continue
            hits.append(_row_to_hit(row, query, shim.metadata))
            if len(hits) >= limit:
                break
        return hits

    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities(backend_type="postgres", keyword=True, default_mode="keyword")

    def _validate_mode(self, mode: RetrievalMode | None) -> None:
        if mode in {None, "keyword"}:
            return
        raise CapabilityError(f"Postgres backend does not support retrieval mode: {mode}")


def _row_to_hit(
    row: dict[str, Any], query: str, extra_meta: dict[str, Any] | None = None
) -> SearchHit:
    return SearchHit(
        artifact_id=row["artifact_id"],
        reference=row["reference"],
        text=snippet_around(row["content_text"], query),
        score=float(row["rank"]),
        retrieval_mode="keyword",
        metadata={"namespace": row["namespace"], **(extra_meta or {})},
    )
