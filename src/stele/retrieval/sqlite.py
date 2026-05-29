"""SQLite FTS retrieval."""

from __future__ import annotations

from stele.core.artifact import SearchHit
from stele.core.capabilities import RetrievalCapabilities
from stele.core.exceptions import CapabilityError
from stele.core.reference import Reference
from stele.core.types import RetrievalMode
from stele.retrieval._filters import FilterableRow, record_matches_filters
from stele.retrieval.rank import snippet_around
from stele.storage.sqlite import SQLiteStorageBackend


class SQLiteRetrievalBackend:
    def __init__(self, storage: SQLiteStorageBackend) -> None:
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
            SELECT artifact_id, reference, content, bm25(artifact_fts) AS rank
            FROM artifact_fts
            WHERE artifact_id = ? AND artifact_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (record.artifact_id, _fts_query(query), limit),
        ).fetchall()
        return [
            SearchHit(
                artifact_id=row["artifact_id"],
                reference=row["reference"],
                text=snippet_around(row["content"], query),
                score=float(-row["rank"]),
                retrieval_mode="keyword",
                metadata={"namespace": record.namespace},
            )
            for row in rows
        ]

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
        # Over-fetch more when filters can reject candidates, so the post-filter
        # still yields `limit` rows. Filtering reuses the shared predicate via a
        # FilterableRow shim built from the joined created_at/metadata columns.
        overfetch = limit * (16 if filters else 4)
        rows = self.storage.conn.execute(
            """
            SELECT
              artifact_fts.artifact_id,
              artifact_fts.reference,
              artifact_fts.content,
              bm25(artifact_fts) AS rank,
              artifacts.session_id,
              artifacts.created_at,
              artifacts.metadata_json
            FROM artifact_fts
            JOIN artifacts ON artifacts.artifact_id = artifact_fts.artifact_id
            WHERE artifact_fts.namespace = ? AND artifact_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (namespace, _fts_query(query), overfetch),
        ).fetchall()
        hits: list[SearchHit] = []
        for row in rows:
            shim = FilterableRow.from_sql(
                row["session_id"], row["created_at"], row["metadata_json"]
            )
            if not record_matches_filters(shim, filters):
                continue
            hits.append(
                SearchHit(
                    artifact_id=row["artifact_id"],
                    reference=row["reference"],
                    text=snippet_around(row["content"], query),
                    score=float(-row["rank"]),
                    retrieval_mode="keyword",
                    metadata={"namespace": namespace, **shim.metadata},
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities(backend_type="sqlite", keyword=True, default_mode="keyword")

    def _validate_mode(self, mode: RetrievalMode | None) -> None:
        if mode in {None, "keyword"}:
            return
        raise CapabilityError(f"SQLite backend does not support retrieval mode: {mode}")


def _fts_query(query: str) -> str:
    terms = [term.replace('"', '""') for term in query.split() if term.strip()]
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms)
