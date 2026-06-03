"""Stele.extract.from_session: the first-class core API for distilling durable
kinded memory from a real agent transcript (LLM-driven, llm injected)."""

from __future__ import annotations

from stele import Stele
from stele.core.memory_record import MemoryScope


def test_from_session_extracts_kinded_memories_with_evidence():
    s = Stele.from_config({"backend": {"type": "memory"}})
    scope = MemoryScope(namespace="t-from-session")
    transcript = [
        {"role": "user", "content": "never use gpt-4o for this project"},
        {"role": "assistant",
         "content": "ran cargo build, got exit code 1, missing import; added it and it passed"},
    ]

    def fake_llm(prompt: str) -> str:
        return (
            '[{"kind":"instruction","summary":"never use gpt-4o","detail":"user rule"},'
            ' {"kind":"pitfall","summary":"cargo build failed with exit code 1",'
            ' "detail":"missing import; add it"}]'
        )

    rep = s.extract.from_session(transcript=transcript, scope=scope, llm=fake_llm)
    assert rep.stats.accepted_count >= 2
    kinds = {a.candidate.kind for a in rep.accepted}
    assert "instruction" in kinds and "pitfall" in kinds
    assert rep.source_refs and rep.source_refs[0].startswith("stele://")

    mems = s.memory.list(scope, None, limit=50)
    assert any(m.summary == "never use gpt-4o" and m.kind == "instruction" for m in mems)
    assert any(m.kind == "pitfall" for m in mems)
    assert all(m.source_refs for m in mems)  # evidence


def test_from_session_empty_transcript_is_a_clean_empty_report():
    s = Stele.from_config({"backend": {"type": "memory"}})
    rep = s.extract.from_session(transcript=[], scope=MemoryScope(namespace="t-empty"),
                                 llm=lambda p: "[]")
    assert rep.stats.accepted_count == 0 and rep.accepted == []
