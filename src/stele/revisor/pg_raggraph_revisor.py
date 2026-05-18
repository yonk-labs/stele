"""pg-raggraph-backed Revisor. The ONLY module that imports/awaits
pg-raggraph. Mirrors the Phase-4 chunkshop adapter: lazy import +
OptionalDependencyError, config synthesized internally (DSN reused; no
os.environ), async->sync bridge contained HERE, no native object escapes
(every result -> package-owned GraphHit). API verified in Task-0 recon."""

from __future__ import annotations

import asyncio
from datetime import datetime
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

from stele.core.exceptions import OptionalDependencyError, ValidationError
from stele.revisor.base import GraphHit, RetractedBehavior

if TYPE_CHECKING:
    from collections.abc import Coroutine

_PIP_HINT = "pip install 'stele-core[postgres-graph]'"


def _require_tz_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationError(
            f"{field} must be timezone-aware (pg-raggraph rejects naive datetimes)"
        )
    return value


class PgRaggraphRevisor:
    """active=True. Construction fails loudly if the extra is absent."""

    active = True

    def __init__(
        self,
        *,
        dsn: str,
        namespace: str,
        evolution_tier: str,
        fact_extractor: str = "none",
        llm_base_url: str | None = None,
        llm_model: str | None = None,
        llm_api_key: str = "",
        query_mode: str = "smart",
        rerank: bool = False,
    ) -> None:
        if find_spec("pg_raggraph") is None:  # pragma: no cover - env-dependent
            raise OptionalDependencyError(
                f"pg-raggraph required for living-knowledge graph search; {_PIP_HINT}"
            )
        if not dsn:
            raise ValidationError("graph projection requires a Postgres backend.dsn")
        self._dsn = dsn
        self._ns = namespace
        self._tier = evolution_tier
        self._fact_extractor = fact_extractor
        self._llm_base_url = llm_base_url
        self._llm_model = llm_model
        self._llm_api_key = llm_api_key
        # Opt-in, non-default: LLM graph extraction fires only when
        # explicitly selected AND an endpoint is supplied. Default ("none")
        # keeps skip_extraction=True — stele's LLM-free invariant holds for
        # the default path; the LLM lives only inside this adapter.
        self._llm_extraction = fact_extractor == "llm" and bool(llm_base_url)
        # Opt-in graph-query tuning. Default ("smart"/False) is the
        # untuned path; with a real graph, ("hybrid"/True) is the
        # documented retrieval lever.
        self._query_mode = query_mode
        self._rerank = rerank

    # --- async->sync bridge (lives ONLY here; DC-P5-2) ---
    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run(coro)

    def _cfg(
        self, retracted_behavior: RetractedBehavior, supersession_behavior: str
    ) -> dict[str, Any]:
        cfg: dict[str, Any] = dict(
            namespace=self._ns,
            embedding_provider="local",
            skip_extraction=not self._llm_extraction,
            evolution_tier=self._tier,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
            fact_extractor=self._fact_extractor,
        )
        if self._llm_extraction:
            cfg["llm_base_url"] = self._llm_base_url
            if self._llm_model:
                cfg["llm_model"] = self._llm_model
            cfg["llm_api_key"] = self._llm_api_key
        return cfg

    def _graphrag(self, **cfg: Any) -> Any:
        from pg_raggraph import GraphRAG

        return GraphRAG(self._dsn, **cfg)

    def ingest_evidence(
        self,
        *,
        stele_ref: str,
        text: str,
        namespace: str,
        effective_from: datetime | None = None,
        session_id: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        if effective_from is not None:
            effective_from = _require_tz_aware(effective_from, "effective_from")
        meta: dict[str, object] = {"stele_ref": stele_ref, "namespace": namespace}
        if effective_from is not None:
            meta["effective_from"] = effective_from
        if session_id is not None:
            meta["session_id"] = session_id
        if extra:
            meta.update(extra)

        async def _op() -> None:
            async with self._graphrag(
                **self._cfg("surface_both", "surface_both")
            ) as rag:
                await rag.ingest_records(
                    [
                        {
                            "text": text,
                            "source_id": stele_ref,
                            "metadata": meta,
                            "skip_llm": not self._llm_extraction,
                        }
                    ],
                    namespace=namespace,
                )

        self._run(_op())

    def supersede(
        self, *, old_ref: str, new_ref: str, reason: str | None = None
    ) -> int:
        async def _op() -> int:
            async with self._graphrag(
                **self._cfg("surface_both", "prefer_new")
            ) as rag:
                res = await rag.supersede(
                    old_source_path=old_ref,
                    new_source_path=new_ref,
                    reason=reason,
                    namespace=self._ns,
                )
            return int(res.get("updated", 0))

        return int(self._run(_op()))

    def retract(
        self, *, stele_ref: str, reason: str = "", retracted_at: datetime | None = None
    ) -> int:
        if retracted_at is not None:
            retracted_at = _require_tz_aware(retracted_at, "retracted_at")

        async def _op() -> int:
            async with self._graphrag(
                **self._cfg("surface_both", "surface_both")
            ) as rag:
                res = await rag.retract(
                    source_path=stele_ref,
                    reason=reason,
                    retracted_at=retracted_at,
                    namespace=self._ns,
                )
            return int(res.get("retracted_count", 0))

        return int(self._run(_op()))

    def _to_hit(self, c: Any) -> GraphHit:
        meta = c.metadata or {}
        ref = meta.get("stele_ref") or c.document_source or ""
        cid = c.chunk_id
        return GraphHit(
            stele_ref=str(ref),
            text=c.content,
            score=float(c.score),
            chunk_id=str(cid) if cid is not None else None,
            retracted=bool(c.retracted) if c.retracted is not None else False,
            version_label=c.version_label,
            effective_from=c.effective_from,
            effective_to=c.effective_to,
            superseded_by_id=c.superseded_by_id,
        )

    def search_current(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        async def _op() -> list[GraphHit]:
            async with self._graphrag(
                **self._cfg(retracted_behavior, "prefer_new")
            ) as rag:
                res = await rag.query(
                    query,
                    mode=self._query_mode,
                    namespace=namespace,
                    version_filter=version_filter,
                    rerank=self._rerank,
                )
            return [self._to_hit(c) for c in res.chunks][:limit]

        return list(self._run(_op()))

    def search_as_of(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        as_of: datetime,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        as_of = _require_tz_aware(as_of, "as_of")

        async def _op() -> list[GraphHit]:
            async with self._graphrag(
                **self._cfg(retracted_behavior, "prefer_new")
            ) as rag:
                res = await rag.query(
                    query,
                    mode=self._query_mode,
                    namespace=namespace,
                    as_of=as_of,
                    version_filter=version_filter,
                    rerank=self._rerank,
                )
            return [self._to_hit(c) for c in res.chunks][:limit]

        return list(self._run(_op()))

    def close(self) -> None:
        return None
