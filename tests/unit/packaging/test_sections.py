from __future__ import annotations

from pathlib import Path

import pytest

from stele.packaging.sections import (
    SectionConflictError,
    remove_section,
    upsert_section,
)


def test_upsert_appends_when_marker_absent(tmp_path: Path) -> None:
    doc = tmp_path / "CLAUDE.md"
    doc.write_text("# Existing\n\nUser content here.\n")

    upsert_section(doc, marker="## stele", content="## stele\n\nstele body\n")

    text = doc.read_text()
    assert "User content here." in text
    assert "## stele\n\nstele body\n" in text
    assert text.endswith("\n")


def test_upsert_replaces_existing_section(tmp_path: Path) -> None:
    doc = tmp_path / "AGENTS.md"
    doc.write_text(
        "# Doc\n\n## stele\n\nOLD body\n\n## other\n\nOther content\n"
    )

    upsert_section(doc, marker="## stele", content="## stele\n\nNEW body\n")

    text = doc.read_text()
    assert "OLD body" not in text
    assert "NEW body" in text
    assert "Other content" in text


def test_upsert_preserves_content_before_and_after(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "# Header\n\nIntro paragraph.\n\n## stele\n\nold\n\n## footer\n\nfooter content\n"
    )

    upsert_section(doc, marker="## stele", content="## stele\n\nnew\n")

    text = doc.read_text()
    assert "Intro paragraph." in text
    assert "footer content" in text
    assert "old" not in text


def test_remove_strips_section_only(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "# Header\n\nIntro.\n\n## stele\n\nstele body\n\n## other\n\nOther.\n"
    )

    remove_section(doc, marker="## stele")

    text = doc.read_text()
    assert "stele body" not in text
    assert "Intro." in text
    assert "Other." in text


def test_remove_is_noop_when_marker_absent(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    original = "# Header\n\nNo stele here.\n"
    doc.write_text(original)

    remove_section(doc, marker="## stele")

    assert doc.read_text() == original


def test_upsert_creates_file_when_missing(tmp_path: Path) -> None:
    doc = tmp_path / "new.md"
    assert not doc.exists()

    upsert_section(doc, marker="## stele", content="## stele\n\nbody\n")

    assert doc.read_text() == "## stele\n\nbody\n"


def test_upsert_refuses_ambiguous_double_marker(tmp_path: Path) -> None:
    doc = tmp_path / "corrupt.md"
    doc.write_text("## stele\n\nA\n\n## stele\n\nB\n")

    with pytest.raises(SectionConflictError):
        upsert_section(doc, marker="## stele", content="## stele\n\nnew\n")
