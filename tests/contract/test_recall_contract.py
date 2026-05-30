"""Cross-backend recall contract — memory + sqlite + postgres."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


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
