"""recall.shortcut cascade: outcome -> context -> procedure -> work (most-reliable-first).

Driven on a real sqlite Stele (lexical matcher; intents must share terms with stored text).
Each tier's short-circuit and fall-through is exercised, plus the work fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.recall.shortcut import ShortcutResult

SCOPE = MemoryScope(user_id="alice")


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "s.db")}}
    )


def test_shortcut_all_miss_returns_work(stele: Stele) -> None:
    res = stele.recall.shortcut(intent="run the test suite", env={"v": "1"}, scope=SCOPE)
    assert isinstance(res, ShortcutResult)
    assert res.tier == "work"
    assert res.hit is False


def test_shortcut_outcome_short_circuits(stele: Stele) -> None:
    stele.memory.record_outcome(
        text="cached result of running the test suite",
        source_refs=["stele://default/o"],
        scope=SCOPE,
        env={"v": "1"},
    )
    res = stele.recall.shortcut(
        intent="running the test suite", env={"v": "1"}, scope=SCOPE
    )
    assert res.tier == "outcome"
    assert res.hit is True
    assert res.payload is not None and "cached result" in res.payload


def test_shortcut_falls_to_context_when_fresh(stele: Stele) -> None:
    src = "def run(): ...  # the test runner"
    stele.memory.record_context(
        text="the test suite runner lives here",
        source_ref="stele://default/runner",
        source=src,
        intent="the test suite runner",
        scope=SCOPE,
        ttl_seconds=3600,
    )
    res = stele.recall.shortcut(
        intent="the test suite runner", env={"v": "1"}, scope=SCOPE, source=src
    )
    assert res.tier == "context"
    assert res.hit is True
    assert res.reason == "fresh"


def test_shortcut_context_stale_falls_through_to_work(stele: Stele) -> None:
    stele.memory.record_context(
        text="the test suite runner lives here",
        source_ref="stele://default/runner",
        source="OLD SOURCE",
        intent="the test suite runner",
        scope=SCOPE,
        ttl_seconds=3600,
    )
    # the source changed -> context is stale, and no procedure exists -> work.
    res = stele.recall.shortcut(
        intent="the test suite runner", env={"v": "1"}, scope=SCOPE, source="NEW SOURCE"
    )
    assert res.tier == "work"


def test_shortcut_context_fresh_unverified_when_no_source(stele: Stele) -> None:
    stele.memory.record_context(
        text="the test suite runner lives here",
        source_ref="stele://default/runner",
        source="whatever",
        intent="the test suite runner",
        scope=SCOPE,
        ttl_seconds=3600,
    )
    res = stele.recall.shortcut(
        intent="the test suite runner", env={"v": "1"}, scope=SCOPE
    )
    assert res.tier == "context"
    assert res.reason == "fresh_unverified_source"


def test_shortcut_context_exact_key_beats_semantic_miss(stele: Stele) -> None:
    # the intent shares NO terms with the context text, so the semantic leg misses; but the
    # exact key (source_ref == the file path) hits. This is the hybrid: exact-key first.
    src = "export function grid() {}"
    stele.memory.record_context(
        text="renders the card grid",
        source_ref="stele://default/cards.js",
        source=src,
        intent="cards grid",
        scope=SCOPE,
        ttl_seconds=3600,
    )
    res = stele.recall.shortcut(
        intent="zzz totally unrelated words",
        env={"v": "1"},
        scope=SCOPE,
        key="stele://default/cards.js",
        source=src,
    )
    assert res.tier == "context"
    assert res.reason == "exact-fresh"


def test_shortcut_context_exact_key_stale_on_changed_source(stele: Stele) -> None:
    stele.memory.record_context(
        text="renders the card grid",
        source_ref="stele://default/cards.js",
        source="OLD BYTES",
        intent="cards grid",
        scope=SCOPE,
        ttl_seconds=3600,
    )
    # the file changed (the read-edit-reread loop) -> exact context is stale, semantic misses.
    res = stele.recall.shortcut(
        intent="zzz unrelated",
        env={"v": "1"},
        scope=SCOPE,
        key="stele://default/cards.js",
        source="NEW CHANGED BYTES",
    )
    assert res.tier == "work"


def test_shortcut_procedure_is_advisory(stele: Stele) -> None:
    stele.memory.record_procedure(
        text="run the test suite: ruff; mypy; pytest",
        intent="run the test suite",
        source_refs=["stele://default/p"],
        scope=SCOPE,
    )
    res = stele.recall.shortcut(intent="run the test suite", env={"v": "1"}, scope=SCOPE)
    assert res.tier == "procedure"
    assert res.hit is True
    assert res.reason in ("advisory", "advisory_env_drift")
