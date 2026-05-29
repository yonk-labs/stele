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
    p.add_argument("--session-id", default=None)
    p.add_argument("--created-after", default=None, metavar="ISO8601",
                   help="Keep artifacts with created_at >= this timestamp.")
    p.add_argument("--created-before", default=None, metavar="ISO8601")
    p.add_argument(
        "--filter", action="append", default=[], metavar="KEY=VALUE",
        help="Metadata filter, repeatable. e.g. metadata.git_branch=auth or "
             "metadata.date__gte=2026-05-18. __in keys take a comma list.",
    )
    p.add_argument("--now", default=None, metavar="ISO8601",
                   help="Reference clock for retrieval.temporal_routing.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {"query": args.query, "limit": args.limit}
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    if args.mode is not None:
        kwargs["mode"] = args.mode
    if args.session_id is not None:
        kwargs["session_id"] = args.session_id
    if args.now is not None:
        kwargs["now"] = args.now
    filters: dict[str, Any] = {}
    if args.created_after is not None:
        filters["created_after"] = args.created_after
    if args.created_before is not None:
        filters["created_before"] = args.created_before
    for item in args.filter:
        if "=" not in item:
            raise SystemExit(f"--filter must be KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        filters[key] = value.split(",") if key.endswith("__in") else value
    if filters:
        kwargs["filters"] = filters
    return invoke("stele_query", kwargs, pretty=args.pretty)
