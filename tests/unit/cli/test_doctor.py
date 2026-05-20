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


def test_doctor_flags_missing_postgres_extra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Per #15: pre-check optional extras before reaching the backend.

    When backend.type=postgres but psycopg isn't importable, doctor must
    print an actionable pip command — not the generic 'config rejected'
    wrapper that OptionalDependencyError lands as today.
    """
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".stele"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "backend:\n"
        "  type: postgres\n"
        "  dsn: postgresql://user:pw@localhost:5432/stele\n"
    )

    # Simulate psycopg not installed by hiding it from find_spec.
    import stele.cli.commands.doctor as doctor_mod

    real_find_spec = doctor_mod.find_spec

    def fake_find_spec(name: str, *args, **kwargs):
        if name == "psycopg":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(doctor_mod, "find_spec", fake_find_spec)

    rc = main(["doctor"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "missing optional dependencies" in captured.out
    assert "stele-core[postgres]" in captured.out


def test_doctor_flags_missing_chunkshop_extra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """indexing.provider='chunkshop' without the extra also surfaces."""
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".stele"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "backend:\n"
        "  type: memory\n"
        "indexing:\n"
        "  provider: chunkshop\n"
        "  mode: sync\n"
    )

    import stele.cli.commands.doctor as doctor_mod

    real_find_spec = doctor_mod.find_spec

    def fake_find_spec(name: str, *args, **kwargs):
        if name == "chunkshop":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(doctor_mod, "find_spec", fake_find_spec)

    rc = main(["doctor"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "stele-core[chunkshop]" in captured.out


def test_doctor_passes_when_extras_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The extras pre-check is no-op for the memory backend (no extra needed)."""
    monkeypatch.chdir(tmp_path)
    main(["init", "--backend", "memory"])
    rc = main(["doctor"])
    assert rc == 0
