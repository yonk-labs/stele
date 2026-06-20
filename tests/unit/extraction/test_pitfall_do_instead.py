"""Issue #62: pitfall extraction must carry a `do_instead` remediation and the
prompt must frame pitfalls as the action NOT to repeat (and not mis-tag facts).

The plumbing (capture do_instead -> thread into pitfall metadata) is unit-tested
here; distill.rules already reads metadata["do_instead"]. The behavioral quality
of the tightened pitfall definition (fewer mis-classified facts) is validated
separately via the paired-transcript A/B + A/A recipe, not a unit test.
"""

from __future__ import annotations

import json

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.extraction.session import extract_session_memories


def test_extract_captures_do_instead_for_pitfall():
    payload = json.dumps([
        {"kind": "pitfall",
         "summary": "assumed the cache key was the bare session_id",
         "detail": "stale hits leaked across turns",
         "do_instead": "key the cache on session_id:turn_index"},
    ])
    out = extract_session_memories(lambda _p: payload, "WINDOW")
    assert len(out) == 1
    assert out[0].kind == "pitfall"
    assert out[0].do_instead == "key the cache on session_id:turn_index"


def test_from_session_threads_do_instead_into_pitfall_metadata():
    s = Stele.from_config({"backend": {"type": "memory"}})
    scope = MemoryScope(namespace="t-62-meta")
    transcript = [{"role": "assistant", "content": "ran the migration against prod by mistake"}]

    def fake_llm(_p: str) -> str:
        return json.dumps([
            {"kind": "pitfall", "summary": "ran the migration against prod by mistake",
             "detail": "no dry-run", "do_instead": "run with --dry-run first"},
        ])

    s.extract.from_session(transcript=transcript, scope=scope, llm=fake_llm)
    pit = [m for m in s.memory.list(scope, None, limit=50) if m.kind == "pitfall"]
    assert len(pit) == 1
    assert pit[0].metadata.get("do_instead") == "run with --dry-run first"


def test_session_prompt_tightens_pitfall_and_requests_do_instead():
    """Regression for issue #62.

    The old `pitfall` gloss ("something that FAILED, a deadend or mistake") was
    loose enough to swallow neutral facts, and remediation lived only in a
    separate `workaround` item, so pitfall memories never carried their own
    do_instead. The delivered prompt must now (1) frame the pitfall summary as
    the action NOT to repeat, (2) ask for a do_instead remediation key, and
    (3) tell the model not to tag a neutral fact as a pitfall. Behavioral proof
    (a live LLM mis-tags fewer facts) needs a live A/B run; this pins the
    delivered prompt through the real extraction call path.
    """
    delivered: list[str] = []

    def spy_llm(prompt: str) -> str:
        delivered.append(prompt)
        return "[]"

    extract_session_memories(spy_llm, "[RESULT ERROR] migration blew up")

    assert len(delivered) == 1
    prompt = delivered[0].lower()
    assert "do_instead" in prompt            # remediation captured inline on the pitfall
    assert "not to repeat" in prompt         # summary framed as the action to avoid
    assert "neutral fact" in prompt          # explicit "don't mis-tag facts" guidance
