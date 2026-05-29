"""Deterministic extractive consolidator for chunkshop's ConsolidationChunker.

Contract (chunkshop CallableConsolidator):
    consolidate(text, **kwargs) -> {"summary": str, "facts": [{...}]}

Goal: actually compress. The previous extractive bake-off run kept ~16k
tokens; this one targets ~500-1000 tokens of total output regardless of
input size. Picks short, content-bearing sentences as facts; truncates a
sentence-window summary to a word cap.
"""
from __future__ import annotations

import re
from typing import Any

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")


def _sentences(text: str) -> list[str]:
    raw = _SENT_SPLIT.split(text or "")
    return [s.strip() for s in raw if s.strip()]


def consolidate(
    text: str,
    *,
    summary_words: int = 120,
    max_facts: int = 12,
    fact_min_chars: int = 30,
    fact_max_chars: int = 180,
    **_: Any,
) -> dict[str, Any]:
    sents = _sentences(text)
    summary = " ".join(text.split()[:summary_words])
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Score sentences by midrange-length preference: not too short (no info),
    # not too long (likely run-on). Keeps the most "factoid"-shaped.
    candidates = sorted(
        ((abs(80 - len(s)), s) for s in sents if fact_min_chars <= len(s) <= 400),
        key=lambda t: t[0],
    )
    for _score, s in candidates:
        key = s[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        span = s[:fact_max_chars]
        toks = re.findall(r"[A-Za-z0-9'-]+", s)
        subj = toks[0] if toks else "?"
        pred = toks[1] if len(toks) > 1 else "?"
        obj = " ".join(toks[2:5]) if len(toks) > 2 else "?"
        facts.append({
            "subject": subj,
            "predicate": pred,
            "object": obj,
            "support_span": span,
            "confidence": 0.5,
        })
        if len(facts) >= max_facts:
            break
    return {"summary": summary, "facts": facts}
