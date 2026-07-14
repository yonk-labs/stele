from __future__ import annotations

import asyncio

from benchmarks.external.memory_modes.distill_gold import GOLD
from stele import Stele
from stele.core.memory_record import MemoryScope


def _store_facts(s: Stele, ns: str, facts: list[tuple[str, str]]) -> None:
    scope = MemoryScope(namespace=ns)
    for proj, text in facts:
        ref = str(s.store(text, namespace=ns).reference)
        s.memory.add(text=text, kind="fact", source_refs=[ref], scope=scope,
                     summary=f"{proj}: {text}", metadata={"project": proj})


def test_distill_facts_surfaces_facts_with_evidence_and_dedup():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-facts"
    _store_facts(s, ns, [("pg-raggraph", "GraphRAG on plain Postgres"),
                         ("pg-raggraph", "GraphRAG on plain Postgres"),  # dup
                         ("lede", "sub-millisecond summarization")])
    view = asyncio.run(s.distill.facts(MemoryScope(namespace=ns)))
    assert view.mode == "facts"
    assert not view.used_llm
    assert all(it.source_refs for it in view.items)          # evidence (SC-011)
    summaries = " ".join(it.summary for it in view.items)
    assert "pg-raggraph" in summaries and "lede" in summaries
    assert len(view.items) == 2                               # dedup collapsed the duplicate


def test_distill_facts_reproduces_gold_fact_set():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-facts-gold"
    _store_facts(s, ns, [(g["id"], g["text"]) for g in GOLD["facts"]])
    view = asyncio.run(s.distill.facts(MemoryScope(namespace=ns)))
    surfaced = " ".join(it.summary for it in view.items)
    hits = sum(1 for g in GOLD["facts"] if g["id"] in surfaced)
    assert hits >= 10, f"reproduced {hits}/12 gold facts"      # SC-003 floor


def test_distill_facts_excludes_superseded_facts():
    """active_memories must pass status_filter=['active'] so superseded records
    are not surfaced. Before the fix, distill_facts would return 2 items
    (both active and superseded); after the fix it returns exactly 1."""
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-facts-supersede"
    scope = MemoryScope(namespace=ns)

    ref1 = str(s.store("old fact", namespace=ns).reference)
    first = s.memory.add(
        text="prod db is in us-east-1",
        kind="fact",
        source_refs=[ref1],
        scope=scope,
        summary="prod-db-region: us-east-1",
    )

    ref2 = str(s.store("new fact", namespace=ns).reference)
    s.memory.add(
        text="prod db moved to us-west-2",
        kind="fact",
        source_refs=[ref2],
        scope=scope,
        summary="prod-db-region: us-west-2",
        supersedes=[first.record.id],
    )

    view = asyncio.run(s.distill.facts(MemoryScope(namespace=ns)))

    # Only the active head should surface -- not the superseded predecessor.
    assert len(view.items) == 1, (
        f"expected 1 item (active head only), got {len(view.items)}: "
        + str([i.summary for i in view.items])
    )
    assert "us-west-2" in view.items[0].summary
    assert "us-east-1" not in view.items[0].summary


def test_distill_items_carry_source_memory_id() -> None:
    """Every 1:1 view item joins back to its store row exactly (bento#962):
    item.memory_id == the id memory.add returned, and memory.get(memory_id)
    resolves. Dedup keeps the FIRST occurrence's id."""
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-facts-memid"
    scope = MemoryScope(namespace=ns)
    ref = str(s.store("evidence", namespace=ns).reference)
    first = s.memory.add(
        text="the audit_window is 455", kind="fact",
        source_refs=[ref], scope=scope,
    )
    s.memory.add(  # normalized duplicate — collapses into `first`
        text="The audit_window is 455", kind="fact",
        source_refs=[ref], scope=scope,
    )
    view = asyncio.run(s.distill.facts(scope))
    assert len(view.items) == 1
    assert view.items[0].memory_id == first.record.id
    assert s.memory.get(view.items[0].memory_id) is not None
