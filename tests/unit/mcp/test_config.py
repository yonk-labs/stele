from __future__ import annotations

from pathlib import Path

import pytest

from stele.mcp.config import config_path, load_raw_config


def test_walks_up_to_dot_stele(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True)
    (project / ".stele").mkdir()
    (project / ".stele" / "config.yaml").write_text("backend:\n  type: memory\n")

    resolved = config_path(start_dir=nested)
    assert resolved == project / ".stele" / "config.yaml"


def test_falls_back_to_user_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    cfg_dir = home / ".config" / "stele"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("backend:\n  type: memory\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)

    project = tmp_path / "proj"
    project.mkdir()

    resolved = config_path(start_dir=project)
    assert resolved == cfg_dir / "config.yaml"


def test_returns_none_when_nothing_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-home")
    assert config_path(start_dir=tmp_path) is None


def test_load_raw_config_parses_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / ".stele" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text("backend:\n  type: sqlite\n  dsn: foo.db\n")

    loaded = load_raw_config(cfg)
    assert loaded == {"backend": {"type": "sqlite", "dsn": "foo.db"}}
