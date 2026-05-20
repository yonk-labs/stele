"""`stele uninstall` — reverse install for one or more platforms."""

from __future__ import annotations

import argparse

from stele.packaging.install import uninstall_for
from stele.packaging.platforms import PLATFORM_CONFIG


def run(args: argparse.Namespace) -> int:
    if args.all:
        targets = list(PLATFORM_CONFIG.keys())
    else:
        if not args.platform or args.platform not in PLATFORM_CONFIG:
            print(f"stele: unknown platform {args.platform!r}")
            return 2
        targets = [args.platform]

    for name in targets:
        uninstall_for(name)
        print(f"stele: uninstalled {name}")
    return 0
