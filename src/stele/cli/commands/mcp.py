"""`stele mcp` — alias for the stele-mcp server entry point."""

from __future__ import annotations

import argparse

from stele.mcp.server import main as server_main


def run(args: argparse.Namespace) -> int:
    server_main()
    return 0
