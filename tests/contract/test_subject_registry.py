"""Contract: registry-backed identity fixes cross-session label drift (#69),
keeps different users isolated, and resolves self-referential subjects."""
from __future__ import annotations

import json

from stele.core.config import StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope
from stele.core.stash import Stele


def _stele(tmp_path, **aliases: str) -> Stele:
    cfg = StashConfig.model_validate({
        "backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")},
        "extraction": {"enabled": True, "subject_aliases": aliases},
    })
    return Stele(cfg)


def _llm(subject_label: str, value: str):  # type: ignore[return]
    def _fake(_window: str) -> str:
        return json.dumps([{"kind": "fact", "summary": value, "detail": "",
                            "subject_label": subject_label, "aspect": "version"}])
    return _fake


def test_alias_resolves_cross_session_label_drift(tmp_path):
    # #69: day1 says "postgres", day2 says "production" for the same entity.
    # The fake LLM emits no subject_type, so day1 mints entity:postgres.
    # The alias maps "production" -> entity:postgres (matching day1's subject_id)
    # so day2's fact supersedes day1's instead of creating a new distinct chain.
    s = _stele(tmp_path, production="entity:postgres")
    ns = "p69"
    s.extract.from_session(
        transcript=[{"role": "user", "content": "pg 14 " + "x" * 4100}],
        scope=MemoryScope(namespace=ns, session_id="d1"),
        llm=_llm("postgres", "Postgres 14"),
        source_ref=None,
    )
    s.extract.from_session(
        transcript=[{"role": "user", "content": "pg 16 " + "y" * 4100}],
        scope=MemoryScope(namespace=ns, session_id="d2"),
        llm=_llm("production", "Postgres 16"),
        source_ref=None,
    )
    active = s.memory.search(MemoryQuery(
        query="Postgres", scope=MemoryScope(namespace=ns), limit=50,
    ))
    summaries = {m.summary for m in active}
    assert "Postgres 16" in summaries
    assert "Postgres 14" not in summaries   # superseded via alias -> one head

    # Verify "Postgres 14" was genuinely superseded (not merely absent / never stored).
    hist = s.memory.search(MemoryQuery(
        query="Postgres", scope=MemoryScope(namespace=ns), limit=50,
        include_superseded=True,
    ))
    hist_summaries = {m.summary for m in hist}
    assert "Postgres 14" in hist_summaries  # stored, then moved to superseded


def test_no_alias_keeps_distinct_no_silent_merge(tmp_path):
    # Without an alias, distinct labels stay distinct (false-negative bias).
    s = _stele(tmp_path)
    ns = "pnoalias"
    s.extract.from_session(
        transcript=[{"role": "user", "content": "pg 14 " + "x" * 4100}],
        scope=MemoryScope(namespace=ns, session_id="d1"),
        llm=_llm("postgres", "Postgres 14"),
        source_ref=None,
    )
    s.extract.from_session(
        transcript=[{"role": "user", "content": "pg 16 " + "y" * 4100}],
        scope=MemoryScope(namespace=ns, session_id="d2"),
        llm=_llm("production", "Postgres 16"),
        source_ref=None,
    )
    active = s.memory.search(MemoryQuery(
        query="Postgres", scope=MemoryScope(namespace=ns), limit=50,
    ))
    summaries = {m.summary for m in active}
    assert summaries == {"Postgres 14", "Postgres 16"}   # both active, nothing merged


def test_handoff_merges_cross_session_without_alias(tmp_path):
    # The handoff path: no alias configured. Day2's LLM returns the existing
    # subject_id for the drifted label "production". The validated handoff causes
    # day2's fact to supersede day1's in the entity:postgres version slot.
    s = _stele(tmp_path)
    ns = "phandoff"
    s.extract.from_session(
        transcript=[{"role": "user", "content": "pg 14 " + "x" * 4100}],
        scope=MemoryScope(namespace=ns, session_id="d1"),
        llm=_llm("postgres", "Postgres 14"),
        source_ref=None,
    )

    def _llm_handoff(_w: str) -> str:
        # Day1 minted "entity:postgres" (subject_type defaults to "entity"); the
        # handoff returns that exact id for the drifted label "production".
        return json.dumps([{
            "kind": "fact",
            "summary": "Postgres 16",
            "detail": "",
            "subject_label": "production",
            "aspect": "version",
            "subject_id": "entity:postgres",
        }])

    s.extract.from_session(
        transcript=[{"role": "user", "content": "pg 16 " + "y" * 4100}],
        scope=MemoryScope(namespace=ns, session_id="d2"),
        llm=_llm_handoff,
        source_ref=None,
    )
    active = {m.summary for m in s.memory.search(MemoryQuery(
        query="Postgres", scope=MemoryScope(namespace=ns), limit=50,
    ))}
    assert "Postgres 16" in active
    assert "Postgres 14" not in active   # merged via handoff

    # Verify "Postgres 14" was genuinely superseded.
    hist = {m.summary for m in s.memory.search(MemoryQuery(
        query="Postgres", scope=MemoryScope(namespace=ns), limit=50,
        include_superseded=True,
    ))}
    assert "Postgres 14" in hist  # stored, then moved to superseded


def test_two_users_do_not_collide(tmp_path):
    # Same label + aspect, different user_id -> separate chains, no supersession.
    s = _stele(tmp_path)
    ns = "pusers"
    s.extract.from_session(
        transcript=[{"role": "user", "content": "loc " + "x" * 4100}],
        scope=MemoryScope(namespace=ns, user_id="A", session_id="s"),
        llm=_llm("location", "Paris"),
        source_ref=None,
    )
    s.extract.from_session(
        transcript=[{"role": "user", "content": "loc " + "y" * 4100}],
        scope=MemoryScope(namespace=ns, user_id="B", session_id="s"),
        llm=_llm("location", "London"),
        source_ref=None,
    )
    a = {m.summary for m in s.memory.search(MemoryQuery(
        query="Paris London", scope=MemoryScope(namespace=ns, user_id="A"), limit=50,
    ))}
    b = {m.summary for m in s.memory.search(MemoryQuery(
        query="Paris London", scope=MemoryScope(namespace=ns, user_id="B"), limit=50,
    ))}
    assert "Paris" in a and "London" not in a
    assert "London" in b and "Paris" not in b


def test_self_referential_same_user_supersedes(tmp_path):
    # Same user moving: "I" in Paris then "I" in London -> one active head.
    # "I" is self-referential -> resolves to user:u9, so both facts share the
    # same subject_id and the second supersedes the first.
    s = _stele(tmp_path)
    ns = "pself"
    for sess, city in (("d1", "Paris"), ("d2", "London")):
        s.extract.from_session(
            transcript=[{"role": "user", "content": f"i am in {city} " + "z" * 4100}],
            scope=MemoryScope(namespace=ns, user_id="u9", session_id=sess),
            llm=_llm("I", city),
            source_ref=None,
        )
    active = {m.summary for m in s.memory.search(MemoryQuery(
        query="Paris London", scope=MemoryScope(namespace=ns, user_id="u9"), limit=50,
    ))}
    assert "London" in active
    assert "Paris" not in active   # self-ref -> user:u9 chain, Paris superseded

    # Verify "Paris" was genuinely superseded.
    hist = {m.summary for m in s.memory.search(MemoryQuery(
        query="Paris London", scope=MemoryScope(namespace=ns, user_id="u9"), limit=50,
        include_superseded=True,
    ))}
    assert "Paris" in hist  # stored, then moved to superseded


def test_backfill_maps_legacy_chains(tmp_path):
    # Simulate a pre-registry store: a memory with canonical_subject but no subject_id.
    s = _stele(tmp_path)
    ns = "pbf"
    scope = MemoryScope(namespace=ns)
    rec = s.memory.add(text="Postgres 14", kind="fact", source_refs=["stele://x/y"],
                       scope=MemoryScope(namespace=ns, session_id="d1"),
                       summary="Postgres 14", confidence=0.8,
                       metadata={"canonical_subject": "postgres", "aspect": "version"})
    from stele.extraction.migration import backfill_subject_ids
    n = backfill_subject_ids(s.memory, scope)
    assert n == 1
    got = s.memory.get(rec.record.id)
    assert got.metadata["subject_id"] == "entity:postgres"
    assert got.metadata["subject_type"] == "entity"
    assert backfill_subject_ids(s.memory, scope) == 0   # idempotent: re-run is a no-op
