from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main


def test_uninstall_reverses_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    main(["install", "--platform", "claude-code"])
    rc = main(["uninstall", "--platform", "claude-code"])
    assert rc == 0
    assert not (tmp_path / ".claude" / "skills" / "stele" / "SKILL.md").exists()
