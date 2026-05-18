"""100-doc corpus: living knowledge, tool-call capture, PII filtering.

Runs deterministically on the memory backend (no DSN needed) so it is a
real CI gate, not a skipped one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from benchmarks.corpus import sample_corpus
from stele.core.memory_record import MemoryQuery, MemoryScope
from stele.core.stash import Stele
from stele.runtime.demo import SteleAgentSession
from stele.workgraph.store import InProcessWorkGraphStore

CORPUS = sample_corpus(100)


def test_corpus_shape() -> None:
    assert len(CORPUS) == 100
    assert len({d.id for d in CORPUS}) == 100
    assert {d.lane for d in CORPUS} == {
        "versioned_docs", "retracted_claim", "policy_update",
        "account_state", "pii_heavy", "tool_output", "plain",
    }


def test_pii_never_survives_store_or_recall() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    scope = MemoryScope(namespace="corpus")
    pii_docs = [d for d in CORPUS if d.pii]
    assert pii_docs  # corpus actually contains PII to test
    for d in pii_docs:
        pii = d.pii
        assert pii is not None
        stored = s.store(d.text, namespace="corpus")
        fetched = s.fetch(stored.reference).content
        body = fetched if isinstance(fetched, str) else fetched.decode()
        assert pii not in body, f"{d.id}: raw PII survived store/fetch"
        s.memory.add(text=body, kind="fact",
                     source_refs=[stored.reference], scope=scope)
    leaks = 0
    for d in pii_docs:
        pii = d.pii
        assert pii is not None
        r = s.recall(query=d.fact, scope=scope)
        if pii in r.context:
            leaks += 1
    assert leaks == 0, f"PII leaked into recall {leaks} times"
    s.close()


def test_tool_call_capture_loop_over_corpus() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    sess = SteleAgentSession(
        stele=s, wg_store=InProcessWorkGraphStore(),
        namespace="corpus", session_id="cap",
    )
    sess.start("corpus capture run")
    tool_docs = [d for d in CORPUS if d.lane == "tool_output"][:5]
    for d in tool_docs:
        node = sess.observe_tool("Bash", d.text)
        assert node.source_refs[0].startswith("stele://")
    pack = sess.recall_and_pack(query="exit code")
    for line in [ln for ln in pack.dynamic_context.splitlines() if ln.strip()]:
        assert "stele://" in line
    for d in tool_docs:
        if d.pii:
            assert d.pii not in pack.dynamic_context
            assert d.pii not in sess.resume()
    assert sess.end() == 1
    s.close()


def test_living_knowledge_memory_layer_over_corpus() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    scope = MemoryScope(namespace="lk")

    # supersession: ingest a v1 then a v2 that supersedes it
    v1 = s.memory.add(text="service auth uses API keys", kind="fact",
                       source_refs=["stele://lk/v1"], scope=scope)
    t_mid = datetime.now(UTC)
    import time

    time.sleep(0.01)
    s.memory.add(text="service auth uses OAuth2", kind="fact",
                 source_refs=["stele://lk/v2"], scope=scope,
                 supersedes=[v1.record.id])

    current = s.memory.search(MemoryQuery(query="service auth", scope=scope))
    assert any("OAuth2" in m.text for m in current)
    assert not any("API keys" in m.text for m in current)  # superseded hidden

    past = s.memory.search(
        MemoryQuery(query="service auth", scope=scope, as_of=t_mid)
    )
    assert any("API keys" in m.text for m in past)  # historical view

    # retraction: retracted_claim lane → memory.retract flips status
    r = s.memory.add(text="compound-Z prevents disease", kind="fact",
                     source_refs=["stele://lk/study"], scope=scope)
    rec = s.memory.retract(r.record.id, reason="retracted by journal")
    assert rec.status == "retracted"
    got = s.memory.get(r.record.id)
    assert got is not None and got.status == "retracted"
    s.close()


@pytest.mark.parametrize("n", [10, 50, 100])
def test_corpus_is_deterministic(n: int) -> None:
    assert [d.id for d in sample_corpus(n)] == [d.id for d in sample_corpus(n)]
    assert sample_corpus(n)[0] == sample_corpus(n)[0]
