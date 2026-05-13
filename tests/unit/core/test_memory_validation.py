"""SC-010 source_refs validation propagates through Memory facade."""

from pathlib import Path

import pytest

from stele import Stele
from stele.core.exceptions import ValidationError
from stele.core.memory_record import MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_empty_source_refs_rejected(stele: Stele) -> None:
    with pytest.raises(ValidationError) as exc:
        stele.memory.add(
            text="hello",
            kind="fact",
            source_refs=[],
            scope=MemoryScope(user_id="alice"),
        )
    assert "stele://" in str(exc.value)


def test_non_stele_source_ref_rejected(stele: Stele) -> None:
    with pytest.raises(ValidationError) as exc:
        stele.memory.add(
            text="hello",
            kind="fact",
            source_refs=["https://example.com"],
            scope=MemoryScope(user_id="alice"),
        )
    assert "stele://" in str(exc.value)
