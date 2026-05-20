"""`stele recall` — run a recall strategy."""

from __future__ import annotations

import argparse
from typing import Any

from stele.cli.commands.data_plane import invoke


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("recall", help="Run a recall strategy")
    p.add_argument("query")
    p.add_argument("--namespace", default=None)
    p.add_argument("--strategy", default=None)
    p.add_argument("--as-of", default=None)
    p.add_argument("--version-filter", default=None)
    p.add_argument("--retracted-behavior", default=None)
    p.add_argument("--max-memory-hits", type=int, default=None)
    p.add_argument("--max-artifact-hits", type=int, default=None)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {"query": args.query}
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    if args.strategy is not None:
        kwargs["strategy"] = args.strategy
    if args.as_of is not None:
        kwargs["as_of"] = args.as_of
    if args.version_filter is not None:
        kwargs["version_filter"] = args.version_filter
    if args.retracted_behavior is not None:
        kwargs["retracted_behavior"] = args.retracted_behavior
    if args.max_memory_hits is not None:
        kwargs["max_memory_hits"] = args.max_memory_hits
    if args.max_artifact_hits is not None:
        kwargs["max_artifact_hits"] = args.max_artifact_hits
    return invoke("stele_recall", kwargs, pretty=args.pretty)
