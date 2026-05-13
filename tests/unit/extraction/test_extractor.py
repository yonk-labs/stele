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


def test_from_artifact_derives_source_refs() -> None:
    stele = _make_stele()
    stored = stele.store(
        "I prefer dark mode. Q1 revenue grew 12%.",
        namespace="default",
    )
    report = stele.extract.from_artifact(
        artifact_id=stored.artifact_id,
        scope=MemoryScope(user_id="alice"),
    )
    # FetchResult.reference is the full stele:// URI; derived source_ref
    # equals the StoredResult.reference for the same artifact.
    assert report.source_refs == [stored.reference]
    assert report.stats.candidate_count >= 1
    stele.close()


def test_from_artifact_raises_for_missing_id() -> None:
    from stele.core.exceptions import ArtifactNotFound

    stele = _make_stele()
    with pytest.raises(ArtifactNotFound):
        stele.extract.from_artifact(
            artifact_id="nonexistent_id",
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()


def test_from_messages_auto_stashes_and_extracts() -> None:
    stele = _make_stele()
    report = stele.extract.from_messages(
        messages=[
            {"role": "user", "content": "I prefer dark mode."},
            {"role": "assistant", "content": "Got it. Anything else?"},
        ],
        scope=MemoryScope(user_id="alice"),
    )
    assert len(report.source_refs) == 1
    assert report.source_refs[0].startswith("stele://")
    # The stashed artifact must be retrievable.
    ref = report.source_refs[0]
    fetched = stele.fetch(ref)
    assert "dark mode" in str(fetched.content)
    stele.close()


def test_from_messages_empty_list_returns_empty_report() -> None:
    stele = _make_stele()
    report = stele.extract.from_messages(
        messages=[],
        scope=MemoryScope(user_id="alice"),
    )
    assert report.candidates == []
    assert report.accepted == []
    # source_refs may be [] when nothing was stashed.
    stele.close()


def test_below_threshold_candidates_appear_in_rejected() -> None:
    from stele.core.config import StashConfig

    # Set min_confidence very high so all candidates fall below.
    cfg = StashConfig.load({"extraction": {"min_confidence": 0.99}})
    stele = Stele(cfg)
    report = stele.extract.from_text(
        text="The capital of France is Paris.",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    assert report.accepted == []
    assert report.rejected
    assert all(r.reason == "below_threshold" for r in report.rejected)
    stele.close()


def test_duplicate_candidate_appears_in_rejected() -> None:
    stele = _make_stele()
    text = "I prefer dark mode."
    report_a = stele.extract.from_text(
        text=text,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    # First run should accept the preference.
    assert any(a.candidate.kind == "preference" for a in report_a.accepted)

    # Second run on identical text → duplicate detection fires.
    report_b = stele.extract.from_text(
        text=text,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    duplicates = [r for r in report_b.rejected if r.reason == "duplicate"]
    assert duplicates, "expected at least one duplicate rejection on re-run"
    for dup in duplicates:
        assert dup.duplicate_of is not None
    stele.close()
