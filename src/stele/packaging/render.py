"""Jinja2 rendering for skill, hook, shared-doc-section, and mcp.json content.

One template per content type. Platform-specific data comes from
`PLATFORM_CONFIG[name]`; the template body is identical across platforms.
"""

from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from stele.packaging.platforms import PLATFORM_CONFIG, HookSpec, PlatformSpec

_TEMPLATES_DIR = files("stele.packaging").joinpath("templates")


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(
            disabled_extensions=("md", "j2", "sh", "js", "json", "mdc")
        ),
        keep_trailing_newline=True,
    )


def _ctx(spec: PlatformSpec) -> dict[str, object]:
    return {
        "name": spec.name,
        "description": spec.description,
        "trigger": spec.trigger,
        "stash_threshold": 4096,
        "tool_reference_table": _tool_reference_table(),
    }


def _tool_reference_table() -> str:
    """Render a one-row-per-tool reference table from the TOOLS registry."""
    from stele.mcp.tools import TOOLS

    lines = ["| Tool | Purpose | Key inputs |", "|---|---|---|"]
    for tool in TOOLS:
        required = ", ".join(tool.input_schema.get("required", []))
        lines.append(
            f"| `{tool.name}` | {tool.description} | {required or '—'} |"
        )
    return "\n".join(lines)


def render_skill(platform_name: str) -> str:
    spec = PLATFORM_CONFIG[platform_name]
    return _env().get_template("skill.md.j2").render(**_ctx(spec))


def render_agents_md_section(platform_name: str) -> str:
    spec = PLATFORM_CONFIG[platform_name]
    return _env().get_template("agents-md-section.md.j2").render(**_ctx(spec))


def render_mcp_server_config(platform_name: str) -> str:
    spec = PLATFORM_CONFIG[platform_name]
    return _env().get_template("mcp-server-config.json.j2").render(**_ctx(spec))


def render_hook(platform_name: str) -> str | None:
    spec = PLATFORM_CONFIG[platform_name]
    if spec.hook_template is None:
        return None
    return _env().get_template(spec.hook_template).render(**_ctx(spec))


def render_hook_spec(platform_name: str, hook: HookSpec) -> str:
    """Render one `HookSpec` with the shared context plus the hook's own context."""
    spec = PLATFORM_CONFIG[platform_name]
    ctx = _ctx(spec)
    ctx.update(hook.context)
    return _env().get_template(hook.template).render(**ctx)
