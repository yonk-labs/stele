"""The rule-aware candidate pass: rule/skill/practice sentences in raw text
must surface as correctly-kinded candidates, not get dropped by lede's
importance filter. This is what makes distill_rules/skills/best_practices work
end-to-end from a raw CLAUDE.md."""

from __future__ import annotations

from stele import Stele
from stele.core.memory_record import MemoryScope


def _kinds_from_text(text: str, ns: str) -> set[str]:
    s = Stele.from_config({"backend": {"type": "memory"}})  # default cfg: extract_rules=True
    scope = MemoryScope(namespace=ns)
    ref = str(s.store(text, namespace=ns).reference)
    rep = s.extract.from_text(text=text, source_refs=[ref], scope=scope)
    return {c.candidate.kind for c in rep.accepted}


def test_extract_surfaces_rules_skills_practices_from_markdown_bullets() -> None:
    text = (
        "- **NEVER use gpt-4o**, it is outdated.\n"
        "- Always use a connection pool, never single connections.\n"
        "- prefer a deterministic check over an LLM judge.\n"
        "- The prod database is in us-west-2.\n"
    )
    kinds = _kinds_from_text(text, "t-rules-extract")
    assert "pitfall" in kinds, kinds          # the NEVER rule
    assert "instruction" in kinds, kinds       # the always-use habit (skill)
    assert "preference" in kinds, kinds        # the prefer practice


def test_plain_facts_still_extract_without_rule_noise() -> None:
    # A fact-only doc should not gain spurious rule candidates.
    text = "The prod database moved to us-west-2 on 1 April 2024. lede runs in under a millisecond."
    kinds = _kinds_from_text(text, "t-facts-only")
    assert kinds <= {"fact", "summary", "stat", "metadata"}, kinds
