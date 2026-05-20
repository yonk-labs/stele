"""`stele install` — render skill/hook/section content for one or more platforms."""

from __future__ import annotations

import argparse

from stele.packaging.install import install_for
from stele.packaging.platforms import PLATFORM_CONFIG


def run(args: argparse.Namespace) -> int:
    if args.all:
        targets = list(PLATFORM_CONFIG.keys())
    else:
        if not args.platform:
            print("stele: --platform NAME or --all required")
            return 2
        if args.platform not in PLATFORM_CONFIG:
            print(f"stele: unknown platform {args.platform!r}")
            return 2
        targets = [args.platform]

    for name in targets:
        install_for(name, dry_run=args.dry_run)
        print(f"stele: installed {name}")
    return 0
