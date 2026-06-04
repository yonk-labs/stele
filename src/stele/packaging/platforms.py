"""Multi-platform routing table.

Adding a new platform = one entry in PLATFORM_CONFIG plus (optionally) a
hook template file. No other code changes needed for basic install
support.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HookSpec:
    """One installable hook: a template, its destination, and render context.

    `context` carries any template variables beyond the shared render context
    (e.g. the ingest hook's `ingest_namespace`).
    """

    template: str
    dest_path: str
    context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PlatformSpec:
    """Where a platform's skill, hooks, and shared-doc-section live.

    `hook_template` / `hook_path` describe the primary hook and are kept for
    backward compatibility (docs and the legacy `render_hook` path read them).
    `extra_hooks` carries any additional hooks a platform installs alongside it.
    `hooks` is the unified view install / uninstall / status iterate over.
    """

    name: str
    description: str
    trigger: str
    skill_path: str
    project_agents_doc: str | None
    user_agents_doc: str | None
    hook_template: str | None
    hook_path: str | None
    mcp_config_path: str | None
    extra_hooks: tuple[HookSpec, ...] = ()

    @property
    def hooks(self) -> tuple[HookSpec, ...]:
        """Every hook this platform installs, primary first then extras."""
        primary: tuple[HookSpec, ...] = ()
        if self.hook_template is not None and self.hook_path is not None:
            primary = (HookSpec(template=self.hook_template, dest_path=self.hook_path),)
        return primary + self.extra_hooks


_STELE_DESCRIPTION = (
    "Evidence-cited memory + artifact storage via stele's MCP server. "
    "Use stele_memory_search before answering from prior context; use "
    "stele_stash_tool_result for oversized tool output."
)


PLATFORM_CONFIG: dict[str, PlatformSpec] = {
    "claude-code": PlatformSpec(
        name="claude-code",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.claude/skills/stele/SKILL.md",
        project_agents_doc="CLAUDE.md",
        user_agents_doc="~/.claude/CLAUDE.md",
        hook_template="hooks/claude-code.sh.j2",
        hook_path="~/.claude/hooks/stele-large-output.sh",
        mcp_config_path="~/.claude/mcp.json",
        extra_hooks=(
            HookSpec(
                template="hooks/claude-code-ingest.sh.j2",
                dest_path="~/.claude/hooks/stele-session-ingest.sh",
            ),
        ),
    ),
    "codex": PlatformSpec(
        name="codex",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.agents/skills/stele/SKILL.md",
        project_agents_doc="AGENTS.md",
        user_agents_doc=None,
        hook_template=None,
        hook_path=None,
        mcp_config_path="~/.agents/mcp.json",
    ),
    "opencode": PlatformSpec(
        name="opencode",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.config/opencode/skills/stele/SKILL.md",
        project_agents_doc="AGENTS.md",
        user_agents_doc=None,
        hook_template="hooks/opencode-plugin.js.j2",
        hook_path="~/.config/opencode/plugins/stele.js",
        mcp_config_path="~/.config/opencode/mcp.json",
    ),
    "cursor": PlatformSpec(
        name="cursor",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.cursor/skills/stele/SKILL.md",
        project_agents_doc=None,
        user_agents_doc=None,
        hook_template="hooks/cursor-rules.mdc.j2",
        hook_path=".cursor/rules/stele.mdc",
        mcp_config_path="~/.cursor/mcp.json",
    ),
    "gemini-cli": PlatformSpec(
        name="gemini-cli",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.gemini/skills/stele/SKILL.md",
        project_agents_doc="GEMINI.md",
        user_agents_doc=None,
        hook_template="hooks/gemini-settings.json.j2",
        hook_path="~/.gemini/settings.json",
        mcp_config_path="~/.gemini/mcp.json",
    ),
    "copilot": PlatformSpec(
        name="copilot",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.copilot/skills/stele/SKILL.md",
        project_agents_doc="AGENTS.md",
        user_agents_doc=None,
        hook_template=None,
        hook_path=None,
        mcp_config_path="~/.copilot/mcp.json",
    ),
    "aider": PlatformSpec(
        name="aider",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.aider/skills/stele/SKILL.md",
        project_agents_doc="AGENTS.md",
        user_agents_doc=None,
        hook_template=None,
        hook_path=None,
        mcp_config_path="~/.aider/mcp.json",
    ),
}
