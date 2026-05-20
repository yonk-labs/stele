"""Per-platform install / uninstall orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stele.packaging.platforms import PLATFORM_CONFIG, PlatformSpec
from stele.packaging.render import (
    render_agents_md_section,
    render_hook,
    render_mcp_server_config,
    render_skill,
)
from stele.packaging.sections import remove_section, upsert_section
from stele.packaging.version_stamps import refresh_all, write_stamp


class McpConfigCorruptedError(RuntimeError):
    """Raised when an existing mcp.json is present but isn't valid JSON.

    The install refuses to overwrite a corrupted config so the user can
    inspect and fix it themselves rather than losing data.
    """


def _expand(path_str: str | None, home: Path) -> Path | None:
    if path_str is None:
        return None
    if path_str.startswith("~"):
        return Path(path_str.replace("~", str(home), 1))
    return Path(path_str)


def _merge_mcp_config(path: Path, rendered: str) -> None:
    """Idempotently set the `stele` entry inside an mcpServers map.

    - If `path` does not exist, write `rendered` verbatim.
    - If `path` exists and is valid JSON, set `mcpServers.stele` to the
      `stele` entry from `rendered`, preserving every other key.
    - If `path` exists but isn't valid JSON, raise `McpConfigCorruptedError`.
    """
    new_payload: dict[str, Any] = json.loads(rendered)
    new_stele_entry = new_payload["mcpServers"]["stele"]

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
        return

    raw = path.read_text()
    if not raw.strip():
        path.write_text(rendered)
        return

    try:
        existing = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise McpConfigCorruptedError(
            f"{path} is not valid JSON ({exc}); refusing to overwrite. "
            f"Inspect the file or remove it manually, then re-run install."
        ) from exc

    if not isinstance(existing, dict):
        raise McpConfigCorruptedError(
            f"{path} top-level must be a JSON object; got {type(existing).__name__}"
        )

    servers = existing.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise McpConfigCorruptedError(
            f"{path} 'mcpServers' must be an object; got {type(servers).__name__}"
        )
    servers["stele"] = new_stele_entry
    path.write_text(json.dumps(existing, indent=2) + "\n")


def _remove_from_mcp_config(path: Path) -> None:
    """Remove the `stele` entry from an mcpServers map; leave others intact.

    - If `path` doesn't exist or is empty, no-op.
    - If `path` is corrupted JSON, leave it alone (don't compound the problem).
    - If after removal `mcpServers` is empty AND it's the only key, leave the
      empty `{"mcpServers": {}}` shell rather than deleting the file — other
      tools may rely on the file existing.
    """
    if not path.exists():
        return
    raw = path.read_text()
    if not raw.strip():
        return
    try:
        existing = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(existing, dict):
        return
    servers = existing.get("mcpServers")
    if isinstance(servers, dict) and "stele" in servers:
        del servers["stele"]
        path.write_text(json.dumps(existing, indent=2) + "\n")


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
        _merge_mcp_config(mcp_dest, render_mcp_server_config(platform))

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
    if mcp_dest is not None:
        _remove_from_mcp_config(mcp_dest)
