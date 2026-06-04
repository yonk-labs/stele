"""Unit tests for the timeline distill view (Phase 3 of episodic recall).

timeline() is the same episodes as episodes(), but ordered OLDEST-FIRST (the
narrative sequence) within an optional since/until window, optionally filtered
to episodes relevant to a query. Computed on read, no store mutation.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.distill.episodes import SESSION_SOURCE
from stele.distill.models import EpisodeItem


def _stele() -> Stele:
    return Stele.from_config({"backend": {"type": "memory"}})


def _ingest(s: Stele, *, namespace: str, session_id: str, text: str, when: datetime) -> str:
    stored = s.store(
        content=text,
        namespace=namespace,
        session_id=session_id,
        metadata={"source": SESSION_SOURCE, "session_mtime": when.isoformat()},
    )
    return str(stored.reference)


def test_timeline_orders_oldest_first() -> None:
    s = _stele()
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    refs = []
    for i in range(3):
        ref = _ingest(
            s, namespace=ns, session_id=f"sess-{i}", text=f"session {i}",
            when=now - timedelta(days=i),
        )
        s.memory.add(
            text=f"decision {i}", kind="decision", source_refs=[ref], scope=scope,
            summary=f"decision {i}",
        )
        refs.append(ref)
    view = asyncio.run(s.distill.timeline(scope))
    assert view.mode == "timeline"
    ordered = [it.ref for it in view.items]
    # i=2 is oldest (now-2d) and must come FIRST; the reverse of episodes().
    assert ordered == [refs[2], refs[1], refs[0]]


def test_timeline_respects_since_until() -> None:
    s = _stele()
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    base = datetime(2026, 5, 15, tzinfo=UTC)
    refs: dict[int, str] = {}
    for delta in (-10, -3, 0):
        when = base + timedelta(days=delta)
        ref = _ingest(s, namespace=ns, session_id=f"s{delta}", text=f"s{delta}", when=when)
        s.memory.add(
            text=f"d{delta}", kind="decision", source_refs=[ref], scope=scope,
            summary=f"d{delta}",
        )
        refs[delta] = ref
    view = asyncio.run(
        s.distill.timeline(scope, since=base - timedelta(days=5), until=base)
    )
    kept = [it.ref for it in view.items]
    # window [base-5d, base]: keeps -3 then 0 (oldest-first), drops -10
    assert kept == [refs[-3], refs[0]]


def test_timeline_query_filter_keeps_relevant_only() -> None:
    s = _stele()
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    ref_auth = _ingest(s, namespace=ns, session_id="auth", text="auth", when=now)
    ref_dash = _ingest(
        s, namespace=ns, session_id="dash", text="dash", when=now - timedelta(days=1)
    )
    s.memory.add(
        text="switched the auth token store", kind="decision", source_refs=[ref_auth],
        scope=scope, summary="auth token refactor decision",
    )
    s.memory.add(
        text="dashboard renders widgets", kind="fact", source_refs=[ref_dash],
        scope=scope, summary="dashboard widget rendering",
    )
    # No embedder injected -> deterministic token-overlap filter.
    view = asyncio.run(s.distill.timeline(scope, query="auth token"))
    kept = {it.ref for it in view.items}
    assert kept == {ref_auth}


def test_timeline_query_filter_semantic_with_embedder() -> None:
    s = _stele()

    class _ConceptEmbedder:
        # auth-axis vs dashboard-axis; orthogonal concepts.
        _AXES = (("auth", "token", "refresh", "login"), ("dashboard", "widget", "render"))

        def embed(self, text: str) -> list[float]:
            low = text.lower()
            return [float(sum(low.count(w) for w in axis)) for axis in self._AXES]

    s._distill_embedder = _ConceptEmbedder()
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    ref_auth = _ingest(s, namespace=ns, session_id="auth", text="auth", when=now)
    ref_dash = _ingest(
        s, namespace=ns, session_id="dash", text="dash", when=now - timedelta(days=1)
    )
    s.memory.add(
        text="token refresh path", kind="decision", source_refs=[ref_auth],
        scope=scope, summary="auth token refresh login",
    )
    s.memory.add(
        text="render widgets", kind="fact", source_refs=[ref_dash],
        scope=scope, summary="dashboard widget render",
    )
    view = asyncio.run(s.distill.timeline(scope, query="login refresh token"))
    assert {it.ref for it in view.items} == {ref_auth}


def test_timeline_no_query_keeps_all() -> None:
    s = _stele()
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    refs = []
    for i in range(2):
        ref = _ingest(
            s, namespace=ns, session_id=f"s{i}", text=f"s{i}", when=now - timedelta(days=i)
        )
        s.memory.add(
            text=f"d{i}", kind="decision", source_refs=[ref], scope=scope, summary=f"d{i}"
        )
        refs.append(ref)
    view = asyncio.run(s.distill.timeline(scope))
    assert {it.ref for it in view.items} == set(refs)
    assert all(isinstance(it, EpisodeItem) for it in view.items)
