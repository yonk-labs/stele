"""`stele status` — per-platform install state."""

from __future__ import annotations

import argparse
from pathlib import Path

from stele.packaging.platforms import PLATFORM_CONFIG


def run(args: argparse.Namespace) -> int:
    home = Path.home()
    print("Platform           Installed   Stamp")
    for name, spec in PLATFORM_CONFIG.items():
        skill = Path(spec.skill_path.replace("~", str(home)))
        stamp = skill.parent / ".stele_version"
        installed = "yes" if skill.exists() else "no"
        version = stamp.read_text().strip() if stamp.exists() else "—"
        print(f"{name:<18} {installed:<11} {version}")
    return 0
