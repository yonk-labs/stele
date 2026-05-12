#!/usr/bin/env python3
"""Summarize generated skill-output directories.

The script is intentionally deterministic: it does not call an LLM or external
service. It indexes markdown files, extracts the first TL;DR-style section when
present, lists top-level headings, writes SUMMARY.md, and prints the result.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

SUMMARY_NAME = "SUMMARY.md"


@dataclass(frozen=True)
class DocumentSummary:
    path: Path
    title: str
    tldr: str | None
    headings: list[str]
    line_count: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a skill-output directory")
    parser.add_argument("directory", type=Path, help="Directory containing markdown outputs")
    args = parser.parse_args()

    directory = args.directory
    if not directory.exists() or not directory.is_dir():
        raise SystemExit(f"Not a directory: {directory}")

    docs = [
        _summarize_doc(path)
        for path in sorted(directory.glob("*.md"))
        if path.name != SUMMARY_NAME
    ]
    summary = _render_summary(directory, docs)
    output_path = directory / SUMMARY_NAME
    output_path.write_text(summary, encoding="utf-8")
    print(summary, end="")


def _summarize_doc(path: Path) -> DocumentSummary:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = _extract_headings(lines)
    title = headings[0] if headings else path.stem
    return DocumentSummary(
        path=path,
        title=title,
        tldr=_extract_tldr(lines),
        headings=headings,
        line_count=len(lines),
    )


def _extract_headings(lines: list[str]) -> list[str]:
    headings: list[str] = []
    for line in lines:
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if match:
            headings.append(match.group(2))
    return headings


def _extract_tldr(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        normalized = line.strip().lower()
        if normalized in {"## tl;dr", "# tl;dr", "## summary", "# summary"}:
            body: list[str] = []
            for next_line in lines[index + 1 :]:
                if next_line.startswith("#"):
                    break
                if next_line.strip():
                    body.append(next_line.strip())
                if len(" ".join(body)) >= 600:
                    break
            return " ".join(body)[:800] if body else None
    return None


def _render_summary(directory: Path, docs: list[DocumentSummary]) -> str:
    lines = [
        f"# Output Summary - {directory.as_posix()}",
        "",
        f"Generated from {len(docs)} markdown file(s).",
        "",
    ]
    for doc in docs:
        rel_path = doc.path.as_posix()
        lines.extend(
            [
                f"## {doc.title}",
                "",
                f"- File: `{rel_path}`",
                f"- Lines: {doc.line_count}",
            ]
        )
        if doc.tldr:
            lines.append(f"- TL;DR: {doc.tldr}")
        if doc.headings:
            lines.append("- Headings: " + "; ".join(doc.headings[:12]))
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
