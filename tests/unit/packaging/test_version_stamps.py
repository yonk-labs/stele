from __future__ import annotations

from pathlib import Path

import pytest

from stele.packaging.platforms import PLATFORM_CONFIG
from stele.packaging.version_stamps import refresh_all, write_stamp


def test_write_stamp_creates_file(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    write_stamp(skill_dir, version="0.1.0")
    stamp = skill_dir / ".stele_version"
    assert stamp.read_text().strip() == "0.1.0"


def test_refresh_all_updates_only_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(Path, "home", lambda: home)

    for name in ["claude-code", "codex"]:
        spec = PLATFORM_CONFIG[name]
        skill_dir = Path(spec.skill_path.replace("~", str(home))).parent
        skill_dir.mkdir(parents=True)
        (skill_dir / ".stele_version").write_text("0.0.9\n")

    refresh_all(version="0.1.0")

    for name in ["claude-code", "codex"]:
        spec = PLATFORM_CONFIG[name]
        stamp = Path(spec.skill_path.replace("~", str(home))).parent / ".stele_version"
        assert stamp.read_text().strip() == "0.1.0"

    for name in ["cursor", "gemini-cli"]:
        spec = PLATFORM_CONFIG[name]
        stamp = Path(spec.skill_path.replace("~", str(home))).parent / ".stele_version"
        assert not stamp.exists()
