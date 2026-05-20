"""Tests for the mcp.json merge/unmerge behavior in install.py.

These test the bug found while planning the smoke checklist: install would
overwrite an existing mcp.json, clobbering other tools' MCP server entries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stele.packaging.install import (
    McpConfigCorruptedError,
    _merge_mcp_config,
    _remove_from_mcp_config,
)

STELE_ENTRY = '{"mcpServers": {"stele": {"command": "stele-mcp", "args": [], "env": {}}}}'


def test_merge_writes_verbatim_when_file_missing(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    _merge_mcp_config(dest, STELE_ENTRY)
    assert dest.is_file()
    assert json.loads(dest.read_text())["mcpServers"]["stele"]["command"] == "stele-mcp"


def test_merge_preserves_other_servers(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other-tool": {"command": "other", "args": ["-x"]},
                    "third-tool": {"command": "third"},
                }
            }
        )
    )

    _merge_mcp_config(dest, STELE_ENTRY)

    result = json.loads(dest.read_text())
    assert set(result["mcpServers"]) == {"other-tool", "third-tool", "stele"}
    assert result["mcpServers"]["other-tool"] == {"command": "other", "args": ["-x"]}
    assert result["mcpServers"]["stele"]["command"] == "stele-mcp"


def test_merge_preserves_unrelated_top_level_keys(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text(
        json.dumps(
            {
                "version": 2,
                "globalEnv": {"FOO": "bar"},
                "mcpServers": {"x": {"command": "x"}},
            }
        )
    )

    _merge_mcp_config(dest, STELE_ENTRY)

    result = json.loads(dest.read_text())
    assert result["version"] == 2
    assert result["globalEnv"] == {"FOO": "bar"}
    assert "stele" in result["mcpServers"]


def test_merge_updates_existing_stele_entry(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "stele": {"command": "OLD-COMMAND", "args": ["--legacy"]},
                }
            }
        )
    )

    _merge_mcp_config(dest, STELE_ENTRY)

    result = json.loads(dest.read_text())
    assert result["mcpServers"]["stele"]["command"] == "stele-mcp"
    assert result["mcpServers"]["stele"]["args"] == []


def test_merge_treats_empty_file_as_missing(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text("")
    _merge_mcp_config(dest, STELE_ENTRY)
    assert json.loads(dest.read_text())["mcpServers"]["stele"]["command"] == "stele-mcp"


def test_merge_raises_on_corrupt_json(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text("{ this is not valid json")
    with pytest.raises(McpConfigCorruptedError):
        _merge_mcp_config(dest, STELE_ENTRY)


def test_merge_raises_when_top_level_not_object(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text("[1, 2, 3]")
    with pytest.raises(McpConfigCorruptedError):
        _merge_mcp_config(dest, STELE_ENTRY)


def test_merge_raises_when_mcpServers_not_object(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text(json.dumps({"mcpServers": "wrong"}))
    with pytest.raises(McpConfigCorruptedError):
        _merge_mcp_config(dest, STELE_ENTRY)


def test_remove_drops_stele_keeps_others(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    dest.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "stele": {"command": "stele-mcp"},
                    "other": {"command": "other"},
                }
            }
        )
    )

    _remove_from_mcp_config(dest)

    result = json.loads(dest.read_text())
    assert "stele" not in result["mcpServers"]
    assert "other" in result["mcpServers"]


def test_remove_leaves_file_with_empty_servers(tmp_path: Path) -> None:
    """File survives even when stele was the only entry — other tools may rely on the file."""
    dest = tmp_path / "mcp.json"
    dest.write_text(json.dumps({"mcpServers": {"stele": {"command": "stele-mcp"}}}))

    _remove_from_mcp_config(dest)

    assert dest.exists()
    result = json.loads(dest.read_text())
    assert result == {"mcpServers": {}}


def test_remove_is_noop_when_missing(tmp_path: Path) -> None:
    dest = tmp_path / "mcp.json"
    _remove_from_mcp_config(dest)
    assert not dest.exists()


def test_remove_is_noop_on_corrupt_json(tmp_path: Path) -> None:
    """Don't compound corruption — leave the file alone."""
    dest = tmp_path / "mcp.json"
    dest.write_text("{ invalid")
    _remove_from_mcp_config(dest)
    assert dest.read_text() == "{ invalid"
