"""CLI surface tests for the lifecycle + bulk-write subcommands (#21)."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest

from stele.cli import main
from stele.cli.commands import data_plane


@pytest.fixture(autouse=True)
def _isolate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    monkeypatch.chdir(tmp_path)
    data_plane.reset_handlers()
    yield
    data_plane.reset_handlers()


def _capture_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return cast(dict[str, Any], json.loads(lines[-1]))


def _init_sqlite(tmp_path: Path) -> None:
    """sqlite backend persists across handler resets in the same tmp."""
    main(["init", "--backend", "sqlite"])


def test_purge_namespace_refuses_without_yes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _init_sqlite(tmp_path)
    capsys.readouterr()
    main(["store", "--text", "evidence", "--namespace", "ns"])
    capsys.readouterr()

    rc = main(["purge-namespace", "ns"])  # no --yes
    out = _capture_json(capsys)
    assert rc != 0
    assert "error" in out and "destructive" in out["error"]["message"]


def test_purge_namespace_dry_run_returns_counts(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _init_sqlite(tmp_path)
    capsys.readouterr()
    main(["store", "--text", "alpha", "--namespace", "ns"])
    main(["store", "--text", "beta", "--namespace", "ns"])
    capsys.readouterr()

    rc = main(["purge-namespace", "ns", "--dry-run"])
    out = _capture_json(capsys)
    assert rc == 0
    assert out["result"]["dry_run"] is True
    assert out["result"]["artifacts"] == 2


def test_purge_namespace_yes_deletes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _init_sqlite(tmp_path)
    capsys.readouterr()
    main(["store", "--text", "evidence", "--namespace", "ns"])
    capsys.readouterr()

    rc = main(["purge-namespace", "ns", "--yes"])
    out = _capture_json(capsys)
    assert rc == 0
    assert out["result"]["artifacts"] == 1
    # Listing the namespace returns nothing.
    capsys.readouterr()
    data_plane.reset_handlers()
    main(["list", "--namespace", "ns"])
    listed = _capture_json(capsys)
    assert listed["page"]["items"] == []


def test_export_then_import_round_trips(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _init_sqlite(tmp_path)
    capsys.readouterr()
    main(["store", "--text", "exported content", "--namespace", "ex"])
    capsys.readouterr()

    bundle = tmp_path / "bundle.jsonl"
    rc = main(["export-namespace", "ex", "--output", str(bundle)])
    out = _capture_json(capsys)
    assert rc == 0
    assert out["result"]["exported_count"] >= 1
    assert bundle.exists()

    # Purge then re-import → content restored.
    capsys.readouterr()
    main(["purge-namespace", "ex", "--yes"])
    capsys.readouterr()
    data_plane.reset_handlers()
    rc = main(["import-namespace", str(bundle)])
    out = _capture_json(capsys)
    assert rc == 0
    assert out["result"]["imported_count"] >= 1


def test_store_many_from_jsonl_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _init_sqlite(tmp_path)
    capsys.readouterr()

    jsonl = tmp_path / "rows.jsonl"
    jsonl.write_text(
        "\n".join(
            json.dumps({"content": f"row {i}", "namespace": "bulk"})
            for i in range(4)
        )
        + "\n"
    )

    rc = main(["store-many", "--input", str(jsonl)])
    out = _capture_json(capsys)
    assert rc == 0
    assert len(out["results"]) == 4


def test_memory_add_many_from_jsonl_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _init_sqlite(tmp_path)
    capsys.readouterr()

    jsonl = tmp_path / "memos.jsonl"
    jsonl.write_text(
        "\n".join(
            json.dumps({
                "text": f"fact {i}",
                "kind": "fact",
                "source_refs": [f"stele://bulk/{i}"],
                "scope": {"namespace": "bulk"},
            })
            for i in range(3)
        )
        + "\n"
    )

    rc = main(["memory", "add-many", "--input", str(jsonl)])
    out = _capture_json(capsys)
    assert rc == 0
    assert len(out["results"]) == 3


def test_store_many_invalid_json_fails_loudly(tmp_path: Path) -> None:
    _init_sqlite(tmp_path)
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not valid json\n")
    with pytest.raises(SystemExit) as exc:
        main(["store-many", "--input", str(bad)])
    assert "invalid JSON" in str(exc.value)
