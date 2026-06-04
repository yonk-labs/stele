"""Tests for `stele status`."""

from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main


def test_status_shows_all_platforms_uninstalled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = main(["status"])
    assert rc == 0

    out = capsys.readouterr().out
    for name in [
        "claude-code",
        "codex",
        "opencode",
        "cursor",
        "gemini-cli",
        "copilot",
        "aider",
    ]:
        assert name in out
    # Every platform reports "no" when nothing is installed.
    assert out.count("no") >= 7


def test_status_reflects_an_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    main(["install", "--platform", "claude-code"])
    capsys.readouterr()  # drain install output

    main(["status"])
    out = capsys.readouterr().out

    # claude-code shows installed; codex still does not.
    claude_line = next(line for line in out.splitlines() if line.startswith("claude-code"))
    codex_line = next(line for line in out.splitlines() if line.startswith("codex"))
    assert "yes" in claude_line
    assert "no" in codex_line


def test_status_reports_ingest_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    # Before install: the ingest hook is listed but not installed.
    main(["status"])
    out = capsys.readouterr().out
    ingest_line = next(
        line for line in out.splitlines() if "stele-session-ingest.sh" in line
    )
    assert "no" in ingest_line

    # After install: it flips to installed.
    main(["install", "--platform", "claude-code"])
    capsys.readouterr()  # drain install output
    main(["status"])
    out = capsys.readouterr().out
    ingest_line = next(
        line for line in out.splitlines() if "stele-session-ingest.sh" in line
    )
    assert "yes" in ingest_line
