"""End-to-end CLI tests for the data-plane subcommands.

These exercise the full path: argv -> argparse -> ``invoke()`` -> bound MCP
handler -> JSON on stdout. The handler cache lives at module scope so the
fixture resets it between tests.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest

from stele.cli import main
from stele.cli.commands import data_plane


@pytest.fixture(autouse=True)
def _isolate_handlers_and_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """Each test gets a fresh CWD and a fresh handler cache."""
    monkeypatch.chdir(tmp_path)
    data_plane.reset_handlers()
    yield
    data_plane.reset_handlers()


def _capture_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    out = capsys.readouterr().out
    # Some test setups print warnings before JSON; take the last non-empty line.
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return cast(dict[str, Any], json.loads(lines[-1]))


# ---------------------------------------------------------------------------
# Artifact surface
# ---------------------------------------------------------------------------


def test_store_fetch_roundtrip_via_cli(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    rc = main(["store", "--text", "hello", "--content-type", "text"])
    out = _capture_json(capsys)
    assert rc == 0
    ref = out["ref"]
    assert isinstance(ref, str) and ref.startswith("stele://")

    rc = main(["fetch", ref])
    fetched = _capture_json(capsys)
    assert rc == 0
    assert "hello" in str(fetched["content"])


def test_memory_find_precedent_via_cli(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    main(["store", "--text", "deploy day is Friday", "--content-type", "text"])
    ref = _capture_json(capsys)["ref"]

    main(
        [
            "memory",
            "add",
            "deploy day is Friday",
            "--source-ref",
            ref,
            "--kind",
            "fact",
            "--metadata",
            '{"subject": "deploy_day", "predicate": "is", "object": "Friday"}',
        ]
    )
    capsys.readouterr()

    rc = main(
        [
            "memory",
            "find-precedent",
            "--match",
            '{"subject": "deploy_day", "predicate": "is"}',
            "--kind",
            "fact",
        ]
    )
    out = _capture_json(capsys)
    assert rc == 0
    assert len(out["records"]) == 1
    assert "deploy_day" in json.dumps(out["records"])


def test_store_reads_stdin_when_dash(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin.read", lambda: "piped body")
    rc = main(["store", "--text", "-", "--content-type", "text"])
    assert rc == 0
    out = _capture_json(capsys)
    ref = out["ref"]

    rc = main(["fetch", ref])
    fetched = _capture_json(capsys)
    assert "piped body" in str(fetched["content"])


def test_search_returns_hits_shape(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    main(["store", "--text", "alpha beta gamma", "--content-type", "text"])
    ref = _capture_json(capsys)["ref"]

    rc = main(["search", ref, "alpha"])
    out = _capture_json(capsys)
    assert rc == 0
    assert "hits" in out


def test_query_returns_hits_shape(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    main(["store", "--text", "alpha beta gamma", "--content-type", "text"])
    capsys.readouterr()

    rc = main(["query", "alpha"])
    out = _capture_json(capsys)
    assert rc == 0
    assert "hits" in out


def test_list_returns_page(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    main(["store", "--text", "one", "--content-type", "text"])
    capsys.readouterr()

    rc = main(["list"])
    out = _capture_json(capsys)
    assert rc == 0
    assert "page" in out


def test_delete_returns_ok(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    main(["store", "--text", "to-delete", "--content-type", "text"])
    ref = _capture_json(capsys)["ref"]

    rc = main(["delete", ref])
    out = _capture_json(capsys)
    assert rc == 0
    assert out["ok"] is True


def test_pretty_flag_outputs_indented(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    main(["--pretty", "store", "--text", "x", "--content-type", "text"])
    out = capsys.readouterr().out
    assert "\n  " in out  # indented JSON


def test_pretty_flag_after_subcommand_also_works(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    main(["store", "--text", "x", "--content-type", "text", "--pretty"])
    out = capsys.readouterr().out
    assert "\n  " in out


# ---------------------------------------------------------------------------
# Memory surface
# ---------------------------------------------------------------------------


def _seed_ref(capsys: pytest.CaptureFixture[str], text: str = "evidence body") -> str:
    main(["store", "--text", text, "--content-type", "text"])
    return str(_capture_json(capsys)["ref"])


def test_memory_add_then_search_via_cli(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    ref = _seed_ref(capsys)
    rc = main(["memory", "add", "user prefers helix", "--source-ref", ref])
    out = _capture_json(capsys)
    assert rc == 0
    assert out["memory_id"]

    rc = main(["memory", "search", "helix"])
    hits = _capture_json(capsys)
    assert rc == 0
    assert isinstance(hits["hits"], list)
    assert len(hits["hits"]) >= 1


def test_memory_get_returns_record(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys)
    main(["memory", "add", "fact one", "--source-ref", ref])
    mid = _capture_json(capsys)["memory_id"]

    rc = main(["memory", "get", str(mid)])
    out = _capture_json(capsys)
    assert rc == 0
    assert out["record"] is not None


def test_memory_list_returns_records(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys)
    main(["memory", "add", "fact A", "--source-ref", ref])
    capsys.readouterr()

    rc = main(["memory", "list"])
    out = _capture_json(capsys)
    assert rc == 0
    assert isinstance(out["records"], list)
    assert len(out["records"]) >= 1


def test_memory_update_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys)
    main(["memory", "add", "fact A", "--source-ref", ref])
    mid = _capture_json(capsys)["memory_id"]

    rc = main(
        [
            "memory",
            "update",
            str(mid),
            "--metadata",
            json.dumps({"tag": "x"}),
        ]
    )
    out = _capture_json(capsys)
    assert rc == 0
    assert out["record"] is not None


def test_memory_delete_returns_ok(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys)
    main(["memory", "add", "fact A", "--source-ref", ref])
    mid = _capture_json(capsys)["memory_id"]

    rc = main(["memory", "delete", str(mid)])
    out = _capture_json(capsys)
    assert rc == 0
    assert out["ok"] is True


def test_memory_retract_preserves_record(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys)
    main(["memory", "add", "fact A", "--source-ref", ref])
    mid = _capture_json(capsys)["memory_id"]

    rc = main(
        ["memory", "retract", str(mid), "--reason", "found a better source"]
    )
    out = _capture_json(capsys)
    assert rc == 0
    assert out["record"] is not None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extract_from_text_via_cli(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys, text="Project uses Postgres 17 in production.")

    rc = main(
        [
            "extract",
            "from-text",
            "--text",
            "Project uses Postgres 17 in production.",
            "--source-ref",
            ref,
        ]
    )
    out = _capture_json(capsys)
    assert rc == 0
    assert "report" in out


def test_extract_from_text_reads_stdin(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys, text="payload via stdin")

    monkeypatch.setattr("sys.stdin.read", lambda: "payload via stdin")
    rc = main(
        ["extract", "from-text", "--text", "-", "--source-ref", ref]
    )
    out = _capture_json(capsys)
    assert rc == 0
    assert "report" in out


def test_extract_from_messages_via_stdin(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    msgs = [
        {"role": "user", "content": "Postgres is preferred over MySQL here."}
    ]
    monkeypatch.setattr("sys.stdin.read", lambda: json.dumps(msgs))
    rc = main(["extract", "from-messages", "--input", "-"])
    out = _capture_json(capsys)
    assert rc == 0
    assert "report" in out


def test_extract_from_artifact_via_cli(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys, text="Postgres 17 chosen for citext support.")

    rc = main(["extract", "from-artifact", ref])
    out = _capture_json(capsys)
    assert rc == 0
    assert "report" in out


# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------


def test_recall_via_cli(capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys, text="Project uses Postgres 17 in production.")
    main(["memory", "add", "Project uses Postgres 17", "--source-ref", ref])
    capsys.readouterr()

    rc = main(["recall", "Postgres version", "--strategy", "memory_search"])
    out = _capture_json(capsys)
    assert rc == 0
    assert "response" in out


def test_recall_hides_retracted_via_cli(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI round-trip of stele's most consequential axis: memory add -> recall
    (hit) -> memory retract -> recall (miss). Uses an isolated `--backend
    memory` instance per test (tmp_path cwd), so nothing shared is touched."""
    main(["init", "--backend", "memory"])
    capsys.readouterr()
    ref = _seed_ref(capsys, text="test_stele: the deploy window is Friday 5pm.")
    main(["memory", "add", "test_stele: the deploy window is Friday 5pm", "--source-ref", ref])
    mid = _capture_json(capsys)["memory_id"]

    rc = main(["recall", "deploy window", "--strategy", "memory_search"])
    out = _capture_json(capsys)
    assert rc == 0
    citations = out["response"]["citations"]
    assert any(c["id"] == mid for c in citations), "expected the memory recalled before retraction"

    rc = main(["memory", "retract", str(mid), "--reason", "test_stele cleanup"])
    assert rc == 0
    capsys.readouterr()

    rc = main(["recall", "deploy window", "--strategy", "memory_search"])
    out = _capture_json(capsys)
    assert rc == 0
    citations_after = out["response"]["citations"]
    assert not any(c["id"] == mid for c in citations_after), (
        "retracted memory must be hidden from recall"
    )


# ---------------------------------------------------------------------------
# Interception
# ---------------------------------------------------------------------------


def test_stash_stdin_passthrough(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin.read", lambda: "x" * 8192)
    rc = main(["stash", "Bash", "-"])
    out = _capture_json(capsys)
    assert rc == 0
    assert "result" in out


def test_stash_input_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    payload_path = tmp_path / "raw.txt"
    payload_path.write_text("y" * 8192)
    rc = main(["stash", "Bash", "--input", str(payload_path)])
    out = _capture_json(capsys)
    assert rc == 0
    assert "result" in out


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_fetch_nonexistent_ref_returns_error_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["init", "--backend", "memory"])
    capsys.readouterr()

    rc = main(["fetch", "stele://default/deadbeef"])
    out = _capture_json(capsys)
    assert rc == 1
    assert "error" in out
