from __future__ import annotations

from benchmarks.external.memory_modes.distill_demo import distill_all, seed_gold_memories
from stele import Stele


def test_distill_all_reproduces_gold_on_seeded_memory():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "demo-ns"
    seed_gold_memories(s, ns)
    views = distill_all(s, ns)
    assert set(views) == {"facts", "precedents", "state", "skills", "best_practices", "rules"}
    # facts reproduce the gold project set
    fact_ids = [it.summary.split(":")[0] for it in views["facts"].items]
    from benchmarks.external.memory_modes.distill_gold import score_view
    assert score_view("facts", fact_ids)["recall"] >= 0.83
    # rules reproduce the gpt-4o -> gpt-5-mini pair
    assert any(getattr(r, "do_instead", "") == "use gpt-5-mini" for r in views["rules"].items)
