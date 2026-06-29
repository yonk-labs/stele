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


def _dated_llm(prompt: str) -> str:
    """Emits a single dated location fact, keyed on the transcript city. NOTE: the
    injected llm receives the FULL prompt (template + window), so we branch on
    "London" — a token that appears only in the transcript, never the template."""
    if "London" in prompt:
        return json.dumps([
            {"kind": "fact", "summary": "Home is in London", "detail": "",
             "subject_label": "Home", "aspect": "location", "event_date": "2026-01-01"},
        ])
    return json.dumps([
        {"kind": "fact", "summary": "Home is in Paris", "detail": "",
         "subject_label": "Home", "aspect": "location", "event_date": "2026-02-01"},
    ])


def test_out_of_order_event_dates_stale_does_not_supersede(tmp_path):
    """#88: ingest the NEWER-event fact (Paris, 2026-02) first, then the OLDER-event
    fact (London, 2026-01). Without event_date the later-committed London wins on
    ingestion recency (stale-wins bug). With event_date extraction, London's
    earlier asserted date must NOT supersede Paris — Paris stays active."""
    s = _stele(tmp_path)
    ns = "evt"
    paris = [{"role": "user", "content": "Moved — Home is in Paris now. " + "x" * 4100}]
    s.extract.from_session(transcript=paris, scope=MemoryScope(namespace=ns, session_id="s_paris"),
                           llm=_dated_llm, source_ref=None)
    london = [{"role": "user", "content": "Back then Home is in London. " + "y" * 4100}]
    s.extract.from_session(transcript=london, llm=_dated_llm, source_ref=None,
                           scope=MemoryScope(namespace=ns, session_id="s_london"))
    active = {m.summary for m in s.memory.search(
        MemoryQuery(query="Home", scope=MemoryScope(namespace=ns), limit=50))}
    assert "Home is in Paris" in active, "fresh (later-event) fact must survive stale ingest"


def test_in_order_event_dates_newer_supersedes(tmp_path):
    """#88 positive control: in chronological order (London 2026-01 then Paris 2026-02),
    the newer-event fact still supersedes the older — the fix doesn't break the
    normal case (event-date and ingestion recency agree here)."""
    s = _stele(tmp_path)
    ns = "evt2"
    london = [{"role": "user", "content": "Home is in London for now. " + "x" * 4100}]
    s.extract.from_session(transcript=london, llm=_dated_llm, source_ref=None,
                           scope=MemoryScope(namespace=ns, session_id="s_london"))
    paris = [{"role": "user", "content": "Update — Home is in Paris. " + "y" * 4100}]
    s.extract.from_session(transcript=paris, scope=MemoryScope(namespace=ns, session_id="s_paris"),
                           llm=_dated_llm, source_ref=None)
    active = {m.summary for m in s.memory.search(
        MemoryQuery(query="Home", scope=MemoryScope(namespace=ns), limit=50))}
    assert "Home is in Paris" in active
    assert "Home is in London" not in active, "newer-event fact supersedes the older"


def test_experimental_flag_off_disables_fact_consolidation(tmp_path):
    """experimental_evolving_facts=False isolates the low-value atomic-fact currency
    machinery: facts are committed standalone, so an earlier state is NOT superseded
    (both stay active). See docs/benchmarks/findings/memory-value-thesis-2026-06-21.md."""
    cfg = StashConfig.model_validate({
        "backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")},
        "extraction": {"enabled": True, "experimental_evolving_facts": False},
    })
    s = Stele(cfg)
    scope = MemoryScope(namespace="t", session_id="s1")
    transcript = [
        {"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100},
        {"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100},
    ]
    s.extract.from_session(transcript=transcript, scope=scope, llm=_fake_llm, source_ref=None)
    summaries = {m.summary for m in s.memory.search(
        MemoryQuery(query="Test 1", scope=scope, limit=50))}
    # consolidation OFF -> earlier state survives (no supersession chain)
    assert "Test 1 not run" in summaries
    assert "Test 1 passed" in summaries
