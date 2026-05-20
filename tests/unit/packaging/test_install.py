from __future__ import annotations

from pathlib import Path

import pytest

from stele.packaging.install import install_for, uninstall_for


def _expand(path_str: str, home: Path) -> Path:
    return Path(path_str.replace("~", str(home)))


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_install_claude_code_writes_skill_and_hook(fake_home: Path) -> None:
    install_for("claude-code")

    skill = _expand("~/.claude/skills/stele/SKILL.md", fake_home)
    hook = _expand("~/.claude/hooks/stele-large-output.sh", fake_home)
    user_md = _expand("~/.claude/CLAUDE.md", fake_home)
    project_md = fake_home / "CLAUDE.md"

    assert skill.is_file()
    assert "stele" in skill.read_text().lower()
    assert hook.is_file()
    assert "## stele" in user_md.read_text()
    assert "## stele" in project_md.read_text()


def test_install_codex_no_hook(fake_home: Path) -> None:
    install_for("codex")

    skill = _expand("~/.agents/skills/stele/SKILL.md", fake_home)
    assert skill.is_file()
    assert not (fake_home / ".agents" / "hooks").exists()


def test_uninstall_removes_skill_and_section(fake_home: Path) -> None:
    install_for("claude-code")
    uninstall_for("claude-code")

    skill = _expand("~/.claude/skills/stele/SKILL.md", fake_home)
    user_md = _expand("~/.claude/CLAUDE.md", fake_home)
    project_md = fake_home / "CLAUDE.md"

    assert not skill.exists()
    if user_md.exists():
        assert "## stele" not in user_md.read_text()
    if project_md.exists():
        assert "## stele" not in project_md.read_text()


def test_dry_run_writes_nothing(fake_home: Path) -> None:
    install_for("claude-code", dry_run=True)
    assert not _expand("~/.claude/skills/stele/SKILL.md", fake_home).exists()


def test_unknown_platform_raises(fake_home: Path) -> None:
    with pytest.raises(KeyError):
        install_for("not-a-platform")
