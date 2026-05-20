"""Tests for `stele mcp` subcommand wiring.

The actual server loop is exercised by the contract tests + the smoke
checklist; here we just verify the CLI dispatches to the server's main()
and that the dispatch is symmetric with the `stele-mcp` console script.
"""

from __future__ import annotations

from unittest.mock import patch

from stele.cli import main


def test_mcp_subcommand_invokes_server_main() -> None:
    with patch("stele.cli.commands.mcp.server_main") as mock_main:
        rc = main(["mcp"])
    assert rc == 0
    mock_main.assert_called_once_with()


def test_mcp_subcommand_is_symmetric_with_stele_mcp_script() -> None:
    """Both `stele mcp` and `stele-mcp` must call into the same server.main."""
    from stele.cli.commands.mcp import server_main as cli_target
    from stele.mcp.server import main as script_target
    assert cli_target is script_target
