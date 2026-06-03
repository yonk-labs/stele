"""Streaming session ingest: the live conversation feed that reduces each event
through reduce_event and stores ONE keep120 artifact (never the raw bytes)."""

from __future__ import annotations

import json
from pathlib import Path

from stele import Stele
from stele.core.config import ExtractionConfig
from stele.extraction.ingest import (
    ingest_session,
    reduce_config_from,
    reduce_stream,
)
from stele.extraction.session import ReduceConfig


def _events() -> list[dict]:
    return [
        {"type": "user", "message": {"content": "ship the migration"}},
        {"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "", "signature": "B64" * 400},  # dropped
            {"type": "text", "text": "running the build"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "cargo build"}},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_result", "content": "error[E0432]: unresolved import",
             "is_error": True},
        ]}},
        {"type": "file-history-snapshot", "snapshot": "x" * 5000},  # dropped
        {"type": "assistant", "message": {"content": [
            {"type": "tool_result", "content": "OK " + "z" * 500, "is_error": False},  # ->120
        ]}},
    ]


def test_reduce_stream_drops_noise_keeps_signal() -> None:
    turns = reduce_stream(_events())
    roles = [t.role for t in turns]
    assert roles == ["user", "assistant", "tool", "result", "result"]
    assert turns[3].is_error and turns[3].text.startswith("error[E0432]")
    assert len(turns[4].text) == 120 and not turns[4].is_error  # success kept, truncated
    blob = "\n".join(t.text for t in turns)
    assert "B64" not in blob  # signature never emitted


def test_ingest_session_from_events_stores_one_reduced_artifact() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    rep = ingest_session(s, transcript=_events(), namespace="t-ingest")
    assert rep["ref"].startswith("stele://")
    assert rep["turns"] == 5
    # what was stored is exactly the reduced render, not the raw events
    from stele.extraction.session import render
    assert rep["chars"] == len(render(reduce_stream(_events())))


def test_ingest_session_from_jsonl_path(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in _events()))
    s = Stele.from_config({"backend": {"type": "memory"}})
    rep = ingest_session(s, transcript=p, namespace="t-ingest-file", session_id="sess-1")
    assert rep["ref"] and rep["turns"] == 5


def test_thin_session_returns_no_ref() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    # only non-conversation lines -> nothing durable
    rep = ingest_session(s, transcript=[{"type": "file-history-snapshot", "x": 1}],
                         namespace="t-thin")
    assert rep["ref"] is None and rep["turns"] == 0


def test_keep_raw_stores_exact_bytes_alongside_reduced(tmp_path: Path) -> None:
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in _events()))
    s = Stele.from_config({"backend": {"type": "memory"}})
    rep = ingest_session(s, transcript=p, namespace="t-raw", keep_raw=True)
    assert rep["ref"] and rep["raw_ref"]
    assert rep["ref"] != rep["raw_ref"]  # two distinct artifacts: reduced + raw
    # without keep_raw there is no second artifact
    rep2 = ingest_session(s, transcript=p, namespace="t-raw2")
    assert rep2["raw_ref"] is None


def test_keep_raw_is_a_noop_for_event_streams() -> None:
    # raw bytes only exist for a path; a live event stream has no raw file
    s = Stele.from_config({"backend": {"type": "memory"}})
    rep = ingest_session(s, transcript=_events(), namespace="t-raw-stream", keep_raw=True)
    assert rep["ref"] and rep["raw_ref"] is None


def test_full_tier_keeps_more_than_keep120() -> None:
    big = [{"type": "assistant", "message": {"content": [
        {"type": "tool_result", "content": "R" * 4000, "is_error": False}]}}]
    s = Stele.from_config({"backend": {"type": "memory"}})
    keep120 = ingest_session(s, transcript=list(big), namespace="t-k120")
    full = ingest_session(s, transcript=list(big), namespace="t-full",
                          cfg=ReduceConfig(result_chars=None))
    assert full["chars"] > keep120["chars"]  # full tier retains the whole body


def test_reduce_config_threads_extraction_knobs() -> None:
    cfg = reduce_config_from(ExtractionConfig(reduce_result_chars=300,
                                              reduce_drop_success_results=True))
    assert cfg.result_chars == 300 and cfg.drop_success_results is True
    # with drop on, the successful result is gone but the error survives
    turns = reduce_stream(_events(), cfg)
    assert [t.role for t in turns] == ["user", "assistant", "tool", "result"]
    assert turns[-1].is_error
