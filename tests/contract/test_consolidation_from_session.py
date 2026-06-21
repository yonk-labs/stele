"""Contract tests: from_session consolidates evolving facts into supersede chains.

Step 1: same-session supersession (earlier window's facts superseded by later).
Step 6: cross-session supersession (day1 facts superseded by day2 session).
"""

from __future__ import annotations

import json

from stele.core.config import StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope
from stele.core.stash import Stele


def _stele(tmp_path):
    cfg = StashConfig.model_validate({
        "backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")},
        "extraction": {"enabled": True},
    })
    return Stele(cfg)


def _fake_llm(window: str) -> str:
    if "not run" in window:
        return json.dumps([
            {"kind": "fact", "summary": "Test 1 not run", "detail": "",
             "subject_label": "Test 1", "aspect": "status"},
            {"kind": "fact", "summary": "Test 1 covers RAG", "detail": "",
             "subject_label": "Test 1", "aspect": "coverage"},
        ])
    return json.dumps([
        {"kind": "fact", "summary": "Test 1 passed", "detail": "",
         "subject_label": "Test 1", "aspect": "status"},
        {"kind": "fact", "summary": "Test 1 covers RAG and graph", "detail": "",
         "subject_label": "Test 1", "aspect": "coverage"},
    ])


def test_same_session_supersedes_within_slot(tmp_path):
    s = _stele(tmp_path)
    scope = MemoryScope(namespace="t", session_id="s1")
    transcript = [
        {"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100},
        {"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100},
    ]
    s.extract.from_session(transcript=transcript, scope=scope, llm=_fake_llm, source_ref=None)
    active = s.memory.search(MemoryQuery(query="Test 1", scope=scope, limit=50))
    summaries = {m.summary for m in active}
    assert "Test 1 passed" in summaries
    assert "Test 1 covers RAG and graph" in summaries
    assert "Test 1 not run" not in summaries          # superseded
    assert "Test 1 covers RAG" not in summaries        # superseded (coverage chain)


def test_as_of_returns_historical_state(tmp_path):
    s = _stele(tmp_path)
    scope = MemoryScope(namespace="t2", session_id="s1")
    transcript = [
        {"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100},
        {"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100},
    ]
    s.extract.from_session(transcript=transcript, scope=scope, llm=_fake_llm, source_ref=None)
    hist = s.memory.search(MemoryQuery(query="Test 1", scope=scope, limit=50,
                                       include_superseded=True))
    assert "Test 1 not run" in {m.summary for m in hist}   # history preserved


def test_cross_session_supersedes_prior(tmp_path):
    s = _stele(tmp_path)
    ns = "t3"
    yest = [{"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100}]
    s.extract.from_session(transcript=yest, scope=MemoryScope(namespace=ns, session_id="day1"),
                           llm=_fake_llm, source_ref=None)
    today = [{"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100}]
    s.extract.from_session(transcript=today, scope=MemoryScope(namespace=ns, session_id="day2"),
                           llm=_fake_llm, source_ref=None)
    # Query across the namespace (session_id=None matches all sessions).
    active = s.memory.search(MemoryQuery(query="Test 1",
                                         scope=MemoryScope(namespace=ns), limit=50))
    summaries = {m.summary for m in active}
    assert "Test 1 passed" in summaries
    assert "Test 1 not run" not in summaries   # day2 superseded day1 in the status slot


def test_committed_facts_carry_subject_id(tmp_path):
    s = _stele(tmp_path)
    scope = MemoryScope(namespace="sid", session_id="s1")
    transcript = [
        {"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100},
        {"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100},
    ]
    s.extract.from_session(transcript=transcript, scope=scope, llm=_fake_llm, source_ref=None)
    hits = s.memory.search(MemoryQuery(query="Test 1", scope=scope, limit=50,
                                       include_superseded=True))
    assert all(m.metadata.get("subject_id") for m in hits if m.metadata.get("aspect"))
