"""Idempotent section editing for shared agent docs (CLAUDE.md, AGENTS.md, GEMINI.md).

A section is delimited by `marker` (a markdown heading like '## stele') and
extends until the next heading at the same or shallower level, or end of file.
Upserts replace in place; removes strip the section; user-authored content
between sections is preserved.
"""

from __future__ import annotations

import re
from pathlib import Path


class SectionConflictError(RuntimeError):
    """Raised when a document contains two markers with the same name."""


def _heading_level(marker: str) -> int:
    return len(marker) - len(marker.lstrip("#"))


def _next_heading_pattern(level: int) -> re.Pattern[str]:
    return re.compile(rf"^#{{1,{level}}} ", re.MULTILINE)


def _find_section(text: str, marker: str) -> tuple[int, int] | None:
    """Return (start, end) of the section bounded by marker, or None."""
    indices = [
        m.start()
        for m in re.finditer(rf"^{re.escape(marker)}(?=\n|$)", text, re.MULTILINE)
    ]
    if not indices:
        return None
    if len(indices) > 1:
        raise SectionConflictError(
            f"Multiple {marker!r} sections found at offsets {indices}; refusing to act"
        )
    start = indices[0]
    after = start + len(marker)
    level = _heading_level(marker)
    next_match = _next_heading_pattern(level).search(text, after)
    end = next_match.start() if next_match else len(text)
    return start, end


def upsert_section(path: Path, *, marker: str, content: str) -> None:
    """Insert or replace the section at `marker` with `content`.

    `content` must include the marker line as its first line.
    """
    if not content.endswith("\n"):
        content = content + "\n"

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return

    text = path.read_text()
    located = _find_section(text, marker)

    if located is None:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        path.write_text(text + sep + content)
        return

    start, end = located
    new_text = text[:start] + content + text[end:]
    path.write_text(new_text)


def remove_section(path: Path, *, marker: str) -> None:
    if not path.exists():
        return
    text = path.read_text()
    located = _find_section(text, marker)
    if located is None:
        return
    start, end = located
    new_text = text[:start] + text[end:]
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    path.write_text(new_text)
