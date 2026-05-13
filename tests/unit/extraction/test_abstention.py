"""Abstention behavior — pure-noise inputs never produce agent-loop kinds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "extraction"
AGENT_LOOP_KINDS = {"preference", "decision", "commitment", "instruction", "issue"}


def _load(name: str) -> dict[str, list[str]]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "fixture_name",
    [
        "preferences.json",
        "decisions.json",
        "commitments.json",
        "changed_facts.json",
        "abstention.json",
    ],
)
def test_abstention_samples_never_produce_agent_loop_kinds(fixture_name: str) -> None:
    fixture = _load(fixture_name)
    stele = Stele(StashConfig())
    for text in fixture["abstention"]:
        report = stele.extract.from_text(
            text=text,
            source_refs=["stele://default/abc"],
            scope=MemoryScope(user_id="abstention"),
        )
        for accepted in report.accepted:
            assert accepted.candidate.kind not in AGENT_LOOP_KINDS, (
                f"{fixture_name} abstention sample produced agent-loop kind: "
                f"{accepted.candidate.kind!r} on text {text!r}"
            )
    stele.close()


def test_positive_samples_produce_expected_kind() -> None:
    for fixture_name in (
        "preferences.json",
        "decisions.json",
        "commitments.json",
    ):
        fixture = _load(fixture_name)
        expected = fixture["expected_kind"]
        stele = Stele(StashConfig())
        for text in fixture["positive"]:
            report = stele.extract.from_text(
                text=text,
                source_refs=["stele://default/abc"],
                scope=MemoryScope(user_id="positive"),
            )
            kinds = {a.candidate.kind for a in report.accepted}
            assert expected in kinds, (
                f"{fixture_name} positive sample failed to produce {expected!r}: "
                f"text={text!r}, kinds={kinds!r}"
            )
        stele.close()
