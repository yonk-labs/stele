"""Tests for BakeoffConfig models + loader + overlay."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.indexing.bakeoff import (
    BakeoffChunker,
    BakeoffConfig,
    BakeoffEmbedder,
    BakeoffSummary,
)


def test_bakeoff_embedder_required_fields() -> None:
    e = BakeoffEmbedder(name="test-model", dim=768)
    assert e.dim == 768
    assert e.revision is None


def test_bakeoff_chunker_params_passthrough() -> None:
    c = BakeoffChunker(type="fixed_overlap", params={"window_words": 220, "overlap_words": 60})
    assert c.params["window_words"] == 220


def test_bakeoff_config_full() -> None:
    cfg = BakeoffConfig(
        chunker=BakeoffChunker(type="fixed_overlap", params={"window_words": 220}),
        embedder=BakeoffEmbedder(name="all-MiniLM-L6-v2", dim=384),
        similarity="cosine",
        benchmark_recall_at_5=0.82,
    )
    assert cfg.similarity == "cosine"


def test_bakeoff_config_rejects_unknown_similarity() -> None:
    with pytest.raises(PydanticValidationError):
        BakeoffConfig(
            chunker=BakeoffChunker(type="x", params={}),
            embedder=BakeoffEmbedder(name="x", dim=1),
            similarity="manhattan",  # type: ignore[arg-type]
        )


def test_bakeoff_summary_sources() -> None:
    s = BakeoffSummary(source="auto_detected", chunker=None, embedder=None, similarity="cosine")
    assert s.source == "auto_detected"
