"""Stele CLI entry point."""

from __future__ import annotations

import argparse
import sys

from stele.cli.commands import init as init_cmd
from stele.cli.commands import install as install_cmd
from stele.cli.commands import uninstall as uninstall_cmd


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stele", description="Stele CLI")
    sub = parser.add_subparsers(dest="command", required=True)

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"stele: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
