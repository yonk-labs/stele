from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from stele.cli import main


def test_init_creates_default_sqlite_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main(["init"])
    assert rc == 0
    cfg = tmp_path / ".stele" / "config.yaml"
    loaded = yaml.safe_load(cfg.read_text())
    assert loaded["backend"]["type"] == "sqlite"
    assert loaded["backend"]["dsn"].endswith("stele.db")


def test_init_respects_flag_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main(["init", "--backend", "memory"])
    assert rc == 0
    cfg = tmp_path / ".stele" / "config.yaml"
    loaded = yaml.safe_load(cfg.read_text())
    assert loaded["backend"]["type"] == "memory"


def test_init_refuses_to_overwrite_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init"])
    rc = main(["init"])
    assert rc != 0


def test_init_overwrites_with_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init", "--backend", "memory"])
    rc = main(["init", "--backend", "sqlite", "--force"])
    assert rc == 0
    loaded = yaml.safe_load((tmp_path / ".stele" / "config.yaml").read_text())
    assert loaded["backend"]["type"] == "sqlite"
