"""Tests for SummaryOnlyStrategy."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import ValidationError
from stele.core.memory_record import MemoryScope
from stele.recall.models import RecallRequest


def test_summary_only_returns_artifact_summary() -> None:
    stele = Stele(StashConfig())
    stored = stele.store(content="The quick brown fox jumps over the lazy dog. " * 30, namespace="default")
    result = stele.recall.summary_only(
        artifact_id=stored.artifact_id,
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "summary_only"
    assert result.context
    assert len(result.citations) == 1
    assert result.citations[0].kind == "artifact"
    assert result.citations[0].reference == stored.reference
    assert result.stats.fetches == 1
    stele.close()


def test_summary_only_requires_artifact_id() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(ValidationError, match="artifact_id"):
        stele.recall(
            query="x",
            scope=MemoryScope(user_id="alice"),
            strategy="summary_only",
            artifact_id=None,
        )
    stele.close()
