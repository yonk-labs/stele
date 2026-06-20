"""Task 2: extraction must emit subject_label + aspect for named-entity facts
so that a later consolidation step can group evolving fact states.

The plumbing (capture subject_label/aspect -> thread into extraction output) is
unit-tested here. Behavioral quality (LLM correctly identifies named entities)
is validated separately via live transcript runs.
"""

from __future__ import annotations

import json

from stele.extraction.session import extract_session_memories


def test_extract_captures_subject_and_aspect():
    payload = json.dumps([
        {"kind": "fact", "summary": "Test 1 passed", "detail": "",
         "subject_label": "Test 1", "aspect": "status"},
        {"kind": "fact", "summary": "no subject here", "detail": ""},
    ])
    out = extract_session_memories(lambda _p: payload, "WINDOW")
    assert out[0].subject_label == "Test 1" and out[0].aspect == "status"
    assert out[1].subject_label == "" and out[1].aspect == ""


def test_extract_subject_aspect_strips_whitespace():
    payload = json.dumps([
        {"kind": "fact", "summary": "Auth service running", "detail": "",
         "subject_label": "  auth-service  ", "aspect": "  status  "},
    ])
    out = extract_session_memories(lambda _p: payload, "WINDOW")
    assert out[0].subject_label == "auth-service"
    assert out[0].aspect == "status"


def test_extract_subject_aspect_defaults_to_empty_string():
    payload = json.dumps([
        {"kind": "decision", "summary": "chose Postgres 16", "detail": "full-text search"},
    ])
    out = extract_session_memories(lambda _p: payload, "WINDOW")
    assert out[0].subject_label == ""
    assert out[0].aspect == ""


def test_extract_preserves_do_instead_alongside_subject_aspect():
    """Regression: subject_label/aspect must coexist with do_instead (#62)."""
    payload = json.dumps([
        {"kind": "pitfall", "summary": "used bare session_id as cache key",
         "detail": "stale hits", "do_instead": "key on session_id:turn_index",
         "subject_label": "cache", "aspect": "config"},
    ])
    out = extract_session_memories(lambda _p: payload, "WINDOW")
    assert out[0].do_instead == "key on session_id:turn_index"
    assert out[0].subject_label == "cache"
    assert out[0].aspect == "config"


def test_session_prompt_requests_subject_label_and_aspect():
    """The delivered prompt must ask for subject_label and aspect for named-entity facts."""
    delivered: list[str] = []

    def spy_llm(prompt: str) -> str:
        delivered.append(prompt)
        return "[]"

    extract_session_memories(spy_llm, "[RESULT ok] test_auth passed in 0.3s")

    assert len(delivered) == 1
    prompt = delivered[0].lower()
    assert "subject_label" in prompt
    assert "aspect" in prompt
