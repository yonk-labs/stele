"""`stele store-many` / `stele memory add-many` — bulk-write CLI surface.

Both read JSONL from --input (file path) or stdin (-).
Each line is a JSON object matching StoreRequest or AddRequest respectively.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from stele.cli.commands.data_plane import invoke


def _read_jsonl(input_arg: str | None) -> list[dict[str, Any]]:
    if input_arg is None or input_arg == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(input_arg).read_text(encoding="utf-8")
    items: list[dict[str, Any]] = []
    for line_num, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            items.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"stele bulk-write: invalid JSON on line {line_num}: {exc}"
            ) from exc
    return items


def add_store_many_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "store-many",
        help="Bulk-store N artifacts from a JSONL file (one StoreRequest per line)",
    )
    p.add_argument(
        "--input",
        default="-",
        help="JSONL file path, or '-' for stdin (default)",
    )
    p.set_defaults(func=run_store_many)


def run_store_many(args: argparse.Namespace) -> int:
    items = _read_jsonl(args.input)
    return invoke("stele_store_many", {"items": items}, pretty=args.pretty)


def add_memory_add_many_subparser(p: argparse.ArgumentParser) -> None:
    """Mount under the existing `stele memory` parent group."""
    p.add_argument(
        "--input",
        default="-",
        help="JSONL file path, or '-' for stdin (default)",
    )
    p.set_defaults(func=run_memory_add_many)


def run_memory_add_many(args: argparse.Namespace) -> int:
    items = _read_jsonl(args.input)
    return invoke("stele_memory_add_many", {"items": items}, pretty=args.pretty)
