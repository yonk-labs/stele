"""PII scrubbing invariants across the extraction pipeline."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope
from stele.pii.regex import RegexPIIScrubber


PII_INPUT = (
    "Contact alice@example.com or call 415-555-0199 for migration questions. "
    "The deadline is 2026-06-30."
)


def test_extracted_candidates_have_scrubbed_text() -> None:
    stele = Stele(StashConfig())
    report = stele.extract.from_text(
        text=PII_INPUT,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    for cand in report.candidates:
        assert "alice@example.com" not in cand.text
        assert "415-555-0199" not in cand.text
    stele.close()


def test_stored_memory_text_remains_scrubbed() -> None:
    stele = Stele(StashConfig())
    report = stele.extract.from_text(
        text=PII_INPUT,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    for accepted in report.accepted:
        stored = stele.memory.get(accepted.stored_id)
        assert stored is not None
        assert "alice@example.com" not in stored.text
        assert "415-555-0199" not in stored.text
    stele.close()


def test_memory_search_hits_remain_scrubbed() -> None:
    stele = Stele(StashConfig())
    stele.extract.from_text(
        text=PII_INPUT,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    hits = stele.memory.search(
        MemoryQuery(
            query="migration",
            scope=MemoryScope(user_id="alice"),
        )
    )
    for hit in hits:
        assert "alice@example.com" not in hit.text
        assert "415-555-0199" not in hit.text
    stele.close()


def test_double_scrub_is_idempotent() -> None:
    scrubber = RegexPIIScrubber()
    once = scrubber.scrub(PII_INPUT).text
    twice = scrubber.scrub(once).text
    assert once == twice
