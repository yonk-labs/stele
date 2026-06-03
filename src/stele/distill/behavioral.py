from __future__ import annotations

import json
import re
from collections.abc import Sequence

from stele.core.memory_record import MemoryRecord, MemoryScope
from stele.distill.base import LLMSynthesizer, active_memories
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


def _llm_and_allowed(d: object) -> tuple[LLMSynthesizer | None, bool]:
    llm = d._llm  # type: ignore[attr-defined]
    synthesis = getattr(d._config, "synthesis", "auto")  # type: ignore[attr-defined]
    return llm, (llm is not None and synthesis != "deterministic")


def _extract_json_array(raw: str) -> list[dict[str, object]]:
    """Pull the first JSON array out of an LLM reply (tolerates ```json fences
    and surrounding prose). Raises on no/invalid array; callers fall back."""
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON array in LLM reply")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise ValueError("LLM reply was not a JSON array")
    return [obj for obj in parsed if isinstance(obj, dict)]


def _refine(
    llm: LLMSynthesizer, mode: str, items: Sequence[DistilledItem]
) -> list[DistilledItem]:
    """LLM precision pass: the deterministic scan is high-recall and surfaces
    doc prose; the LLM keeps only genuine rule/skill/practice items, normalizes
    each to one line, and (for rules) supplies the in-family do_instead. Source
    refs are carried over from the matched candidate by index (no fabrication).
    On any parse failure the deterministic candidates are returned unchanged."""
    if not items:
        return list(items)
    listing = "\n".join(f"{i}. {it.summary}" for i, it in enumerate(items))
    if mode == "rules":
        instr = (
            "Keep ONLY genuine 'never do X' rules an agent must obey. Drop "
            "documentation prose, descriptions, and anything that is not a real "
            "prohibition. For each kept item give its index i, a one-line 'dont', "
            "and 'do_instead' = the in-family replacement to use (same tool/model "
            "vendor or family; empty string if the source implies no replacement)."
        )
        schema = '[{"i": <int>, "dont": "<text>", "do_instead": "<text or empty>"}]'
    elif mode == "skills":
        instr = (
            "Keep ONLY genuine 'always do X' portable habits an agent should apply. "
            "Drop architecture notes, descriptions, and prose that merely contains "
            "the words always/never. For each kept item give index i and 'text'."
        )
        schema = '[{"i": <int>, "text": "<one-line habit>"}]'
    else:  # best_practices
        instr = (
            "Keep ONLY genuine suggested best practices (earned advice worth "
            "surfacing). Drop documentation prose. For each give index i and 'text'."
        )
        schema = '[{"i": <int>, "text": "<one-line practice>"}]'
    prompt = (
        f"Candidate lines extracted from project docs:\n{listing}\n\n{instr}\n"
        f"Reply with ONLY JSON matching {schema}. No prose, no code fences."
    )
    try:
        parsed = _extract_json_array(llm(prompt))
    except Exception:  # noqa: BLE001 -- any LLM/parse failure falls back to deterministic
        return list(items)
    refined: list[DistilledItem] = []
    for obj in parsed:
        idx = obj.get("i")
        if not isinstance(idx, int) or not (0 <= idx < len(items)):
            continue
        src = items[idx]
        if mode == "rules":
            dont = str(obj.get("dont") or getattr(src, "dont", "") or src.summary).strip()
            do_instead = str(obj.get("do_instead") or "").strip()
            if do_instead and not _in_family(dont, do_instead):
                do_instead = ""  # in-family remediation only
            refined.append(Rule(
                summary=dont, dont=dont, do_instead=do_instead,
                domain=getattr(src, "domain", "prose"),
                confidence=src.confidence, source_refs=list(src.source_refs),
            ))
        else:
            text = str(obj.get("text") or src.summary).strip()
            refined.append(DistilledItem(
                summary=text, detail=src.detail,
                confidence=src.confidence, source_refs=list(src.source_refs),
            ))
    return refined


def _dedup(records: Sequence[MemoryRecord]) -> list[MemoryRecord]:
    out: list[MemoryRecord] = []
    seen: set[str] = set()
    for m in records:
        key = (m.summary or m.text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


def _plain_view(records: Sequence[MemoryRecord], mode: str, d: object) -> DistilledView:
    items: list[DistilledItem] = [
        DistilledItem(summary=m.summary or m.text, detail=m.detail or "",
                      confidence=m.confidence, source_refs=list(m.source_refs))
        for m in _dedup(records)
    ]
    llm, allowed = _llm_and_allowed(d)
    if allowed and llm is not None:
        items = _refine(llm, mode, items)
    return DistilledView(mode=mode, items=items, used_llm=allowed,
                         stats={"n": float(len(items))})


async def distill_skills(d: object, scope: MemoryScope) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    recs = [m for m in active_memories(memory, scope) if m.kind == "instruction"]
    return _plain_view(recs, "skills", d)


async def distill_best_practices(d: object, scope: MemoryScope) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    recs = [m for m in active_memories(memory, scope) if m.kind == "preference"]
    return _plain_view(recs, "best_practices", d)


async def distill_rules(d: object, scope: MemoryScope) -> DistilledView:
    memory = d._memory  # type: ignore[attr-defined]
    llm, allowed = _llm_and_allowed(d)
    # Deterministic candidates: pitfalls, do_instead from metadata or a same-key
    # workaround. The LLM refine pass (when present) filters noise + supplies
    # do_instead where the source did not state one.
    candidates: list[DistilledItem] = []
    seen: set[str] = set()
    for m in active_memories(memory, scope):
        if m.kind != "pitfall":
            continue
        dont = m.summary or m.text
        key = dont.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        do_instead = str((m.metadata or {}).get("do_instead", "") or "")
        if do_instead and not _in_family(dont, do_instead):
            do_instead = ""
        candidates.append(Rule(
            summary=dont, dont=dont, do_instead=do_instead,
            domain=str((m.metadata or {}).get("domain", "prose") or "prose"),
            confidence=m.confidence, source_refs=list(m.source_refs),
        ))
    items: list[DistilledItem] = candidates
    if allowed and llm is not None:
        items = _refine(llm, "rules", candidates)
    return DistilledView(mode="rules", items=items, used_llm=allowed,
                         stats={"n": float(len(items))})
