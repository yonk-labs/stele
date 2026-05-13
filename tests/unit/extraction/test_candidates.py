"""Tests for the pure extract_candidates core."""

from __future__ import annotations

from stele.extraction.candidates import extract_candidates
from stele.extraction.models import MemoryCandidate
from stele.pii.regex import RegexPIIScrubber


def _scrubber() -> RegexPIIScrubber:
    return RegexPIIScrubber()


SAMPLE = (
    "The 2026 Q1 product launch is on March 15. "
    "Revenue grew 12% year over year. "
    "I prefer dark mode for the dashboard."
)


def test_extract_candidates_returns_memory_candidates() -> None:
    out = extract_candidates(
        text=SAMPLE,
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    assert isinstance(out, list)
    for cand in out:
        assert isinstance(cand, MemoryCandidate)
        assert 0.0 <= cand.confidence <= 1.0
        assert cand.lede_source in {"key_fact", "stat", "metadata", "phrase", "summary"}


def test_extract_candidates_deterministic() -> None:
    a = extract_candidates(
        text=SAMPLE,
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    b = extract_candidates(
        text=SAMPLE,
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_extract_candidates_truncates_to_max() -> None:
    long_text = " ".join(
        f"Fact number {i} is that the year 202{i % 10} mattered."
        for i in range(100)
    )
    out = extract_candidates(
        text=long_text,
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=5,
    )
    assert len(out) <= 5


def test_extract_candidates_empty_text_returns_empty_list() -> None:
    out = extract_candidates(
        text="",
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    assert out == []


def test_extract_candidates_preference_is_classified_via_overlay() -> None:
    out = extract_candidates(
        text="I prefer dark mode.",
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    kinds = {c.kind for c in out}
    assert "preference" in kinds


def test_extract_candidates_overlay_disabled_means_no_overrides() -> None:
    out = extract_candidates(
        text="I prefer dark mode.",
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=False,
        max_candidates=50,
    )
    assert all(c.classifier_path == "type_based" for c in out)
    assert all(c.kind != "preference" for c in out)


def test_extract_candidates_scrubs_pii_in_candidate_text() -> None:
    out = extract_candidates(
        text="Contact alice@example.com for the migration plan.",
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    for cand in out:
        assert "alice@example.com" not in cand.text
