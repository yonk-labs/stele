"""Phase 4 public API surface (SC-003, SC-016, SC-023)."""

from __future__ import annotations

import stele


def test_phase4_types_exported() -> None:
    from stele import (
        BakeoffChunker,
        BakeoffConfig,
        BakeoffEmbedder,
        BakeoffSummary,
        IndexTask,
        StashCapabilities,
        TaskStatus,
    )

    for name in (
        "StashCapabilities",
        "BakeoffConfig",
        "BakeoffEmbedder",
        "BakeoffChunker",
        "BakeoffSummary",
        "IndexTask",
        "TaskStatus",
    ):
        assert name in stele.__all__
    # Sanity: they are the real classes, not shadows.
    assert StashCapabilities.__module__ == "stele.core.capabilities"
    assert {BakeoffConfig, BakeoffEmbedder, BakeoffChunker, BakeoffSummary}
    assert IndexTask.__name__ == "IndexTask"
    assert TaskStatus.__name__ == "TaskStatus"


def test_deleted_orphan_capabilities_not_exported() -> None:
    assert "Capabilities" not in stele.__all__
    assert not hasattr(stele, "Capabilities")
