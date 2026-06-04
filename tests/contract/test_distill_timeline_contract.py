"""Distill `timeline` view contract, parametrized across backends.

timeline() returns the scope's episodes ordered OLDEST-FIRST (the narrative
sequence), within an optional since/until window, optionally query-filtered.

Each test uses a UNIQUE namespace because the postgres bench DB is SHARED:
namespace="default" would leak other tests' data and break the exact-set
assertions. Ordering is anchored on explicit session_mtime values (not
insertion order), so the oldest-first contract is deterministic under leakage.
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


def _ingest(s: Stele, *, namespace: str, session_id: str, text: str, when: datetime) -> str:
    stored = s.store(
        content=text,
        namespace=namespace,
        session_id=session_id,
        metadata={"source": SESSION_SOURCE, "session_mtime": when.isoformat()},
    )
    return str(stored.reference)


@pytest.mark.parametrize("backend", BACKENDS)
def test_distill_timeline_orders_oldest_first(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    try:
        ns = f"ep3-{uuid.uuid4().hex}"  # unique: the postgres bench DB is shared
        scope = MemoryScope(namespace=ns)
        base = datetime(2026, 5, 20, tzinfo=UTC)

        old_ref = _ingest(
            s, namespace=ns, session_id="old", text="old", when=base - timedelta(days=10)
        )
        new_ref = _ingest(s, namespace=ns, session_id="new", text="new", when=base)
        for ref in (new_ref, old_ref):  # insert newest first, on purpose
            s.memory.add(
                text=f"decision {ref}", kind="decision", source_refs=[ref],
                scope=scope, summary=f"decision {ref}",
            )

        view = asyncio.run(s.distill.timeline(scope))
        assert view.mode == "timeline"
        ordered = [it.ref for it in view.items]
        # oldest-first regardless of insertion order
        assert ordered == [old_ref, new_ref], f"[{backend}] oldest-first"
        assert all(isinstance(it, EpisodeItem) for it in view.items)
        assert all(it.source_refs for it in view.items)
    finally:
        s.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_distill_timeline_query_filter(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    try:
        ns = f"ep3-{uuid.uuid4().hex}"  # unique: the postgres bench DB is shared
        scope = MemoryScope(namespace=ns)
        now = datetime.now(UTC)

        auth_ref = _ingest(s, namespace=ns, session_id="auth", text="auth", when=now)
        dash_ref = _ingest(
            s, namespace=ns, session_id="dash", text="dash", when=now - timedelta(days=1)
        )
        s.memory.add(
            text="switched the auth token store", kind="decision",
            source_refs=[auth_ref], scope=scope, summary="auth token refactor",
        )
        s.memory.add(
            text="dashboard renders widgets", kind="fact",
            source_refs=[dash_ref], scope=scope, summary="dashboard widget rendering",
        )

        view = asyncio.run(s.distill.timeline(scope, query="auth token"))
        refs = {it.ref for it in view.items}
        assert auth_ref in refs, f"[{backend}] query-relevant episode kept"
        assert dash_ref not in refs, f"[{backend}] irrelevant episode filtered"
    finally:
        s.close()
