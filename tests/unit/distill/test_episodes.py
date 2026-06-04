"""Unit tests for the seventh distill view: episodes.

An episode is one session: a session-ingest artifact + the memories that cite
it via source_refs. The view groups the scope's active memories by session and
synthesizes ONE summary per session, computed on read (no store mutation).
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


def _ingest_session(
    s: Stele, *, namespace: str, session_id: str, text: str, when: datetime
) -> str:
    """Store a session-ingest artifact (an episode) and return its ref."""
    stored = s.store(
        content=text,
        namespace=namespace,
        session_id=session_id,
        metadata={"source": SESSION_SOURCE, "session_mtime": when.isoformat()},
    )
    return str(stored.reference)


def test_episodes_groups_memories_by_session_one_summary_each() -> None:
    s = _stele()
    ns = f"ep2-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)

    ref_a = _ingest_session(
        s, namespace=ns, session_id="sess-a", text="auth refactor session", when=now
    )
    ref_b = _ingest_session(
        s,
        namespace=ns,
        session_id="sess-b",
        text="dashboard session",
        when=now - timedelta(days=2),
    )
    # session A produced a decision + a pitfall
    s.memory.add(
        text="switched the token store to keep120",
        kind="decision",
        source_refs=[ref_a],
        scope=scope,
        summary="switch to keep120",
    )
    s.memory.add(
        text="the old refresh path deadlocked under load",
        kind="pitfall",
        source_refs=[ref_a],
        scope=scope,
        summary="refresh path deadlock",
    )
    # session B produced one fact
    s.memory.add(
        text="dashboard renders 40 widgets",
        kind="fact",
        source_refs=[ref_b],
        scope=scope,
        summary="40 widgets",
    )

    view = asyncio.run(s.distill.episodes(scope))
    assert view.mode == "episodes"
    assert not view.used_llm
    assert len(view.items) == 2  # one per session
    assert all(isinstance(it, EpisodeItem) for it in view.items)

    by_ref = {it.ref: it for it in view.items}
    assert set(by_ref) == {ref_a, ref_b}

    a = by_ref[ref_a]
    assert a.session_id == "sess-a"
    assert "switch to keep120" in a.decisions
    assert "refresh path deadlock" in a.pitfalls
    assert "switch to keep120" in a.summary  # composed from the decision
    # source_refs merge the session ref with each memory's refs
    assert ref_a in a.source_refs

    b = by_ref[ref_b]
    assert b.facts == ["40 widgets"]
    assert not b.decisions and not b.pitfalls


def test_episodes_when_prefers_session_mtime() -> None:
    s = _stele()
    ns = f"ep2-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    mtime = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    ref = _ingest_session(
        s, namespace=ns, session_id="sess-1", text="a session", when=mtime
    )
    s.memory.add(
        text="did a thing", kind="decision", source_refs=[ref], scope=scope,
        summary="did a thing",
    )
    view = asyncio.run(s.distill.episodes(scope))
    assert len(view.items) == 1
    item = view.items[0]
    assert isinstance(item, EpisodeItem)
    assert item.when == mtime  # session_mtime, not the store's created_at


def test_episodes_newest_first() -> None:
    s = _stele()
    ns = f"ep2-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    refs = []
    for i in range(3):
        ref = _ingest_session(
            s,
            namespace=ns,
            session_id=f"sess-{i}",
            text=f"session {i}",
            when=now - timedelta(days=i),
        )
        s.memory.add(
            text=f"decision {i}", kind="decision", source_refs=[ref], scope=scope,
            summary=f"decision {i}",
        )
        refs.append(ref)
    view = asyncio.run(s.distill.episodes(scope))
    ordered = [it.ref for it in view.items]
    assert ordered == refs  # i=0 is newest, comes first


def test_episodes_time_filter_since_until() -> None:
    s = _stele()
    ns = f"ep2-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    base = datetime(2026, 5, 15, tzinfo=UTC)
    days = {-10: None, -3: None, 0: None}
    for delta in days:
        when = base + timedelta(days=delta)
        ref = _ingest_session(
            s, namespace=ns, session_id=f"sess{delta}", text=f"s{delta}", when=when
        )
        s.memory.add(
            text=f"d{delta}", kind="decision", source_refs=[ref], scope=scope,
            summary=f"d{delta}",
        )
        days[delta] = ref

    # window: [base - 5d, base] -> keeps the -3 and 0 sessions, drops -10
    view = asyncio.run(
        s.distill.episodes(
            scope, since=base - timedelta(days=5), until=base
        )
    )
    kept = {it.ref for it in view.items}
    assert days[-3] in kept and days[0] in kept
    assert days[-10] not in kept


def test_episodes_skips_sessions_with_no_memories() -> None:
    s = _stele()
    ns = f"ep2-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    # a session artifact with NO back-linked memory is not an episode
    _ingest_session(s, namespace=ns, session_id="empty", text="empty", when=now)
    ref = _ingest_session(
        s, namespace=ns, session_id="full", text="full", when=now
    )
    s.memory.add(
        text="a decision", kind="decision", source_refs=[ref], scope=scope,
        summary="a decision",
    )
    view = asyncio.run(s.distill.episodes(scope))
    assert {it.ref for it in view.items} == {ref}


def test_episodes_llm_refine_tightens_summary() -> None:
    s = _stele()
    s._distill_llm = lambda prompt: "Refactored auth and fixed the deadlock."
    ns = f"ep2-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    ref = _ingest_session(
        s, namespace=ns, session_id="sess-a", text="auth", when=now
    )
    s.memory.add(
        text="switched token store", kind="decision", source_refs=[ref], scope=scope,
        summary="switch token store",
    )
    view = asyncio.run(s.distill.episodes(scope))
    assert view.used_llm
    assert view.items[0].summary == "Refactored auth and fixed the deadlock."


def test_episodes_llm_bad_output_falls_back_to_deterministic() -> None:
    s = _stele()

    def _bad_llm(prompt: str) -> str:
        raise RuntimeError("model exploded")

    s._distill_llm = _bad_llm
    ns = f"ep2-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    ref = _ingest_session(
        s, namespace=ns, session_id="sess-a", text="auth", when=now
    )
    s.memory.add(
        text="switched token store", kind="decision", source_refs=[ref], scope=scope,
        summary="switch token store",
    )
    view = asyncio.run(s.distill.episodes(scope))
    # used_llm flag reflects that synthesis was ALLOWED; the deterministic
    # fallback still produced the composed summary.
    assert view.used_llm
    assert "switch token store" in view.items[0].summary


def test_episodes_llm_empty_output_falls_back() -> None:
    s = _stele()
    s._distill_llm = lambda prompt: "   "  # whitespace-only -> rejected
    ns = f"ep2-{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)
    now = datetime.now(UTC)
    ref = _ingest_session(
        s, namespace=ns, session_id="sess-a", text="auth", when=now
    )
    s.memory.add(
        text="switched token store", kind="decision", source_refs=[ref], scope=scope,
        summary="switch token store",
    )
    view = asyncio.run(s.distill.episodes(scope))
    assert "switch token store" in view.items[0].summary
