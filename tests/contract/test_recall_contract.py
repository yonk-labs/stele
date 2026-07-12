"""Cross-backend recall contract — memory + sqlite + postgres."""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope
from stele.recall.episodic import SESSION_SOURCE
from stele.retrieval.temporal import parse_temporal


def _test_namespace() -> str:
    """Isolated namespace for a test run: test_stele_<timestamp>_<random>."""
    return f"test_stele_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def _backend_configs() -> list[tuple[str, dict[str, object]]]:
    configs: list[tuple[str, dict[str, object]]] = [
        ("memory", {"backend": {"type": "memory"}}),
    ]
    tmp = Path(tempfile.mkdtemp())
    configs.append(
        ("sqlite", {"backend": {"type": "sqlite", "path": str(tmp / "stele.db")}})
    )
    pg_dsn = os.environ.get("STELE_PG_DSN")
    if pg_dsn:
        configs.append(("postgres", {"backend": {"type": "postgres", "dsn": pg_dsn}}))
    return configs


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_recall_contract_memory_then_artifact(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        stele.memory.add(
            text="user prefers dark mode for the dashboard",
            kind="preference",
            source_refs=["stele://default/abc"],
            scope=MemoryScope(user_id="contract"),
        )
        result = stele.recall(
            query="dark mode",
            scope=MemoryScope(user_id="contract"),
        )
        # Structural invariants
        assert result.strategy_used in {
            "memory_search",
            "artifact_search",
            "digest",
            "adaptive",
            "abstain",
        }
        assert isinstance(result.stats.memory_searches, int)
        assert isinstance(result.context, str)
    finally:
        stele.close()


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_recall_contract_forced_scope(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        stored = stele.store(
            content="The migration deadline is 2026-06-30. " * 10,
            namespace="default",
        )
        result = stele.recall.artifact_search(
            query="migration",
            scope=MemoryScope(user_id="contract"),
            artifact_id=stored.artifact_id,
        )
        for c in result.citations:
            assert c.reference == stored.reference, (
                f"forced scope leaked: got {c.reference}, expected {stored.reference}"
            )
    finally:
        stele.close()


def _ingest_episode(
    stele: Stele,
    *,
    namespace: str,
    session_id: str,
    text: str,
    when: datetime,
) -> str:
    stored = stele.store(
        content=text,
        namespace=namespace,
        session_id=session_id,
        metadata={"source": SESSION_SOURCE, "session_mtime": when.isoformat()},
    )
    return stored.reference


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_recall_contract_episodic_returns_in_window_episode_with_memories(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        ns = f"ep-{uuid.uuid4().hex}"  # unique: the postgres bench DB is shared
        scope = MemoryScope(namespace=ns)
        now = datetime.now(UTC)
        _, window = parse_temporal("what was I building last week", now)
        assert window is not None and window.after is not None
        in_window = window.after + timedelta(hours=12)

        recent_ref = _ingest_episode(
            stele,
            namespace=ns,
            session_id="sess-recent",
            text="building the dashboard widget layout",
            when=now,
        )
        older_ref = _ingest_episode(
            stele,
            namespace=ns,
            session_id="sess-older",
            text="building the dashboard widget layout",
            when=in_window,
        )
        older_mem = stele.memory.add(
            text="decided to build the widget layout last week",
            kind="decision",
            source_refs=[older_ref],
            scope=scope,
        )
        stele.memory.add(
            text="note for the recent session",
            kind="fact",
            source_refs=[recent_ref],
            scope=scope,
        )

        result = stele.recall.episodic(
            query="what was I building last week", scope=scope
        )
        assert result.strategy_used == "episodic"
        assert result.episodes, f"[{backend_name}] expected episodes"
        top = result.episodes[0]
        assert top.ref == older_ref, (
            f"[{backend_name}] in-window episode should rank first"
        )
        assert older_mem.record.id in {m.id for m in top.memories}, (
            f"[{backend_name}] episode must carry its back-linked memories"
        )
    finally:
        stele.close()


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_recall_hides_retracted(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    """Retraction is stele's most consequential axis: once a memory is
    retracted it must stop showing up in recall. Round-trips
    add -> recall (hit) -> retract -> recall (miss), isolated in a
    throwaway test_stele_ namespace."""
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        ns = _test_namespace()
        scope = MemoryScope(namespace=ns)
        added = stele.memory.add(
            text="the on-call rotation runs Monday through Friday",
            kind="fact",
            source_refs=[f"stele://{ns}/a"],
            scope=scope,
        )

        before = stele.recall(
            query="on-call rotation", scope=scope, strategy="memory_search"
        )
        assert added.record.id in {c.id for c in before.citations}, (
            f"[{backend_name}] expected the new memory to be recalled before retraction"
        )

        stele.memory.retract(added.record.id, reason="test_stele cleanup: superseded rotation")

        after = stele.recall(
            query="on-call rotation", scope=scope, strategy="memory_search"
        )
        assert added.record.id not in {c.id for c in after.citations}, (
            f"[{backend_name}] retracted memory must be hidden from recall"
        )
    finally:
        # Cleanup: hard-delete the throwaway namespace (memory backend has no
        # purge_namespace support; sqlite/postgres do).
        with contextlib.suppress(Exception):
            stele.memory.delete_namespace(ns)
        stele.close()


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_purge_superseded_removes_expired_rows_but_keeps_recent(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    """purge_superseded hard-deletes only superseded rows whose validity
    window ended strictly before the caller's cutoff -- an earlier cutoff
    must purge nothing, a later one must remove exactly the superseded row."""
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        ns = _test_namespace()
        scope = MemoryScope(namespace=ns)
        old = stele.memory.add(
            text="v1: the API rate limit is 100/min",
            kind="fact",
            source_refs=[f"stele://{ns}/a"],
            scope=scope,
        )
        stele.memory.add(
            text="v2: the API rate limit is 500/min",
            kind="fact",
            source_refs=[f"stele://{ns}/a"],
            scope=scope,
            supersedes=[old.record.id],
        )
        superseded = stele.memory.get(old.record.id)
        assert superseded is not None and superseded.status == "superseded"

        cutoff_before = datetime.now(UTC) - timedelta(days=1)
        removed_none = stele.memory.purge_superseded(cutoff_before)
        assert removed_none == 0, (
            f"[{backend_name}] a cutoff before the supersession must purge nothing"
        )
        assert stele.memory.get(old.record.id) is not None

        cutoff_after = datetime.now(UTC) + timedelta(days=1)
        removed = stele.memory.purge_superseded(cutoff_after)
        assert removed == 1, f"[{backend_name}] expected exactly the superseded row removed"
        assert stele.memory.get(old.record.id) is None
    finally:
        with contextlib.suppress(Exception):
            stele.memory.delete_namespace(ns)
        stele.close()


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_recall_contract_episodic_wrong_window_falls_back(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    """A window that matches no candidate must fall back to the unfiltered
    rank rather than returning nothing (anti-backfire rule)."""
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        ns = f"ep-{uuid.uuid4().hex}"  # unique: the postgres bench DB is shared
        scope = MemoryScope(namespace=ns)
        now = datetime.now(UTC)
        refs = [
            _ingest_episode(
                stele,
                namespace=ns,
                session_id=f"sess-{i}",
                text="building the dashboard widget layout",
                when=now - timedelta(hours=i),
            )
            for i in range(2)
        ]
        for ref in refs:
            stele.memory.add(
                text=f"note for {ref}",
                kind="fact",
                source_refs=[ref],
                scope=scope,
            )

        result = stele.recall.episodic(
            query="what was I building last week", scope=scope, hard_temporal=True
        )
        assert result.episodes, (
            f"[{backend_name}] empty window must fall back, not return nothing"
        )
        assert {ep.ref for ep in result.episodes} == set(refs)
    finally:
        stele.close()
