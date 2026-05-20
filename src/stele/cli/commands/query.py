"""`stele query` — targeted query against the chunk index."""

from __future__ import annotations

import argparse
from typing import Any

from stele.cli.commands.data_plane import invoke


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("query", help="Targeted query against the chunk index")
    p.add_argument("query")
    p.add_argument("--namespace", default=None)
    p.add_argument("--mode", default=None)
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {"query": args.query, "limit": args.limit}
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    if args.mode is not None:
        kwargs["mode"] = args.mode
    return invoke("stele_query", kwargs, pretty=args.pretty)
