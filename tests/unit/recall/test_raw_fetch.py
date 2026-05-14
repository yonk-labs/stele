"""Tests for RawFetchStrategy."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import PIIBlockedError, ValidationError
from stele.core.memory_record import MemoryScope


def test_raw_fetch_requires_artifact_id() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(ValidationError, match="artifact_id"):
        stele.recall(
            query="x",
            scope=MemoryScope(user_id="alice"),
            strategy="raw_fetch",
            artifact_id=None,
        )
    stele.close()


def test_raw_fetch_returns_full_content_when_pii_raw_fetch_enabled() -> None:
    cfg = StashConfig.load({"pii": {"raw_fetch_enabled": True}})
    stele = Stele(cfg)
    stored = stele.store(content="full content body here", namespace="default")
    result = stele.recall.raw_fetch(
        artifact_id=stored.artifact_id,
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "raw_fetch"
    assert result.stats.fetches == 1
    assert "full content body here" in result.context
    stele.close()


def test_raw_fetch_propagates_pii_blocked_when_disabled() -> None:
    stele = Stele(StashConfig())  # default: pii.raw_fetch_enabled=False
    stored = stele.store(content="anything", namespace="default")
    with pytest.raises(PIIBlockedError):
        stele.recall.raw_fetch(
            artifact_id=stored.artifact_id,
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()
