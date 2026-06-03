from __future__ import annotations

import asyncio

from stele import Stele
from stele.core.memory_record import MemoryScope


def _store_episodes(s: Stele, ns: str, eps: list[tuple[str, str]]) -> None:
    scope = MemoryScope(namespace=ns)
    for sha, subject in eps:
        ref = str(s.store(subject, namespace=ns).reference)
        s.memory.add(text=subject, kind="decision", source_refs=[ref], scope=scope,
                     summary=subject, detail=f"episode {sha}", metadata={"sha": sha})


def test_distill_precedents_surfaces_episodes_with_evidence_and_dedup():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-prec"
    _store_episodes(s, ns, [
        ("b8dd415", "fix packaging so PyPI accepts the upload"),
        ("b8dd415", "fix packaging so PyPI accepts the upload"),  # dup
        ("4ce30a7", "retract the headroom hypothesis"),
    ])
    view = asyncio.run(s.distill.precedents(MemoryScope(namespace=ns)))
    assert view.mode == "precedents"
    assert all(it.source_refs for it in view.items)
    assert len(view.items) == 2  # dedup


def test_distill_precedents_ranks_when_query_given():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-prec-q"
    _store_episodes(s, ns, [
        ("b8dd415", "fix packaging so PyPI accepts the upload"),
        ("4ce30a7", "retract the headroom hypothesis"),
    ])
    view = asyncio.run(
        s.distill.precedents(MemoryScope(namespace=ns), query="packaging PyPI upload")
    )
    # the packaging episode should rank first
    assert "packaging" in view.items[0].summary.lower()
