"""Distill `spans` view contract, parametrized across backends.

spans() groups episodes into cross-session topic/task arcs. With an injected
embedder it clusters by summary cosine; with NONE injected the deterministic
fallback is one-episode-per-span. This contract exercises the no-embedder
fallback (no embedder is configured on the backends here) plus an embedder-
injected clustering case, asserting only namespace-local, order-free facts.

Each test uses a UNIQUE namespace because the postgres bench DB is SHARED:
namespace="default" would leak other tests' data and break the assertions.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.distill.episodes import SESSION_SOURCE
from stele.distill.models import SpanItem

BACKENDS = ["memory", "sqlite"]
if os.environ.get("STELE_PG_DSN"):
    BACKENDS.append("postgres")


class _BowEmbedder:
    """Deterministic concept embedder: auth-arc paraphrases land on one axis,
    dashboard on another (orthogonal)."""

    _CONCEPTS: tuple[tuple[str, ...], ...] = (
        ("auth", "token", "refresh", "login", "session"),
        ("dashboard", "widget", "render", "chart"),
    )

    def embed(self, text: str) -> list[float]:
        low = text.lower()
        return [float(sum(low.count(w) for w in concept)) for concept in self._CONCEPTS]


def _stele(tmp_path: Path, backend: str) -> Stele:
    if backend == "memory":
        return Stele.from_config({"backend": {"type": "memory"}})
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
        )
    return Stele.from_config(
        {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}}
    )


def _ingest(s: Stele, *, namespace: str, session_id: str, text: str, when: datetime) -> str:
    stored = s.store(
        content=text,
        namespace=namespace,
        session_id=session_id,
        metadata={"source": SESSION_SOURCE, "session_mtime": when.isoformat()},
    )
    return str(stored.reference)


def _add_episode(s: Stele, ns: str, scope: MemoryScope, sid: str, summary: str,
                 when: datetime) -> str:
    ref = _ingest(s, namespace=ns, session_id=sid, text=sid, when=when)
    s.memory.add(
        text=summary, kind="decision", source_refs=[ref], scope=scope, summary=summary
    )
    return ref


@pytest.mark.parametrize("backend", BACKENDS)
def test_distill_spans_no_embedder_one_per_span(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    try:
        ns = f"ep3-{uuid.uuid4().hex}"  # unique: the postgres bench DB is shared
        scope = MemoryScope(namespace=ns)
        now = datetime.now(UTC)
        refs = {
            _add_episode(s, ns, scope, "a1", "auth token login", now - timedelta(days=1)),
            _add_episode(s, ns, scope, "a2", "auth session token", now),
        }
        view = asyncio.run(s.distill.spans(scope))
        assert view.mode == "spans"
        assert all(isinstance(it, SpanItem) for it in view.items)
        # no embedder -> one span per episode (never errors)
        assert len(view.items) == 2, f"[{backend}] one-per-span fallback"
        assert {r for it in view.items for r in it.refs} == refs
        assert all(len(it.refs) == 1 for it in view.items)
        assert all(it.source_refs for it in view.items)  # evidence carried
    finally:
        s.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_distill_spans_clusters_with_embedder(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    s._distill_embedder = _BowEmbedder()
    try:
        ns = f"ep3-{uuid.uuid4().hex}"  # unique: the postgres bench DB is shared
        scope = MemoryScope(namespace=ns)
        now = datetime.now(UTC)
        a1 = _add_episode(s, ns, scope, "a1", "auth token refresh login", now - timedelta(days=2))
        a2 = _add_episode(s, ns, scope, "a2", "auth session token login", now - timedelta(days=1))
        d1 = _add_episode(s, ns, scope, "d1", "dashboard widget render chart", now)
        view = asyncio.run(s.distill.spans(scope))
        by_refs = {frozenset(it.refs): it for it in view.items}
        # auth paraphrases collapse; dashboard stays separate
        assert frozenset({a1, a2}) in by_refs, f"[{backend}] auth arc clustered"
        assert frozenset({d1}) in by_refs, f"[{backend}] dashboard arc separate"
        assert len(view.items) == 2
    finally:
        s.close()
