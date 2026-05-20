"""`stele search` — search artifacts via the configured retrieval backend."""

from __future__ import annotations

import argparse
from typing import Any

from stele.cli.commands.data_plane import invoke


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("search", help="Search artifacts under a stele:// ref")
    p.add_argument("ref")
    p.add_argument("query")
    p.add_argument("--mode", default=None)
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {
        "ref": args.ref,
        "query": args.query,
        "limit": args.limit,
    }
    if args.mode is not None:
        kwargs["mode"] = args.mode
    return invoke("stele_search", kwargs, pretty=args.pretty)
