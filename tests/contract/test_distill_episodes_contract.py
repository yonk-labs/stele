"""Distill `episodes` view contract, parametrized across backends.

The seventh distill view groups a scope's active memories by their session
artifact and synthesizes one episode summary per session, computed on read.

Each test uses a UNIQUE namespace because the postgres bench DB is SHARED:
namespace="default" would leak other tests' data and break the exact-set
assertions. No ordering is assumed beyond the documented newest-first contract,
which is anchored on explicit session_mtime values (not insertion order).
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
from stele.distill.models import EpisodeItem

BACKENDS = ["memory", "sqlite"]
if os.environ.get("STELE_PG_DSN"):
    BACKENDS.append("postgres")


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


def _ingest(
    s: Stele, *, namespace: str, session_id: str, text: str, when: datetime
) -> str:
    stored = s.store(
        content=text,
        namespace=namespace,
        session_id=session_id,
        metadata={"source": SESSION_SOURCE, "session_mtime": when.isoformat()},
    )
    return str(stored.reference)


@pytest.mark.parametrize("backend", BACKENDS)
def test_distill_episodes_one_per_session_with_evidence(
    tmp_path: Path, backend: str
) -> None:
    s = _stele(tmp_path, backend)
    try:
        ns = f"ep2-{uuid.uuid4().hex}"  # unique: the postgres bench DB is shared
        scope = MemoryScope(namespace=ns)
        now = datetime.now(UTC)

        ref_a = _ingest(
            s, namespace=ns, session_id="a", text="auth refactor", when=now
        )
        ref_b = _ingest(
            s,
            namespace=ns,
            session_id="b",
            text="dashboard work",
            when=now - timedelta(days=1),
        )
        s.memory.add(
            text="switched to keep120", kind="decision", source_refs=[ref_a],
            scope=scope, summary="switch to keep120",
        )
        s.memory.add(
            text="40 widgets render", kind="fact", source_refs=[ref_b],
            scope=scope, summary="40 widgets",
        )

        view = asyncio.run(s.distill.episodes(scope))
        assert view.mode == "episodes"
        assert {it.ref for it in view.items} == {ref_a, ref_b}, (
            f"[{backend}] one episode per session, exact set in this namespace"
        )
        assert all(isinstance(it, EpisodeItem) for it in view.items)
        assert all(it.source_refs for it in view.items)  # evidence carried
        by_ref = {it.ref: it for it in view.items}
        assert "switch to keep120" in by_ref[ref_a].decisions
        assert "40 widgets" in by_ref[ref_b].facts
    finally:
        s.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_distill_episodes_time_filter(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    try:
        ns = f"ep2-{uuid.uuid4().hex}"  # unique: the postgres bench DB is shared
        scope = MemoryScope(namespace=ns)
        base = datetime(2026, 5, 20, tzinfo=UTC)

        old_ref = _ingest(
            s, namespace=ns, session_id="old", text="old", when=base - timedelta(days=30)
        )
        recent_ref = _ingest(
            s, namespace=ns, session_id="recent", text="recent", when=base
        )
        for ref in (old_ref, recent_ref):
            s.memory.add(
                text=f"decision {ref}", kind="decision", source_refs=[ref],
                scope=scope, summary=f"decision {ref}",
            )

        view = asyncio.run(
            s.distill.episodes(scope, since=base - timedelta(days=5))
        )
        refs = {it.ref for it in view.items}
        assert recent_ref in refs, f"[{backend}] in-window episode kept"
        assert old_ref not in refs, f"[{backend}] out-of-window episode filtered"
    finally:
        s.close()
