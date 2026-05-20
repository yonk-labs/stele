from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main


def test_install_single_platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = main(["install", "--platform", "claude-code"])
    assert rc == 0
    assert (tmp_path / ".claude" / "skills" / "stele" / "SKILL.md").is_file()


def test_install_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = main(["install", "--all"])
    assert rc == 0
    skills = list(tmp_path.glob("*/skills/stele/SKILL.md")) + list(
        tmp_path.glob("*/*/skills/stele/SKILL.md")
    )
    assert len(skills) >= 3


def test_install_rejects_unknown_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = main(["install", "--platform", "not-a-thing"])
    assert rc != 0
