"""`stele doctor` — validate config + extras + backend reachability."""

from __future__ import annotations

import argparse
from importlib.util import find_spec
from typing import Any

from stele.core.stash import Stele
from stele.mcp.config import config_path, load_raw_config

# Backend → (import_name, extra_name) pairs. The doctor pre-check fires before
# Stele.from_config so the user sees an actionable pip command instead of the
# generic "config rejected" wrapper that OptionalDependencyError lands as.
_BACKEND_EXTRAS: dict[str, tuple[str, str]] = {
    "postgres": ("psycopg", "postgres"),
    "mariadb": ("pymysql", "mariadb"),
    "clickhouse": ("clickhouse_connect", "clickhouse"),
}


def _check_extras(raw: dict[str, Any]) -> list[str]:
    """Return human-readable extras-missing diagnostics. Empty list = OK."""
    problems: list[str] = []
    backend_type = (raw.get("backend") or {}).get("type")
    if backend_type in _BACKEND_EXTRAS:
        import_name, extra = _BACKEND_EXTRAS[backend_type]
        if find_spec(import_name) is None:
            problems.append(
                f"backend.type={backend_type!r} requires the [{extra}] extra. "
                f"Install with: pip install 'stele-core[{extra}]'"
            )
    if (raw.get("graph") or {}).get("enabled") and find_spec("pg_raggraph") is None:
        problems.append(
            "graph.enabled=true requires the [postgres-graph] extra. "
            "Install with: pip install 'stele-core[postgres-graph]'"
        )
    indexing = raw.get("indexing") or {}
    if indexing.get("provider") == "chunkshop" and find_spec("chunkshop") is None:
        problems.append(
            "indexing.provider='chunkshop' requires the [chunkshop] extra. "
            "Install with: pip install 'stele-core[chunkshop]'"
        )
    return problems


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

    extras_problems = _check_extras(raw)
    if extras_problems:
        print(f"stele doctor: missing optional dependencies for {cfg}")
        for line in extras_problems:
            print(f"  - {line}")
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
