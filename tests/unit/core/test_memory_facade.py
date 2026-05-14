"""Memory facade + Stele.memory property."""

import sqlite3
from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory import Memory
from stele.core.memory_record import MemoryQuery, MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_stele_memory_property_returns_memory(stele: Stele) -> None:
    assert isinstance(stele.memory, Memory)


def test_memory_add_then_get(stele: Stele) -> None:
    res = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    fetched = stele.memory.get(res.record.id)
    assert fetched is not None
    assert fetched.text == "user prefers Helix"


def test_memory_add_then_search(stele: Stele) -> None:
    stele.memory.add(
        text="favorite editor is Helix",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    hits = stele.memory.search(
        MemoryQuery(query="editor", scope=MemoryScope(user_id="alice"))
    )
    assert len(hits) == 1


def test_memory_supersession_via_add(stele: Stele) -> None:
    old = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    new = stele.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="alice"),
        supersedes=[old.record.id],
    )
    hits = stele.memory.search(
        MemoryQuery(query="prefers", scope=MemoryScope(user_id="alice"))
    )
    assert [h.id for h in hits] == [new.record.id]


def test_memory_add_persists_supersedes_link(stele: Stele) -> None:
    old = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    new = stele.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="alice"),
        supersedes=[old.record.id],
    )

    fetched = stele.memory.get(new.record.id)

    assert new.record.supersedes == [old.record.id]
    assert fetched is not None
    assert fetched.supersedes == [old.record.id]


def test_stele_close_closes_initialized_memory_store(stele: Stele) -> None:
    memory = stele.memory

    stele.close()

    with pytest.raises(sqlite3.ProgrammingError):
        memory.add(
            text="user prefers Zed",
            kind="preference",
            source_refs=["stele://default/b"],
            scope=MemoryScope(user_id="alice"),
        )


def test_memory_facade_search_with_score_delegates_to_store() -> None:
    from stele import Stele
    from stele.core.config import StashConfig
    from stele.core.memory_record import MemoryScope, ScoredMemoryHit

    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    hits = stele.memory.search_with_score(
        "dark mode",
        scope=MemoryScope(user_id="alice"),
    )
    assert hits
    assert all(isinstance(h, ScoredMemoryHit) for h in hits)
    stele.close()
