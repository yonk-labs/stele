"""Stele CLI entry point."""

from __future__ import annotations

import argparse
import sys

from stele.cli.commands import artifacts as artifacts_cmd
from stele.cli.commands import bulk as bulk_cmd
from stele.cli.commands import doctor as doctor_cmd
from stele.cli.commands import extract as extract_cmd
from stele.cli.commands import fetch as fetch_cmd
from stele.cli.commands import init as init_cmd
from stele.cli.commands import install as install_cmd
from stele.cli.commands import lifecycle as lifecycle_cmd
from stele.cli.commands import mcp as mcp_cmd
from stele.cli.commands import memory as memory_cmd
from stele.cli.commands import query as query_cmd
from stele.cli.commands import recall as recall_cmd
from stele.cli.commands import search as search_cmd
from stele.cli.commands import stash as stash_cmd
from stele.cli.commands import status as status_cmd
from stele.cli.commands import store as store_cmd
from stele.cli.commands import uninstall as uninstall_cmd


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stele", description="Stele CLI")
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=False,
        help="Pretty-print JSON output (data-plane commands).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ----- operator surface -------------------------------------------------
    p_init = sub.add_parser("init", help="Write .stele/config.yaml")
    p_init.add_argument(
        "--backend",
        default="sqlite",
        choices=["memory", "sqlite", "postgres", "mariadb", "clickhouse"],
    )
    p_init.add_argument("--dsn", default=None)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=init_cmd.run)

    p_install = sub.add_parser(
        "install", help="Install stele skill+hook for a platform"
    )
    p_install.add_argument("--platform", default=None)
    p_install.add_argument("--all", action="store_true")
    p_install.add_argument("--dry-run", action="store_true")
    p_install.set_defaults(func=install_cmd.run)

    p_uninstall = sub.add_parser("uninstall", help="Uninstall stele skill+hook")
    p_uninstall.add_argument("--platform", default=None)
    p_uninstall.add_argument("--all", action="store_true")
    p_uninstall.set_defaults(func=uninstall_cmd.run)

    sub.add_parser("doctor", help="Validate config + backend").set_defaults(
        func=doctor_cmd.run
    )
    sub.add_parser("status", help="Per-platform install state").set_defaults(
        func=status_cmd.run
    )
    sub.add_parser(
        "mcp", help="Run the stele-mcp server in foreground"
    ).set_defaults(func=mcp_cmd.run)

    # ----- data-plane surface ----------------------------------------------
    store_cmd.add_subparser(sub)
    fetch_cmd.add_subparser(sub)
    search_cmd.add_subparser(sub)
    query_cmd.add_subparser(sub)
    artifacts_cmd.add_list_subparser(sub)
    artifacts_cmd.add_delete_subparser(sub)
    memory_cmd.add_subparser(sub)
    extract_cmd.add_subparser(sub)
    recall_cmd.add_subparser(sub)
    stash_cmd.add_subparser(sub)

    # ----- lifecycle + bulk-write ------------------------------------------
    lifecycle_cmd.add_purge_subparser(sub)
    lifecycle_cmd.add_export_subparser(sub)
    lifecycle_cmd.add_import_subparser(sub)
    bulk_cmd.add_store_many_subparser(sub)

    return parser


def _extract_pretty(argv: list[str]) -> tuple[list[str], bool]:
    """Pop ``--pretty`` from anywhere in argv so it works pre- or post-verb.

    argparse global flags can normally only sit *before* the subcommand;
    stripping the flag up front lets `stele fetch REF --pretty` work the same
    as `stele --pretty fetch REF`.
    """
    pretty = False
    cleaned: list[str] = []
    for tok in argv:
        if tok == "--pretty":
            pretty = True
            continue
        cleaned.append(tok)
    return cleaned, pretty


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, pretty = _extract_pretty(raw)
    parser = _build_parser()
    args = parser.parse_args(raw)
    # Ensure every handler sees args.pretty (pre-verb --pretty already wins,
    # but stripping above means we always set it explicitly).
    args.pretty = pretty or bool(getattr(args, "pretty", False))
    try:
        return int(args.func(args) or 0)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"stele: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
