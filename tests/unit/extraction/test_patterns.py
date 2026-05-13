"""Tests for the regex pattern packs."""

from __future__ import annotations

import pytest

from stele.extraction.patterns import (
    PATTERN_PACKS,
    PatternPack,
    match_first_kind,
)


def test_pattern_pack_kind_weights_in_range() -> None:
    for pack in PATTERN_PACKS:
        assert 0.0 < pack.kind_weight <= 1.0, pack.kind


def test_pattern_pack_declaration_order_is_stable() -> None:
    kinds = [p.kind for p in PATTERN_PACKS]
    assert kinds == [
        "preference",
        "decision",
        "commitment",
        "instruction",
        "issue",
    ]


@pytest.mark.parametrize(
    "text,expected_kind",
    [
        ("I prefer dark mode over light mode.", "preference"),
        ("I like Helix more than Vim.", "preference"),
        ("My favorite editor is Zed.", "preference"),
        ("We decided to switch to RBAC.", "decision"),
        ("Let's go with PostgreSQL for now.", "decision"),
        ("I'll send the report by Friday.", "commitment"),
        ("TODO: rewrite the auth middleware.", "commitment"),
        ("Please always use parameterized queries.", "instruction"),
        ("Never commit the .env file.", "instruction"),
        ("The login page is broken on Safari.", "issue"),
        ("Crash on startup with empty config.", "issue"),
    ],
)
def test_match_first_kind_positive(text: str, expected_kind: str) -> None:
    result = match_first_kind(text)
    assert result is not None
    assert result.kind == expected_kind


@pytest.mark.parametrize(
    "text",
    [
        "The capital of France is Paris.",
        "Population: 67 million.",
        "Q3 revenue grew 12 percent year over year.",
        "",
        "   ",
        "lorem ipsum dolor sit amet",
    ],
)
def test_match_first_kind_abstention(text: str) -> None:
    assert match_first_kind(text) is None


def test_pattern_pack_dataclass_fields() -> None:
    pack = PATTERN_PACKS[0]
    assert isinstance(pack, PatternPack)
    assert pack.kind == "preference"
    assert pack.kind_weight > 0
    assert len(pack.patterns) > 0
