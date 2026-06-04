from __future__ import annotations

import json

import pytest

from stele.packaging.platforms import PLATFORM_CONFIG
from stele.packaging.render import (
    render_agents_md_section,
    render_hook,
    render_hook_spec,
    render_mcp_server_config,
    render_skill,
)

PLATFORM_NAMES = list(PLATFORM_CONFIG.keys())


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_skill_renders_for_every_platform(name: str) -> None:
    out = render_skill(name)
    assert "/stele" in out
    assert "stele://" in out
    assert "stash_tool_result" in out
    assert "{{" not in out
    assert "{%" not in out


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_skill_frontmatter_present(name: str) -> None:
    out = render_skill(name)
    assert out.startswith("---")
    assert "name: stele" in out
    assert "description:" in out


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_agents_md_section_starts_with_marker(name: str) -> None:
    out = render_agents_md_section(name)
    assert out.startswith("## stele")
    assert "{{" not in out


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_mcp_server_config_is_valid_json(name: str) -> None:
    out = render_mcp_server_config(name)
    parsed = json.loads(out)
    assert "mcpServers" in parsed
    assert "stele" in parsed["mcpServers"]
    assert parsed["mcpServers"]["stele"]["command"] == "stele-mcp"


def test_unknown_platform_raises() -> None:
    with pytest.raises(KeyError):
        render_skill("not-a-platform")


HOOK_PLATFORMS = ["claude-code", "gemini-cli", "opencode", "cursor"]
NO_HOOK_PLATFORMS = ["codex", "copilot", "aider"]


@pytest.mark.parametrize("name", HOOK_PLATFORMS)
def test_hook_renders_for_supported_platforms(name: str) -> None:
    out = render_hook(name)
    assert out is not None
    assert "{{" not in out
    assert "{%" not in out
    assert "stele" in out.lower()


@pytest.mark.parametrize("name", NO_HOOK_PLATFORMS)
def test_no_hook_returns_none(name: str) -> None:
    assert render_hook(name) is None


def test_gemini_hook_is_valid_json() -> None:
    out = render_hook("gemini-cli")
    assert out is not None
    parsed = json.loads(out)
    assert "tools" in parsed or "beforeTool" in parsed or isinstance(parsed, dict)


def test_render_hook_spec_renders_each_claude_code_hook() -> None:
    for hook in PLATFORM_CONFIG["claude-code"].hooks:
        out = render_hook_spec("claude-code", hook)
        assert "{{" not in out
        assert "{%" not in out
        assert "stele" in out.lower()


def test_render_hook_spec_uses_default_namespace() -> None:
    # The ingest template defaults `ingest_namespace` to 'sessions' when the
    # HookSpec supplies no override.
    ingest = next(
        h
        for h in PLATFORM_CONFIG["claude-code"].hooks
        if "session-ingest" in h.dest_path
    )
    out = render_hook_spec("claude-code", ingest)
    assert "--namespace \"sessions\"" in out
