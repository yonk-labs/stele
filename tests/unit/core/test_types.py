"""Tests for RetrievalMode literal expansion in Phase 4."""

from __future__ import annotations

from typing import get_args

from stele.core.types import RetrievalMode


def test_retrieval_mode_includes_vector_and_hybrid() -> None:
    members = set(get_args(RetrievalMode))
    # Phase 4 requires vector and hybrid; graph may also be present from Phase 3.
    assert {"keyword", "vector", "hybrid"} <= members
