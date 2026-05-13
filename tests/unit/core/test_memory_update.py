"""memory.update() rejects text edits (SC-004)."""

from pathlib import Path

import pytest

from stele import Stele
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_update_rejects_text_change(stele: Stele) -> None:
    r = stele.memory.add(
        text="hello",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    with pytest.raises(CapabilityError) as exc:
        stele.memory.update(r.record.id, text="goodbye")
    msg = str(exc.value)
    assert "supersedes" in msg
    assert "preserves history" in msg


def test_update_metadata_succeeds(stele: Stele) -> None:
    r = stele.memory.add(
        text="hello",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    updated = stele.memory.update(r.record.id, metadata={"tag": "x"})
    assert updated.metadata["tag"] == "x"
    assert updated.text == "hello"
