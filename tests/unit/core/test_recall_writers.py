"""Writers that feed recall.shortcut: record_procedure (Phase 3) and record_context (Phase 2).

record_procedure stores the steps for a workflow as kind="procedure" with the trigger intent
(and an optional applicability env). record_context stores what a source is/does as
kind="observation" with the freshness anchors (source hash + optional TTL) that
reuse.is_stale checks at recall time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stele import Stele
from stele.core import reuse as _reuse
from stele.core.memory_record import MemoryScope

SCOPE = MemoryScope(user_id="alice")


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_record_procedure_stores_kind_intent_and_env(stele: Stele) -> None:
    res = stele.memory.record_procedure(
        text="run ruff; mypy; pytest",
        intent="test the project",
        source_refs=["stele://default/evidence"],
        scope=SCOPE,
        env={"py": "3.12"},
    )
    got = stele.memory.get(res.record.id)
    assert got is not None
    assert got.kind == "procedure"
    assert got.metadata[_reuse.META_INTENT] == "test the project"
    assert got.metadata[_reuse.META_ENV] == {"py": "3.12"}


def test_record_context_stores_hash_ttl_and_intent(stele: Stele) -> None:
    source = "def cards(): ..."
    res = stele.memory.record_context(
        text="cards.py renders the card grid",
        source_ref="stele://default/cards",
        source=source,
        intent="what does cards.py do",
        scope=SCOPE,
        ttl_seconds=3600,
    )
    got = stele.memory.get(res.record.id)
    assert got is not None
    assert got.kind == "observation"
    assert got.metadata[_reuse.META_SOURCE_HASH] == _reuse.source_hash(source)
    assert got.metadata[_reuse.META_TTL] == 3600
    assert got.metadata[_reuse.META_INTENT] == "what does cards.py do"
    assert got.source_refs == ["stele://default/cards"]


def test_record_context_without_ttl_omits_it(stele: Stele) -> None:
    res = stele.memory.record_context(
        text="ctx", source_ref="stele://default/x", source="x", intent="i", scope=SCOPE
    )
    got = stele.memory.get(res.record.id)
    assert got is not None
    assert _reuse.META_TTL not in got.metadata
