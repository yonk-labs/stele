"""Tests for the Capabilities model — Phase 4 fields exist."""

from __future__ import annotations

from stele.core.artifact import Capabilities
from stele.indexing.bakeoff import BakeoffSummary


def test_capabilities_has_phase4_fields() -> None:
    caps = Capabilities()
    assert hasattr(caps, "chunk_store_backend")
    assert hasattr(caps, "vector_enabled")
    assert hasattr(caps, "hybrid_enabled")
    assert hasattr(caps, "chunkshop_installed")
    assert hasattr(caps, "chunkshop_version")
    assert hasattr(caps, "bakeoff_summary")
    assert hasattr(caps, "task_backend")


def test_capabilities_bakeoff_summary_typed() -> None:
    caps = Capabilities(
        bakeoff_summary=BakeoffSummary(
            source="auto_detected",
            chunker=None,
            embedder=None,
            similarity="cosine",
        )
    )
    assert caps.bakeoff_summary is not None
    assert caps.bakeoff_summary.source == "auto_detected"
