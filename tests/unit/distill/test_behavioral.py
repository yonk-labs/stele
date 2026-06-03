from __future__ import annotations

import asyncio

from stele import Stele
from stele.core.memory_record import MemoryScope


def _add(s, ns, kind, summary, text, detail="", metadata=None):
    scope = MemoryScope(namespace=ns)
    ref = str(s.store(text, namespace=ns).reference)
    s.memory.add(text=text, kind=kind, source_refs=[ref], scope=scope,
                 summary=summary, detail=detail, metadata=metadata or {})


def test_skills_surfaced_with_evidence():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-skill"
    _add(s, ns, "instruction", "always use connection pools", "always use a connection pool")
    view = asyncio.run(s.distill.skills(MemoryScope(namespace=ns)))
    assert view.mode == "skills"
    assert view.items and all(it.source_refs for it in view.items)


def test_best_practices_are_suggest_only():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-bp"
    _add(s, ns, "preference", "prefer deterministic checks",
         "prefer a deterministic check over an LLM judge")
    view = asyncio.run(s.distill.best_practices(MemoryScope(namespace=ns)))
    assert view.mode == "best_practices"
    assert view.items
    for it in view.items:
        assert not hasattr(it, "enforce") and not hasattr(it, "gate")  # suggest-not-force


def test_rules_pair_dont_with_do_instead_in_family():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-rules"
    _add(s, ns, "pitfall", "gpt-4o is outdated", "gpt-4o is outdated, do not use it",
         metadata={"do_instead": "use gpt-5-mini", "domain": "config"})
    view = asyncio.run(s.distill.rules(MemoryScope(namespace=ns)))
    assert view.mode == "rules"
    r = view.items[0]
    assert "gpt-4o" in r.dont
    assert "gpt-5-mini" in r.do_instead          # in-family kept
    assert r.source_refs


def test_rules_drop_cross_vendor_do_instead():
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-rules-x"
    _add(s, ns, "pitfall", "gpt-4o is outdated", "gpt-4o is outdated",
         metadata={"do_instead": "use claude-opus"})  # cross-vendor
    view = asyncio.run(s.distill.rules(MemoryScope(namespace=ns)))
    assert view.items[0].do_instead == ""          # cross-vendor dropped
    assert not view.used_llm


def test_rules_use_llm_to_synthesize_do_instead():
    # The LLM refine pass returns JSON; it supplies the do_instead the source
    # did not state (and the in-family guard still applies downstream).
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-rules-llm"
    _add(s, ns, "pitfall", "gpt-4o is outdated", "gpt-4o is outdated")  # no do_instead
    reply = '[{"i": 0, "dont": "gpt-4o is outdated", "do_instead": "use gpt-5-mini"}]'
    s._distill_llm = lambda prompt: reply   # inject a fake LLM returning refine JSON
    view = asyncio.run(s.distill.rules(MemoryScope(namespace=ns)))
    assert "gpt-5-mini" in view.items[0].do_instead
    assert view.items[0].source_refs          # evidence carried through refine
    assert view.used_llm


def test_refine_drops_noise_and_falls_back_on_bad_json():
    # Two pitfall candidates: one real rule, one doc-prose false positive.
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-rules-noise"
    _add(s, ns, "pitfall", "never use gpt-4o", "never use gpt-4o")
    _add(s, ns, "pitfall", "skip extras you don't use to keep the venv lean",
         "skip extras you don't use to keep the venv lean")
    # LLM keeps only index of the real rule (drops the prose). Order of
    # active_memories is insertion order, so build the reply by matching text.
    def fake_llm(prompt: str) -> str:
        # keep whichever candidate is the genuine gpt-4o rule
        lines = [ln for ln in prompt.splitlines() if "gpt-4o" in ln]
        idx = int(lines[0].split(".")[0]) if lines else 0
        return f'[{{"i": {idx}, "dont": "never use gpt-4o", "do_instead": ""}}]'
    s._distill_llm = fake_llm
    view = asyncio.run(s.distill.rules(MemoryScope(namespace=ns)))
    assert len(view.items) == 1                # the prose false-positive was dropped
    assert "gpt-4o" in view.items[0].dont

    # bad (non-JSON) LLM output -> deterministic fallback keeps both candidates
    s2 = Stele.from_config({"backend": {"type": "memory"}})
    _add(s2, ns, "pitfall", "never use gpt-4o", "never use gpt-4o")
    _add(s2, ns, "pitfall", "do not edit vendored tests", "do not edit vendored tests")
    s2._distill_llm = lambda prompt: "sorry I cannot do that"
    view2 = asyncio.run(s2.distill.rules(MemoryScope(namespace=ns)))
    assert len(view2.items) == 2               # fallback to deterministic candidates


def test_rules_reproduce_gold_gpt4o_pair():
    from benchmarks.external.memory_modes.distill_gold import GOLD
    s = Stele.from_config({"backend": {"type": "memory"}})
    ns = "t-rules-gold"
    for g in GOLD["rules"]:
        _add(s, ns, "pitfall", g["dont"], f"{g['dont']} (outdated/forbidden)",
             metadata={"do_instead": g["do_instead"], "domain": g["domain"]})
    view = asyncio.run(s.distill.rules(MemoryScope(namespace=ns)))
    pairs = {(r.dont, r.do_instead) for r in view.items}
    assert ("use gpt-4o", "use gpt-5-mini") in pairs
