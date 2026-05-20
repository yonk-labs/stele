"""`stele stash` — route a tool's raw output through interception."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from stele.cli.commands.data_plane import invoke, read_stdin_if_dash


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "stash",
        help="Route a tool's raw output through interception",
    )
    p.add_argument("tool_name")
    p.add_argument(
        "--input",
        default=None,
        help="path to a file with the raw output, or '-' for stdin",
    )
    # Positional shorthand: 'stele stash NAME -' reads stdin
    p.add_argument(
        "raw_input",
        nargs="?",
        default=None,
        help="'-' to read raw output from stdin",
    )
    p.add_argument("--namespace", default=None)
    p.add_argument("--metadata", type=json.loads, default=None)
    p.set_defaults(func=run)


def _resolve_raw(args: argparse.Namespace) -> str:
    # Explicit --input wins
    if args.input is not None:
        if args.input == "-":
            return sys.stdin.read()
        with open(args.input) as fh:
            return fh.read()
    # Positional '-' shorthand
    pos = read_stdin_if_dash(args.raw_input)
    if pos is not None:
        return pos
    # Bare pipe (no '-' supplied) — accept stdin if not a TTY
    if not sys.stdin.isatty():
        return sys.stdin.read()
    sys.stderr.write(
        "stele stash: provide --input FILE, '-' for stdin, or pipe data\n"
    )
    raise SystemExit(2)


def run(args: argparse.Namespace) -> int:
    raw = _resolve_raw(args)
    kwargs: dict[str, Any] = {
        "tool_name": args.tool_name,
        "raw_output": raw,
    }
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    if args.metadata is not None:
        kwargs["metadata"] = args.metadata
    return invoke("stele_stash_tool_result", kwargs, pretty=args.pretty)
