"""`stele distill <mode>` -- per-mode memory distillation."""

from __future__ import annotations

import argparse

from stele.cli.commands.data_plane import invoke


def add_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "distill",
        help="Distill a memory mode (facts|precedents|state|skills|best_practices|"
        "rules|episodes|timeline|spans)",
    )
    p.add_argument(
        "mode",
        choices=["facts", "precedents", "state", "skills", "best_practices", "rules",
                 "episodes", "timeline", "spans"],
    )
    p.add_argument("--namespace", default=None)
    p.set_defaults(func=run_distill)


def run_distill(args: argparse.Namespace) -> int:
    kwargs: dict[str, object] = {"mode": args.mode}
    if args.namespace is not None:
        kwargs["namespace"] = args.namespace
    return invoke("stele_distill", kwargs, pretty=args.pretty)
