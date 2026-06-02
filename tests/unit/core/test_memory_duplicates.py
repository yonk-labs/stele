"""Duplicate detection (SC-006)."""

from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_first_add_has_no_duplicate(stele: Stele) -> None:
    r = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    assert r.duplicate_of is None


def test_second_identical_add_merges_into_existing(stele: Stele) -> None:
    """Re-observing the exact assertion in-scope confirms the existing row
    (bumps confirmations) instead of inserting a twin."""
    r1 = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    assert r1.record.confirmations == 1
    r2 = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="alice"),
    )
    # Same row, not a twin: duplicate_of points at it AND it IS that row.
    assert r2.duplicate_of == r1.record.id
    assert r2.record.id == r1.record.id
    assert r2.record.confirmations == 2
    assert r2.record.last_confirmed is not None
    # Exactly one row survives.
    listed = stele.memory.list(MemoryScope(user_id="alice"), limit=50)
    assert [m.id for m in listed] == [r1.record.id]


def test_different_scope_not_duplicate(stele: Stele) -> None:
    stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    r = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="bob"),
    )
    assert r.duplicate_of is None
