"""Digest strategy + indexing-gated default."""

from __future__ import annotations

import warnings

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def _stash(config_dict: dict[str, object]) -> Stele:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Stele(StashConfig.load(config_dict))


_INDEXED = {
    "backend": {"type": "memory"},
    "indexing": {"mode": "sync", "provider": "chunkshop"},
}


def test_digest_is_default_when_indexing_enabled() -> None:
    stele = _stash(_INDEXED)
    try:
        assert stele.recall._deps.config.default_strategy == "digest"
    finally:
        stele.close()


def test_default_unchanged_when_indexing_skipped() -> None:
    stele = _stash({"backend": {"type": "memory"}, "indexing": {"mode": "skip"}})
    try:
        assert stele.recall._deps.config.default_strategy == "adaptive"
    finally:
        stele.close()


def test_explicit_default_strategy_is_respected() -> None:
    # An explicit recall.default_strategy must win over the indexing-gated auto-digest.
    stele = _stash({**_INDEXED, "recall": {"default_strategy": "adaptive"}})
    try:
        assert stele.recall._deps.config.default_strategy == "adaptive"
    finally:
        stele.close()


def test_digest_packs_summary_and_chunks() -> None:
    stele = _stash(_INDEXED)
    try:
        stored = stele.store(
            content="The migration deadline is 2026-06-30. " * 12,
            namespace="default",
        )
        result = stele.recall(
            query="migration deadline",
            scope=MemoryScope(user_id="t"),
            strategy="digest",
            artifact_id=stored.artifact_id,
        )
        assert result.strategy_used == "digest"
        assert result.context
        assert "2026-06-30" in result.context
        # Packed shape: lede summary block + the raw top chunks section.
        assert "Retrieved Chunks" in result.context
        assert result.citations
    finally:
        stele.close()
