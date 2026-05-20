"""Config-file resolution for the MCP server and CLI.

Walks up from `start_dir` (defaults to CWD) looking for `.stele/config.yaml`.
Falls back to `~/.config/stele/config.yaml`. Returns `None` if neither exists;
callers decide whether that's fatal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def config_path(*, start_dir: Path | None = None) -> Path | None:
    cwd = (start_dir or Path.cwd()).resolve()
    for candidate in [cwd, *cwd.parents]:
        local = candidate / ".stele" / "config.yaml"
        if local.is_file():
            return local
    user_global = Path.home() / ".config" / "stele" / "config.yaml"
    if user_global.is_file():
        return user_global
    return None


def load_raw_config(path: Path) -> dict[str, Any]:
    with path.open() as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping at top of {path}, got {type(loaded)!r}")
    return loaded
