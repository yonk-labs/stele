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
