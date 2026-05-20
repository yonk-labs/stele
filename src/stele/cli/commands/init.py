"""`stele init` — write .stele/config.yaml with sensible defaults."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, dict[str, Any]] = {
    "memory": {"backend": {"type": "memory"}},
    "sqlite": {"backend": {"type": "sqlite", "dsn": ".stele/stele.db"}},
    "postgres": {"backend": {"type": "postgres", "dsn": None}},
    "mariadb": {"backend": {"type": "mariadb", "dsn": None}},
    "clickhouse": {"backend": {"type": "clickhouse", "dsn": None}},
}

BASE_CONFIG: dict[str, Any] = {
    "pii": {"raw_fetch_enabled": False, "scrub_summary": True},
    "signing": {"mode": "optional"},
    "indexing": {"mode": "sync"},
    "retrieval": {"default_mode": "hybrid"},
    "mcp": {"stash_threshold_tokens": 4096},
}


def run(args: argparse.Namespace) -> int:
    cfg_dir = Path.cwd() / ".stele"
    cfg_path = cfg_dir / "config.yaml"
    if cfg_path.exists() and not args.force:
        print(f"stele: {cfg_path} already exists (use --force to overwrite)")
        return 2

    cfg_dir.mkdir(parents=True, exist_ok=True)
    backend = dict(DEFAULTS[args.backend])
    if args.dsn is not None:
        backend["backend"]["dsn"] = args.dsn
    body: dict[str, Any] = {**backend, **BASE_CONFIG}
    cfg_path.write_text(yaml.safe_dump(body, sort_keys=False))
    print(f"stele: wrote {cfg_path}")
    return 0
