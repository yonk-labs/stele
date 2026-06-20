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
    assert slot_for(_fact("x", "Test 1", "status")) == SlotKey("test 1", "status")
    assert slot_for(_fact("x", "Test 1", "")) is None       # no aspect
    assert slot_for(_fact("x", "", "status")) is None        # no subject
    assert slot_for(_fact("x", "Test 1", "status", kind="pitfall")) is None


def test_plan_chains_groups_and_orders():
    items = [
        Slotted((1, 0), _fact("passed", "Test 1", "status"), SlotKey("test 1", "status")),
        Slotted((0, 0), _fact("not run", "Test 1", "status"), SlotKey("test 1", "status")),
        Slotted((0, 1), _fact("chitchat"), None),
    ]
    chains, standalone = plan_chains(items)
    assert [s.memory.summary for s in chains[SlotKey("test 1", "status")]] == ["not run", "passed"]
    assert [s.memory.summary for s in standalone] == ["chitchat"]


def test_overlap_warnings_flags_multi_aspect_subject():
    chains = {SlotKey("test 1", "status"): [], SlotKey("test 1", "coverage"): []}
    assert overlap_warnings(chains) == [("test 1", ["status", "coverage"])]


def test_is_newer():
    assert is_newer(10.0, 5.0) is True
    assert is_newer(5.0, 10.0) is False
    assert is_newer(None, 5.0) is False   # unknown recency never supersedes on mtime
