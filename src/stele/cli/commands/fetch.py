"""`stele fetch` — resolve a stele:// ref."""

from __future__ import annotations

import argparse

from stele.cli.commands.data_plane import invoke


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("fetch", help="Resolve a stele:// reference")
    p.add_argument("ref")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    return invoke("stele_fetch", {"ref": args.ref}, pretty=args.pretty)
