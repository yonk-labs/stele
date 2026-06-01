"""PII scrub on memory text (SC-009)."""

from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {
            "backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")},
            "pii": {"enabled": True},  # scrubbing is opt-in; this suite tests it
        }
    )


def test_email_in_memory_is_scrubbed_on_add(stele: Stele) -> None:
    r = stele.memory.add(
        text="contact alice@example.com about ticket",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    assert "alice@example.com" not in r.record.text
    assert "EMAIL" in r.record.pii_flags


def test_scrubbed_text_persists_through_search(stele: Stele) -> None:
    stele.memory.add(
        text="contact bob@example.com today",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    hits = stele.memory.search(
        MemoryQuery(query="contact", scope=MemoryScope(user_id="alice"))
    )
    assert len(hits) == 1
    assert "bob@example.com" not in hits[0].text
