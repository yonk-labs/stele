"""`stele purge-namespace` / `export-namespace` / `import-namespace` — lifecycle CLI surface."""

from __future__ import annotations

import argparse
from typing import Any

from stele.cli.commands.data_plane import invoke


def add_purge_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "purge-namespace",
        help="GDPR-style namespace purge (artifacts + memory + chunks + revisor)",
    )
    p.add_argument("namespace", help="namespace to purge")
    p.add_argument(
        "--yes",
        action="store_true",
        help="confirm destructive action (required for live purge)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="report counts that WOULD be deleted; mutate nothing",
    )
    p.set_defaults(func=run_purge)


def add_export_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "export-namespace",
        help="Export a namespace to a v2 JSONL bundle",
    )
    p.add_argument("namespace", help="namespace to export")
    p.add_argument("--output", required=True, help="bundle file path")
    p.add_argument("--limit", type=int, default=100_000)
    p.set_defaults(func=run_export)


def add_import_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "import-namespace",
        help="Restore a v2 JSONL bundle from export-namespace",
    )
    p.add_argument("input", help="bundle file path")
    p.set_defaults(func=run_import)


def run_purge(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {
        "namespace": args.namespace,
        "dry_run": bool(args.dry_run),
        # The MCP handler refuses unless confirm=true OR dry_run=true.
        "confirm": bool(args.yes),
    }
    return invoke("stele_purge_namespace", kwargs, pretty=args.pretty)


def run_export(args: argparse.Namespace) -> int:
    kwargs: dict[str, Any] = {
        "namespace": args.namespace,
        "path": args.output,
        "limit": int(args.limit),
    }
    return invoke("stele_export_namespace", kwargs, pretty=args.pretty)


def run_import(args: argparse.Namespace) -> int:
    return invoke("stele_import_namespace", {"path": args.input}, pretty=args.pretty)
