"""`stele store` — store text/bytes and emit the stele:// ref."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from stele.cli.commands.data_plane import invoke, read_stdin_if_dash


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("store", help="Store text/bytes and return a stele:// ref")
    p.add_argument(
        "--text",
        default=None,
        help="payload text, or '-' to read from stdin",
    )
    p.add_argument("--content-type", default=None)
    p.add_argument("--namespace", default=None)
    p.add_argument(
        "--metadata",
        type=json.loads,
        default=None,
        help="JSON object",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    text = read_stdin_if_dash(args.text)
    if text is None:
        # No --text and no '-': allow stdin if it's piped
        if not sys.stdin.isatty():
            text = sys.stdin.read()
        else:
            sys.stderr.write(
                "stele store: provide --text TEXT or pipe data via stdin\n"
            )
            return 2
    kwargs: dict[str, Any] = {"payload": text}
    if args.content_type is not None:
        kwargs["content_type"] = args.content_type
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    if args.metadata is not None:
        kwargs["metadata"] = args.metadata
    return invoke("stele_store", kwargs, pretty=args.pretty)
