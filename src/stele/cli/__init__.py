"""Stele CLI entry point."""

from __future__ import annotations

import argparse
import sys

from stele.cli.commands import init as init_cmd


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
