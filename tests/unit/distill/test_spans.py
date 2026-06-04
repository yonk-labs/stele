"""Unit tests for the spans distill view (Phase 3 of episodic recall).

spans() groups episodes into cross-session topic/task arcs by clustering on the
embedding similarity of their summaries (reusing base.consolidate's greedy
cosine-threshold pattern). With NO embedder injected the deterministic fallback
is one-episode-per-span. Computed on read, no store mutation.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.distill.episodes import SESSION_SOURCE
from stele.distill.models import SpanItem


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


class _BowEmbedder:
    """Deterministic concept embedder: paraphrases of one arc land on the same
    axis (high cosine), distinct arcs are orthogonal. Mirrors the stub in
    test_behavioral.py."""

    _CONCEPTS: tuple[tuple[str, ...], ...] = (
        ("auth", "token", "refresh", "login", "session"),  # auth arc
        ("dashboard", "widget", "render", "chart"),         # dashboard arc
        ("deploy", "release", "ci", "pipeline"),            # release arc
    )

    def embed(self, text: str) -> list[float]:
        low = text.lower()
        return [float(sum(low.count(w) for w in concept)) for concept in self._CONCEPTS]


def _add_episode(s: Stele, ns: str, scope: MemoryScope, sid: str, summary: str,
                 when: datetime) -> str:
    ref = _ingest(s, namespace=ns, session_id=sid, text=sid, when=when)
    s.memory.add(
        text=summary, kind="decision", source_refs=[ref], scope=scope, summary=summary
    )
    return ref


def test_spans_clusters_similar_episodes_into_one_span() -> None:
    s = _stele()
    s._distill_embedder = _BowEmbedder()
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    # Two auth-arc sessions (paraphrases) + one dashboard session.
    a1 = _add_episode(s, ns, scope, "a1", "auth token refresh login", now - timedelta(days=3))
    a2 = _add_episode(s, ns, scope, "a2", "auth session token login", now - timedelta(days=2))
    d1 = _add_episode(s, ns, scope, "d1", "dashboard widget render chart", now - timedelta(days=1))

    view = asyncio.run(s.distill.spans(scope))
    assert view.mode == "spans"
    assert all(isinstance(it, SpanItem) for it in view.items)
    # The two auth episodes collapse into one span; dashboard stays separate.
    assert len(view.items) == 2, [it.summary for it in view.items]
    spans_by_refs = {frozenset(it.refs): it for it in view.items}
    assert frozenset({a1, a2}) in spans_by_refs
    assert frozenset({d1}) in spans_by_refs
    auth_span = spans_by_refs[frozenset({a1, a2})]
    assert set(auth_span.session_ids) == {"a1", "a2"}
    # the span's time range brackets both members
    assert auth_span.started is not None and auth_span.ended is not None
    assert auth_span.started < auth_span.ended


def test_spans_keeps_distinct_episodes_separate() -> None:
    s = _stele()
    s._distill_embedder = _BowEmbedder()
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    _add_episode(s, ns, scope, "a", "auth token login", now - timedelta(days=2))
    _add_episode(s, ns, scope, "d", "dashboard widget render", now - timedelta(days=1))
    _add_episode(s, ns, scope, "r", "deploy release ci pipeline", now)

    view = asyncio.run(s.distill.spans(scope))
    # three orthogonal arcs -> three single-member spans
    assert len(view.items) == 3
    assert all(len(it.refs) == 1 for it in view.items)


def test_spans_no_embedder_falls_back_to_one_per_span() -> None:
    s = _stele()  # no embedder injected
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    refs = [
        _add_episode(s, ns, scope, "a1", "auth token login", now - timedelta(days=2)),
        _add_episode(s, ns, scope, "a2", "auth session token", now - timedelta(days=1)),
    ]
    view = asyncio.run(s.distill.spans(scope))
    # Even though these would cluster WITH an embedder, the no-embedder fallback
    # gives one span per episode -- never errors.
    assert len(view.items) == 2
    assert {r for it in view.items for r in it.refs} == set(refs)
    assert all(len(it.refs) == 1 for it in view.items)


def test_spans_span_id_is_deterministic_and_carries_evidence() -> None:
    s = _stele()
    s._distill_embedder = _BowEmbedder()
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    _add_episode(s, ns, scope, "a1", "auth token refresh", now - timedelta(days=1))
    _add_episode(s, ns, scope, "a2", "auth login session", now)

    v1 = asyncio.run(s.distill.spans(scope))
    v2 = asyncio.run(s.distill.spans(scope))
    ids1 = sorted(it.span_id for it in v1.items)
    ids2 = sorted(it.span_id for it in v2.items)
    assert ids1 == ids2  # deterministic across runs
    assert all(it.span_id.startswith("span-") for it in v1.items)
    assert all(it.source_refs for it in v1.items)  # evidence carried


def test_spans_llm_refine_tightens_span_summary() -> None:
    s = _stele()
    s._distill_embedder = _BowEmbedder()
    s._distill_llm = lambda prompt: "Completed the auth refactor across two sessions."
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    _add_episode(s, ns, scope, "a1", "auth token refresh", now - timedelta(days=1))
    _add_episode(s, ns, scope, "a2", "auth login session", now)

    view = asyncio.run(s.distill.spans(scope))
    assert view.used_llm
    auth_span = next(it for it in view.items if len(it.refs) == 2)
    assert auth_span.summary == "Completed the auth refactor across two sessions."


def test_spans_llm_bad_output_falls_back_to_deterministic() -> None:
    s = _stele()
    s._distill_embedder = _BowEmbedder()

    def _bad_llm(prompt: str) -> str:
        raise RuntimeError("model exploded")

    s._distill_llm = _bad_llm
    ns = f"ep3-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    _add_episode(s, ns, scope, "a1", "auth token refresh", now - timedelta(days=1))
    _add_episode(s, ns, scope, "a2", "auth login session", now)

    view = asyncio.run(s.distill.spans(scope))
    assert view.used_llm  # synthesis was allowed
    auth_span = next(it for it in view.items if len(it.refs) == 2)
    # deterministic fallback composed from member summaries
    assert "auth token refresh" in auth_span.summary
    assert "auth login session" in auth_span.summary
    assert "[2 sessions]" in auth_span.summary
