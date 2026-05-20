from __future__ import annotations

import json

import pytest

from stele.packaging.platforms import PLATFORM_CONFIG
from stele.packaging.render import (
    render_agents_md_section,
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
