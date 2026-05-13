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


def test_second_identical_add_flags_duplicate(stele: Stele) -> None:
    r1 = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    r2 = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="alice"),
    )
    assert r2.duplicate_of == r1.record.id


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
