"""End-to-end install/uninstall integration tests across all platforms."""

from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main
from stele.packaging.platforms import PLATFORM_CONFIG


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _skill_path(name: str, home: Path) -> Path:
    spec = PLATFORM_CONFIG[name]
    return Path(spec.skill_path.replace("~", str(home)))


def test_install_all_then_uninstall_all_leaves_no_skill_files(
    fake_home: Path,
) -> None:
    rc = main(["install", "--all"])
    assert rc == 0
    for name in PLATFORM_CONFIG:
        assert _skill_path(name, fake_home).is_file(), name

    rc = main(["uninstall", "--all"])
    assert rc == 0
    for name in PLATFORM_CONFIG:
        assert not _skill_path(name, fake_home).exists(), name


def test_install_then_reinstall_is_idempotent(fake_home: Path) -> None:
    main(["install", "--platform", "claude-code"])
    main(["install", "--platform", "claude-code"])
    user_md = fake_home / ".claude" / "CLAUDE.md"
    # Marker must appear exactly once.
    assert user_md.read_text().count("## stele") == 1


def test_install_one_uninstall_other_does_not_affect_first(
    fake_home: Path,
) -> None:
    main(["install", "--platform", "claude-code"])
    main(["install", "--platform", "codex"])
    main(["uninstall", "--platform", "codex"])
    assert _skill_path("claude-code", fake_home).is_file()
    assert not _skill_path("codex", fake_home).exists()
