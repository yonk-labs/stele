"""Per-platform install / uninstall orchestration."""

from __future__ import annotations

from pathlib import Path

from stele.packaging.platforms import PLATFORM_CONFIG, PlatformSpec
from stele.packaging.render import (
    render_agents_md_section,
    render_hook,
    render_mcp_server_config,
    render_skill,
)
from stele.packaging.sections import remove_section, upsert_section
from stele.packaging.version_stamps import refresh_all, write_stamp


def _expand(path_str: str | None, home: Path) -> Path | None:
    if path_str is None:
        return None
    if path_str.startswith("~"):
        return Path(path_str.replace("~", str(home), 1))
    return Path(path_str)


def install_for(platform: str, *, dry_run: bool = False) -> None:
    spec: PlatformSpec = PLATFORM_CONFIG[platform]
    home = Path.home()

    skill_dest = _expand(spec.skill_path, home)
    hook_dest = _expand(spec.hook_path, home)
    user_doc = _expand(spec.user_agents_doc, home)
    project_doc = (
        Path.cwd() / spec.project_agents_doc if spec.project_agents_doc else None
    )
    mcp_dest = _expand(spec.mcp_config_path, home)

    if dry_run:
        return

    assert skill_dest is not None
    skill_dest.parent.mkdir(parents=True, exist_ok=True)
    skill_dest.write_text(render_skill(platform))

    if hook_dest is not None:
        hook_text = render_hook(platform)
        if hook_text is not None:
            hook_dest.parent.mkdir(parents=True, exist_ok=True)
            hook_dest.write_text(hook_text)
            if hook_dest.suffix == ".sh":
                hook_dest.chmod(0o755)

    section = render_agents_md_section(platform)
    if user_doc is not None:
        upsert_section(user_doc, marker="## stele", content=section)
    if project_doc is not None:
        upsert_section(project_doc, marker="## stele", content=section)

    if mcp_dest is not None:
        mcp_dest.parent.mkdir(parents=True, exist_ok=True)
        mcp_dest.write_text(render_mcp_server_config(platform))

    write_stamp(skill_dest.parent)
    refresh_all()


def uninstall_for(platform: str) -> None:
    spec = PLATFORM_CONFIG[platform]
    home = Path.home()

    skill_dest = _expand(spec.skill_path, home)
    hook_dest = _expand(spec.hook_path, home)
    user_doc = _expand(spec.user_agents_doc, home)
    project_doc = (
        Path.cwd() / spec.project_agents_doc if spec.project_agents_doc else None
    )
    mcp_dest = _expand(spec.mcp_config_path, home)

    if skill_dest is not None and skill_dest.exists():
        skill_dest.unlink()
        stamp = skill_dest.parent / ".stele_version"
        if stamp.exists():
            stamp.unlink()
    if hook_dest is not None and hook_dest.exists():
        hook_dest.unlink()
    if user_doc is not None:
        remove_section(user_doc, marker="## stele")
    if project_doc is not None:
        remove_section(project_doc, marker="## stele")
    if mcp_dest is not None and mcp_dest.exists():
        mcp_dest.unlink()
