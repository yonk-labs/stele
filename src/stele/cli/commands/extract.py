"""`stele extract ...` — extraction subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from stele.cli.commands.data_plane import invoke, read_stdin_if_dash


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("extract", help="Extraction operations")
    ext = p.add_subparsers(dest="extract_command", required=True)

    p_text = ext.add_parser("from-text", help="Extract from free text")
    p_text.add_argument(
        "--text",
        default=None,
        help="text payload, or '-' for stdin",
    )
    p_text.add_argument("--source-ref", nargs="+", required=True)
    p_text.add_argument("--namespace", default=None)
    p_text.set_defaults(func=run_from_text)

    p_msg = ext.add_parser("from-messages", help="Extract from a JSON message list")
    p_msg.add_argument(
        "--input",
        default=None,
        help="path to a JSON file, or '-' for stdin",
    )
    p_msg.add_argument("--namespace", default=None)
    p_msg.set_defaults(func=run_from_messages)

    p_art = ext.add_parser("from-artifact", help="Extract from a stored artifact")
    p_art.add_argument("ref")
    p_art.add_argument("--namespace", default=None)
    p_art.set_defaults(func=run_from_artifact)


def _resolve_text(value: str | None) -> str:
    resolved = read_stdin_if_dash(value)
    if resolved is None:
        if not sys.stdin.isatty():
            resolved = sys.stdin.read()
        else:
            sys.stderr.write(
                "stele extract from-text: provide --text TEXT or pipe via stdin\n"
            )
            raise SystemExit(2)
    return resolved


def _resolve_messages_json(value: str | None) -> list[dict[str, Any]]:
    if value == "-" or value is None:
        if value is None and sys.stdin.isatty():
            sys.stderr.write(
                "stele extract from-messages: provide --input FILE or pipe JSON\n"
            )
            raise SystemExit(2)
        raw = sys.stdin.read()
    else:
        with open(value) as fh:
            raw = fh.read()
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        sys.stderr.write("stele extract from-messages: input must be a JSON array\n")
        raise SystemExit(2)
    return parsed


def run_from_text(args: argparse.Namespace) -> int:
    text = _resolve_text(args.text)
    kwargs: dict[str, Any] = {
        "text": text,
        "source_refs": args.source_ref,
    }
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    return invoke("stele_extract_from_text", kwargs, pretty=args.pretty)


def run_from_messages(args: argparse.Namespace) -> int:
    messages = _resolve_messages_json(args.input)
    kwargs: dict[str, Any] = {"messages": messages}
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    return invoke("stele_extract_from_messages", kwargs, pretty=args.pretty)


def run_from_artifact(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {"ref": args.ref}
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    return invoke("stele_extract_from_artifact", kwargs, pretty=args.pretty)
