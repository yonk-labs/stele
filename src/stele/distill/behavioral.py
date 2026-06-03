from __future__ import annotations

from collections.abc import Sequence

from stele.core.memory_record import MemoryRecord, MemoryScope
from stele.distill.base import active_memories
from stele.distill.models import DistilledItem, DistilledView, Rule

_VENDOR_TOKENS: dict[str, str] = {
    "gpt": "openai", "openai": "openai", "o1": "openai", "o3": "openai",
    "claude": "anthropic", "anthropic": "anthropic",
    "gemini": "google", "gemma": "google",
    "llama": "meta", "qwen": "qwen", "mistral": "mistral", "deepseek": "deepseek",
}


def _vendor(text: str) -> str | None:
    low = text.lower()
    for tok, vendor in _VENDOR_TOKENS.items():
        if tok in low:
            return vendor
    return None


def _in_family(dont: str, do_instead: str) -> bool:
    dv, rv = _vendor(dont), _vendor(do_instead)
    return not (dv is not None and rv is not None and dv != rv)


def _dedup_items(records: Sequence[MemoryRecord], mode: str) -> DistilledView:
    items: list[DistilledItem] = []
    seen: set[str] = set()
    for m in records:
        key = (m.summary or m.text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(DistilledItem(
            summary=m.summary or m.text,
            detail=m.detail or "",
            confidence=m.confidence,
            source_refs=list(m.source_refs),
        ))
    return DistilledView(mode=mode, items=items, used_llm=False, stats={"n": float(len(items))})


async def distill_skills(d: object, scope: MemoryScope) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    recs = [m for m in active_memories(memory, scope) if m.kind == "instruction"]
    return _dedup_items(recs, "skills")


async def distill_best_practices(d: object, scope: MemoryScope) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    recs = [m for m in active_memories(memory, scope) if m.kind == "preference"]
    return _dedup_items(recs, "best_practices")


async def distill_rules(d: object, scope: MemoryScope) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    llm = d._llm  # type: ignore[attr-defined]
    synthesis = getattr(d._config, "synthesis", "auto")  # type: ignore[attr-defined]
    use_llm_allowed = llm is not None and synthesis != "deterministic"
    rules: list[DistilledItem] = []
    llm_used = False
    seen: set[str] = set()
    for m in active_memories(memory, scope):
        if m.kind != "pitfall":
            continue
        dont = m.summary or m.text
        key = dont.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        do_instead: str = str((m.metadata or {}).get("do_instead", "") or "")
        if not do_instead and use_llm_allowed:
            do_instead = llm(
                f"The rule is: {m.text}. Name the single in-family replacement "
                f"to use instead. Reply with only the short replacement."
            ).strip()
            llm_used = True
        if do_instead and not _in_family(dont, do_instead):
            do_instead = ""  # in-family remediation only
        domain: str = str((m.metadata or {}).get("domain", "prose") or "prose")
        rules.append(Rule(
            summary=dont,
            dont=dont,
            do_instead=do_instead,
            domain=domain,
            confidence=m.confidence,
            source_refs=list(m.source_refs),
        ))
    return DistilledView(
        mode="rules",
        items=rules,
        used_llm=llm_used,
        stats={"n": float(len(rules))},
    )
