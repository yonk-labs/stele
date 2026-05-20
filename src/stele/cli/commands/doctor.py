"""`stele doctor` — validate config + backend reachability."""

from __future__ import annotations

import argparse

from stele.core.stash import Stele
from stele.mcp.config import config_path, load_raw_config


def run(args: argparse.Namespace) -> int:
    cfg = config_path()
    if cfg is None:
        print("stele doctor: no config found (run `stele init`)")
        return 1

    try:
        raw = load_raw_config(cfg)
    except Exception as exc:
        print(f"stele doctor: failed to parse {cfg}: {exc}")
        return 1

    try:
        stele = Stele.from_config(raw)
    except Exception as exc:
        print(f"stele doctor: config rejected: {exc}")
        return 1

    try:
        caps = stele.capabilities()
        backend_type = raw.get("backend", {}).get("type")
        print(
            f"stele doctor: ok ({cfg}) — backend={backend_type} capabilities={caps!r}"
        )
    except Exception as exc:
        print(f"stele doctor: backend not reachable: {exc}")
        return 1
    return 0
