from __future__ import annotations

import pytest

from stele.extraction.classifier import classify_kind

# (text, expected_kind) -- real rule language from yonk-tools CLAUDE.md files
CASES = [
    ("NEVER use gpt-4o, it is outdated", "pitfall"),
    ("do not edit the vendored llama.cpp test directory", "pitfall"),
    ("always use a connection pool, never a single connection", "instruction"),
    ("use gpt-5-mini instead", "workaround"),
    ("prefer a deterministic check over an LLM judge", "preference"),
    ("the prod database moved to us-west-2 on 1 April 2024", "fact"),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_rule_language_is_not_collapsed_to_fact(text: str, expected: str) -> None:
    out = classify_kind(text=text, lede_source="key_fact", overlay_enabled=True)
    assert out.kind == expected, f"{text!r} -> {out.kind}, expected {expected}"
