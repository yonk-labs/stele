"""Tests for the MemoryExtractor orchestrator (from_text path)."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import ValidationError
from stele.core.memory_record import MemoryScope
from stele.extraction.models import ExtractionReport


def _make_stele() -> Stele:
    return Stele(StashConfig())


def test_from_text_returns_extraction_report() -> None:
    stele = _make_stele()
    report = stele.extract.from_text(
        text="I prefer dark mode. Q1 revenue grew 12%.",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    assert isinstance(report, ExtractionReport)
    assert report.source_refs == ["stele://default/abc"]
    assert report.stats.candidate_count >= 1
    stele.close()


def test_from_text_rejects_empty_source_refs() -> None:
    stele = _make_stele()
    with pytest.raises(ValidationError, match="stele://"):
        stele.extract.from_text(
            text="x",
            source_refs=[],
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()


def test_from_text_rejects_non_stele_refs() -> None:
    stele = _make_stele()
    with pytest.raises(ValidationError, match="stele://"):
        stele.extract.from_text(
            text="x",
            source_refs=["http://example.com/abc"],
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()


def test_from_text_empty_text_returns_empty_accepted() -> None:
    stele = _make_stele()
    report = stele.extract.from_text(
        text="",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    assert report.accepted == []
    assert report.stats.candidate_count == 0
    stele.close()


def test_from_text_accepted_have_stored_ids() -> None:
    stele = _make_stele()
    report = stele.extract.from_text(
        text="I prefer dark mode.",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    for accepted in report.accepted:
        assert accepted.stored_id
        # Confirm the stored memory exists in the store
        stored = stele.memory.get(accepted.stored_id)
        assert stored is not None
        assert stored.text == accepted.candidate.text
    stele.close()
