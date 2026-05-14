"""PII flags are inherited from underlying surfaces; recall never re-scrubs."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

PII_TEXT = "Contact alice@example.com or 415-555-0199 for the migration plan."


def test_recall_context_remains_scrubbed() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text=PII_TEXT,
        kind="fact",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    result = stele.recall.memory_search(
        query="migration",
        scope=MemoryScope(user_id="alice"),
    )
    assert "alice@example.com" not in result.context
    assert "415-555-0199" not in result.context
    stele.close()


def test_recall_collects_pii_flags() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text=PII_TEXT,
        kind="fact",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    result = stele.recall.memory_search(
        query="migration",
        scope=MemoryScope(user_id="alice"),
    )
    # Phase 1's scrubber tags emails + phones. Exact flag names depend on
    # RegexPIIScrubber output — just assert non-empty.
    assert result.pii_flags, "expected at least one PII flag inherited from memory"
    stele.close()
