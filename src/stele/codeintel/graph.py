"""Cross-file dependency resolution via pg-raggraph's code graph (slice E).

Wraps ``pg_raggraph.code_graph.code_impact``: given a symbol's fully-qualified
name, returns the symbols it calls (callees) or that call it (callers), resolved
*across files* through the ``CALLS``/``INHERITS``/``IMPLEMENTS`` graph that
pg-raggraph builds from ``chunkshop:symbol_aware`` chunks (``backfill_code_graph``).

This is the cross-file complement to ``codeview``'s in-file resolver. It degrades
to ``[]`` when no graph DB is supplied, so it is a safe optional tier: the bounded
view still works (in-file deps + outline + handles) without it.

Scope: this is the QUERY side, wired and tested. The graph must be ingested first
(pg-raggraph ``backfill_code_graph``), and feeding resolved cross-file callee
*bodies* back into the bounded view (FQN -> file -> span) plus re-indexing on
manifest ``Changes`` is the remaining integration. pg-raggraph is an optional
dependency (the ``postgres-graph`` extra); it is imported lazily, never at module
load, and the ``db`` handle is supplied by the caller.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

ImpactFn = Callable[..., Coroutine[Any, Any, Any]]


class GraphResolver:
    """Cross-file callee/caller resolution over pg-raggraph's code graph.

    ``db`` is a pg-raggraph async DB handle (``fetch_one``/``fetch_all``); pass
    ``None`` to disable (every query returns ``[]``). ``impact_fn`` overrides the
    query function for testing; production uses ``pg_raggraph.code_graph.code_impact``.
    """

    def __init__(
        self,
        db: Any = None,
        *,
        namespace: str = "default",
        impact_fn: ImpactFn | None = None,
    ) -> None:
        self._db = db
        self._namespace = namespace
        self._impact_fn = impact_fn

    def _impact(self, fqn: str, depth: int) -> Any:
        fn = self._impact_fn
        if fn is None:
            from pg_raggraph.code_graph import code_impact

            fn = code_impact
        return asyncio.run(fn(self._db, fqn, namespace=self._namespace, depth=depth))

    def callees(self, fqn: str, *, depth: int = 1) -> list[str]:
        """FQNs that ``fqn`` calls, resolved cross-file. ``[]`` when no graph DB."""
        if self._db is None:
            return []
        impact = self._impact(fqn, depth)
        return [str(edge.fqn) for edge in getattr(impact, "callees", [])]

    def callers(self, fqn: str, *, depth: int = 1) -> list[str]:
        """FQNs that call ``fqn``, resolved cross-file. ``[]`` when no graph DB."""
        if self._db is None:
            return []
        impact = self._impact(fqn, depth)
        return [str(edge.fqn) for edge in getattr(impact, "callers", [])]
