"""`stele status` — per-platform install state."""

from __future__ import annotations

import argparse
from pathlib import Path

from stele.packaging.platforms import PLATFORM_CONFIG


def _expand(path_str: str, home: Path) -> Path:
    return Path(path_str.replace("~", str(home), 1))


def run(args: argparse.Namespace) -> int:
    home = Path.home()
    print("Platform           Installed   Stamp")
    for name, spec in PLATFORM_CONFIG.items():
        skill = Path(spec.skill_path.replace("~", str(home)))
        stamp = skill.parent / ".stele_version"
        installed = "yes" if skill.exists() else "no"
        version = stamp.read_text().strip() if stamp.exists() else "—"
        print(f"{name:<18} {installed:<11} {version}")
        for hook in spec.hooks:
            hook_dest = _expand(hook.dest_path, home)
            hook_state = "yes" if hook_dest.exists() else "no"
            print(f"  hook {hook_dest.name:<27} {hook_state}")
    return 0
