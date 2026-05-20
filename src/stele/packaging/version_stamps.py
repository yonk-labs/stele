"""Per-platform .stele_version stamps; refresh-all on any install."""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from pathlib import Path

from stele.packaging.platforms import PLATFORM_CONFIG


def _current_version() -> str:
    try:
        return _pkg_version("stele-core")
    except Exception:
        return "0.0.0"


def write_stamp(skill_dir: Path, *, version: str | None = None) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / ".stele_version").write_text((version or _current_version()) + "\n")


def refresh_all(*, version: str | None = None) -> None:
    """Refresh .stele_version in every platform's skill dir that already has one."""
    home = Path.home()
    v = version or _current_version()
    for spec in PLATFORM_CONFIG.values():
        skill_path = Path(spec.skill_path.replace("~", str(home)))
        stamp = skill_path.parent / ".stele_version"
        if stamp.exists():
            stamp.write_text(v + "\n")
