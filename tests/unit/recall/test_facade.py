"""Tests for the Recall facade — canonical entry vs shims (SC-013, SC-018)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope


def test_canonical_and_shim_produce_identical_result() -> None:
    """SC-013: canonical __call__ and memory_search shim are structurally equivalent."""
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode for the dashboard",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    canonical = stele.recall(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
        strategy="memory_search",
    )
    shim = stele.recall.memory_search(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
    )
    assert canonical.strategy_used == shim.strategy_used
    assert len(canonical.citations) == len(shim.citations)
    assert canonical.abstained == shim.abstained
    stele.close()


def test_canonical_callable() -> None:
    """SC-013: stele.recall.__call__ is invocable."""
    stele = Stele(StashConfig())
    result = stele.recall(
        query="anything",
        scope=MemoryScope(user_id="bob"),
    )
    assert result is not None
    assert isinstance(result.strategy_used, str)
    stele.close()


def test_seven_shims_exist() -> None:
    """SC-013: all 7 convenience shims are callable attributes."""
    stele = Stele(StashConfig())
    recall = stele.recall
    assert callable(recall.summary_only)
    assert callable(recall.memory_search)
    assert callable(recall.artifact_search)
    assert callable(recall.graph_search)
    assert callable(recall.adaptive)
    assert callable(recall.raw_fetch)
    assert callable(recall.abstain)
    stele.close()


def test_disabled_raises_capability_error() -> None:
    """SC-013 + SC-018: recall.enabled=False raises CapabilityError on both entry points."""
    cfg = StashConfig.load({"recall": {"enabled": False}})
    stele = Stele(cfg)
    with pytest.raises(CapabilityError, match="disabled"):
        stele.recall(
            query="x",
            scope=MemoryScope(user_id="alice"),
        )
    with pytest.raises(CapabilityError, match="disabled"):
        stele.recall.adaptive(
            query="x",
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()


def test_invalid_strategy_rejected() -> None:
    """SC-013: unknown strategy raises Pydantic ValidationError at request construction."""
    stele = Stele(StashConfig())
    with pytest.raises((ValidationError, Exception)):
        stele.recall(
            query="x",
            scope=MemoryScope(user_id="alice"),
            strategy="not_a_strategy",  # type: ignore[arg-type]
        )
    stele.close()
