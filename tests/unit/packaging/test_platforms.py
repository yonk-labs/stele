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
