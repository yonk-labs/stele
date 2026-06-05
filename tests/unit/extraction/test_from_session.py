"""Stele.extract.from_session: the first-class core API for distilling durable
kinded memory from a real agent transcript (LLM-driven, llm injected)."""

from __future__ import annotations

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.extraction.session import extract_session_memories


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


def test_session_prompt_gives_instruction_and_preference_extraction_guidance():
    """Regression for issue #59.

    The extraction prompt under-specified the `instruction`/`preference` kinds
    (a terse parenthetical gloss, no examples, no explicit directive) while the
    preamble nudged hard toward failure/fact signal. A real LLM therefore emitted
    those two kinds far less often than fact/decision, starving the distilled
    views that derive from them (skills <- instruction, best_practices <-
    preference). The prompt the model actually receives must give those kinds
    concrete, example-bearing guidance plus an explicit directive to extract
    them. Behavioral proof (does a live LLM emit more) needs a live run; this
    pins the delivered prompt through the real extraction call path.
    """
    delivered: list[str] = []

    def spy_llm(prompt: str) -> str:
        delivered.append(prompt)
        return "[]"

    extract_session_memories(spy_llm, "[USER] always run the tests before committing")

    assert len(delivered) == 1
    prompt = delivered[0].lower()
    # concrete examples were added (the old prompt had none at all)
    assert "e.g." in prompt
    # instruction and preference get an explicit extraction directive,
    # not just a parenthetical gloss buried in the kind enumeration
    assert "extract instructions and preferences" in prompt


def test_from_session_empty_transcript_is_a_clean_empty_report():
    s = Stele.from_config({"backend": {"type": "memory"}})
    rep = s.extract.from_session(transcript=[], scope=MemoryScope(namespace="t-empty"),
                                 llm=lambda p: "[]")
    assert rep.stats.accepted_count == 0 and rep.accepted == []
