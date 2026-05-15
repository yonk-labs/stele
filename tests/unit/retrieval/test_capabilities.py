"""Tests for StashCapabilities — Phase 4 fields on the real capability model."""

from __future__ import annotations

from stele.core.capabilities import RetrievalCapabilities, StashCapabilities, StorageCapabilities
from stele.indexing.bakeoff import BakeoffSummary


def test_stash_capabilities_has_phase4_fields() -> None:
    caps = StashCapabilities(
        storage=StorageCapabilities(backend_type="memory", durable=False),
        retrieval=RetrievalCapabilities(backend_type="memory"),
    )
    assert hasattr(caps, "chunk_store_backend")
    assert hasattr(caps, "vector_enabled")
    assert hasattr(caps, "hybrid_enabled")
    assert hasattr(caps, "chunkshop_installed")
    assert hasattr(caps, "chunkshop_version")
    assert hasattr(caps, "bakeoff_summary")
    assert hasattr(caps, "task_backend")
    # Verify correct defaults
    assert caps.chunk_store_backend is None
    assert caps.vector_enabled is False
    assert caps.hybrid_enabled is False
    assert caps.chunkshop_installed is False
    assert caps.chunkshop_version is None
    assert caps.bakeoff_summary is None
    assert caps.task_backend is None


def test_stash_capabilities_bakeoff_summary_typed() -> None:
    caps = StashCapabilities(
        storage=StorageCapabilities(backend_type="memory", durable=False),
        retrieval=RetrievalCapabilities(backend_type="memory"),
        bakeoff_summary=BakeoffSummary(
            source="auto_detected",
            chunker=None,
            embedder=None,
            similarity="cosine",
        ),
    )
    assert caps.bakeoff_summary is not None
    assert caps.bakeoff_summary.source == "auto_detected"
