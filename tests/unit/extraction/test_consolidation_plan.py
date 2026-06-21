from stele.extraction.consolidation import (
    SlotKey,
    Slotted,
    is_newer,
    overlap_warnings,
    plan_chains,
    slot_for,
)
from stele.extraction.session import SessionMemory


def _fact(summary, subject="", aspect="", kind="fact"):
    return SessionMemory(kind=kind, summary=summary, detail="",
                         subject_label=subject, aspect=aspect)


def test_slot_for_only_facts_with_subject_and_aspect():
    assert slot_for(
        _fact("x", "Test 1", "status"),
        scope_key="ns=proj", subject_id="entity:test 1", subject_type="entity",
    ) == SlotKey("ns=proj", "entity", "entity:test 1", "status")
    assert slot_for(
        _fact("x", "Test 1", ""),
        scope_key="ns=proj", subject_id="entity:test 1", subject_type="entity",
    ) is None       # no aspect
    assert slot_for(
        _fact("x", "", "status"),
        scope_key="ns=proj", subject_id="", subject_type="entity",
    ) is None        # no subject_id
    assert slot_for(
        _fact("x", "Test 1", "status", kind="pitfall"),
        scope_key="ns=proj", subject_id="entity:test 1", subject_type="entity",
    ) is None


def test_slot_key_includes_scope_type_subject_id():
    mem = SessionMemory(kind="fact", summary="Postgres 16", detail="",
                        subject_label="postgres", aspect="version")
    slot = slot_for(mem, scope_key="ns=proj", subject_id="service:postgres",
                    subject_type="service")
    assert slot == SlotKey("ns=proj", "service", "service:postgres", "version")


def test_non_fact_has_no_slot():
    mem = SessionMemory(kind="instruction", summary="do x", detail="",
                        subject_label="", aspect="")
    assert slot_for(mem, scope_key="ns=proj", subject_id="x", subject_type="entity") is None


def test_plan_chains_groups_and_orders():
    sk = SlotKey("ns=proj", "entity", "entity:test 1", "status")
    items = [
        Slotted((1, 0), _fact("passed", "Test 1", "status"), sk),
        Slotted((0, 0), _fact("not run", "Test 1", "status"), sk),
        Slotted((0, 1), _fact("chitchat"), None),
    ]
    chains, standalone = plan_chains(items)
    assert [s.memory.summary for s in chains[sk]] == ["not run", "passed"]
    assert [s.memory.summary for s in standalone] == ["chitchat"]


def test_overlap_warnings_flags_multi_aspect_subject():
    chains = {
        SlotKey("ns=proj", "entity", "entity:test 1", "status"): [],
        SlotKey("ns=proj", "entity", "entity:test 1", "coverage"): [],
    }
    assert overlap_warnings(chains) == [("entity:test 1", ["status", "coverage"])]


def test_is_newer():
    assert is_newer(10.0, 5.0) is True
    assert is_newer(5.0, 10.0) is False
    assert is_newer(None, 5.0) is False   # unknown recency never supersedes on mtime
