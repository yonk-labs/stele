from __future__ import annotations

import pytest

from stele.packaging.platforms import PLATFORM_CONFIG, PlatformSpec

PLATFORM_NAMES = [
    "claude-code",
    "codex",
    "opencode",
    "cursor",
    "gemini-cli",
    "copilot",
    "aider",
]


def test_all_seven_platforms_registered() -> None:
    assert set(PLATFORM_CONFIG.keys()) == set(PLATFORM_NAMES)


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_every_spec_has_required_fields(name: str) -> None:
    spec = PLATFORM_CONFIG[name]
    assert isinstance(spec, PlatformSpec)
    assert spec.skill_path.startswith("~/") or spec.skill_path.startswith("/")
    assert spec.description
    assert spec.trigger.startswith("/")


def test_platform_spec_immutable() -> None:
    spec = PLATFORM_CONFIG["claude-code"]
    with pytest.raises((AttributeError, TypeError)):
        spec.skill_path = "/tmp/oops"  # type: ignore[misc]


def test_claude_code_has_two_hooks() -> None:
    spec = PLATFORM_CONFIG["claude-code"]
    dests = [h.dest_path for h in spec.hooks]
    assert "~/.claude/hooks/stele-large-output.sh" in dests
    assert "~/.claude/hooks/stele-session-ingest.sh" in dests
    assert len(spec.hooks) == 2


def test_ingest_hook_is_claude_code_only() -> None:
    for name, spec in PLATFORM_CONFIG.items():
        if name == "claude-code":
            continue
        assert all("session-ingest" not in h.dest_path for h in spec.hooks), name


def test_hooks_property_matches_legacy_fields() -> None:
    # Platforms with a single primary hook expose exactly that hook.
    for name in ("opencode", "cursor", "gemini-cli"):
        spec = PLATFORM_CONFIG[name]
        assert [h.dest_path for h in spec.hooks] == [spec.hook_path]
        assert [h.template for h in spec.hooks] == [spec.hook_template]
    # Platforms with no hook expose an empty tuple.
    for name in ("codex", "copilot", "aider"):
        assert PLATFORM_CONFIG[name].hooks == ()
