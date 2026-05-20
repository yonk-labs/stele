from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main


def test_doctor_passes_after_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init", "--backend", "memory"])
    rc = main(["doctor"])
    assert rc == 0


def test_doctor_fails_without_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty-home")
    rc = main(["doctor"])
    assert rc != 0
