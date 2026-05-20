"""`stele memory ...` — memory subcommands."""

from __future__ import annotations

import argparse
import json
from typing import Any

from stele.cli.commands.data_plane import invoke


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("memory", help="Memory operations")
    mem = p.add_subparsers(dest="memory_command", required=True)

    p_add = mem.add_parser("add", help="Add a memory record")
    p_add.add_argument("text")
    p_add.add_argument("--source-ref", nargs="+", required=True)
    p_add.add_argument("--kind", default="fact")
    p_add.add_argument("--namespace", default=None)
    p_add.add_argument("--supersedes", nargs="*", default=None)
    p_add.add_argument("--confidence", type=float, default=1.0)
    p_add.add_argument("--metadata", type=json.loads, default=None)
    p_add.set_defaults(func=run_add)

    p_get = mem.add_parser("get", help="Fetch a memory record by id")
    p_get.add_argument("memory_id")
    p_get.set_defaults(func=run_get)

    p_search = mem.add_parser("search", help="Search memory")
    p_search.add_argument("query")
    p_search.add_argument("--namespace", default=None)
    p_search.add_argument("--as-of", default=None)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument(
        "--include-superseded", action="store_true", default=False
    )
    p_search.set_defaults(func=run_search)

    p_list = mem.add_parser("list", help="List memory records")
    p_list.add_argument("--namespace", default=None)
    p_list.add_argument("--as-of", default=None)
    p_list.add_argument("--limit", type=int, default=100)
    p_list.add_argument(
        "--status", nargs="*", default=None, dest="status_filter"
    )
    p_list.set_defaults(func=run_list)

    p_update = mem.add_parser("update", help="Update memory metadata")
    p_update.add_argument("memory_id")
    p_update.add_argument("--metadata", type=json.loads, default=None)
    p_update.set_defaults(func=run_update)

    p_delete = mem.add_parser("delete", help="Soft-delete a memory record")
    p_delete.add_argument("memory_id")
    p_delete.set_defaults(func=run_delete)

    p_retract = mem.add_parser("retract", help="Retract a memory record")
    p_retract.add_argument("memory_id")
    p_retract.add_argument("--reason", required=True)
    p_retract.set_defaults(func=run_retract)


def run_add(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {
        "text": args.text,
        "source_refs": args.source_ref,
        "kind": args.kind,
        "confidence": args.confidence,
    }
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    if args.supersedes is not None:
        kwargs["supersedes"] = args.supersedes
    if args.metadata is not None:
        kwargs["metadata"] = args.metadata
    return invoke("stele_memory_add", kwargs, pretty=args.pretty)


def run_get(args: argparse.Namespace) -> int:
    return invoke(
        "stele_memory_get", {"memory_id": args.memory_id}, pretty=args.pretty
    )


def run_search(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {
        "query": args.query,
        "limit": args.limit,
        "include_superseded": args.include_superseded,
    }
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    if args.as_of is not None:
        kwargs["as_of"] = args.as_of
    return invoke("stele_memory_search", kwargs, pretty=args.pretty)


def run_list(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {"limit": args.limit}
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    if args.as_of is not None:
        kwargs["as_of"] = args.as_of
    if args.status_filter is not None:
        kwargs["status_filter"] = args.status_filter
    return invoke("stele_memory_list", kwargs, pretty=args.pretty)


def run_update(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {"memory_id": args.memory_id}
    if args.metadata is not None:
        kwargs["metadata"] = args.metadata
    return invoke("stele_memory_update", kwargs, pretty=args.pretty)


def run_delete(args: argparse.Namespace) -> int:
    return invoke(
        "stele_memory_delete", {"memory_id": args.memory_id}, pretty=args.pretty
    )


def run_retract(args: argparse.Namespace) -> int:
    return invoke(
        "stele_memory_retract",
        {"memory_id": args.memory_id, "reason": args.reason},
        pretty=args.pretty,
    )
