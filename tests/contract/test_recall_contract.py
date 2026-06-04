"""Cross-backend recall contract — memory + sqlite + postgres."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope
from stele.recall.episodic import SESSION_SOURCE
from stele.retrieval.temporal import parse_temporal


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
        scope = MemoryScope(namespace="default")
        now = datetime.now(UTC)
        _, window = parse_temporal("what was I building last week", now)
        assert window is not None and window.after is not None
        in_window = window.after + timedelta(hours=12)

        recent_ref = _ingest_episode(
            stele,
            namespace="default",
            session_id="sess-recent",
            text="building the dashboard widget layout",
            when=now,
        )
        older_ref = _ingest_episode(
            stele,
            namespace="default",
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
def test_recall_contract_episodic_wrong_window_falls_back(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    """A window that matches no candidate must fall back to the unfiltered
    rank rather than returning nothing (anti-backfire rule)."""
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        scope = MemoryScope(namespace="default")
        now = datetime.now(UTC)
        refs = [
            _ingest_episode(
                stele,
                namespace="default",
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
