"""`stele list` and `stele delete` — artifact listing + deletion.

Lives in a single module to keep one obvious place for the artifact-surface
read/delete pair (and to dodge the ``list`` keyword conflict at module level).
"""

from __future__ import annotations

import argparse
from typing import Any

from stele.cli.commands.data_plane import invoke


def add_list_subparser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = sub.add_parser("list", help="List stored artifacts")
    p.add_argument("--namespace", default=None)
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=run_list)


def add_delete_subparser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p = sub.add_parser("delete", help="Delete a stored artifact by reference")
    p.add_argument("ref")
    p.set_defaults(func=run_delete)


def run_list(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {"limit": args.limit}
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    return invoke("stele_list", kwargs, pretty=args.pretty)


def run_delete(args: argparse.Namespace) -> int:
    return invoke("stele_delete", {"ref": args.ref}, pretty=args.pretty)
