"""Deterministic extractive consolidator for chunkshop's ConsolidationChunker.

Contract (chunkshop CallableConsolidator):
    consolidate(text, **kwargs) -> {"summary": str, "facts": [{...}]}

No LLM, no API cost. It cannot *understand* (it won't resolve "last Friday"
to an absolute date — only the LLM consolidator does that), but it selects
and ranks the answer-bearing content instead of emitting length-picked
fragments. Three rules drive quality:

1. Segment into speaker-attributed sentences (keep "[Caroline] ..." so the
   span carries the *who*), never split mid-turn into fragments.
2. Score each sentence by answer-bearing density — dates, numbers, and named
   entities are exactly what LoCoMo questions ask about — not by length.
3. Keep whole sentences as spans; if a span must be capped, cap at a word
   boundary so we never emit "s a gorgeous song".

The summary is the top-scored sentences concatenated to a word budget (dense
and fact-bearing), NOT the first N words of the dialogue (pleasantries).
"""
from __future__ import annotations

import re
from typing import Any

# Speaker turn marker used by the LoCoMo scenario builder: "[Caroline] ...".
_TURN = re.compile(r"\[([^\]]+)\]\s*")
# Sentence boundary: period/!/? + space, but not inside common abbreviations.
_SENT = re.compile(r"(?<=[.!?])\s+")

# Answer-bearing signals (LoCoMo is heavily temporal + named-entity).
_DATE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    r"|\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b"
    r"|\b\d{4}\b|\b\d{1,2}(?:st|nd|rd|th)\b"
    r"|\b(?:yesterday|today|tomorrow|last|next|ago|week|weekend|month|year)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\b\d+\b")
# Proper nouns: capitalized words that are NOT at sentence start.
_PROPER = re.compile(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-z]{2,}\b")


def _split_turns(text: str) -> list[tuple[str, str]]:
    """Return [(speaker, sentence), ...] preserving speaker attribution.

    A turn is "[Speaker] free text"; we split the free text into sentences
    and attach the speaker to each. Text before the first marker (or input
    without markers) is attributed to speaker "".
    """
    out: list[tuple[str, str]] = []
    pos = 0
    speaker = ""
    for m in _TURN.finditer(text):
        chunk = text[pos:m.start()].strip()
        if chunk:
            for s in _SENT.split(chunk):
                s = s.strip()
                if s:
                    out.append((speaker, s))
        speaker = m.group(1).strip()
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        for s in _SENT.split(tail):
            s = s.strip()
            if s:
                out.append((speaker, s))
    return out


def _score(sentence: str) -> int:
    """Answer-bearing density: dates dominate, then numbers, then entities."""
    score = 0
    score += 4 * len(_DATE.findall(sentence))
    score += 2 * len(_NUMBER.findall(sentence))
    score += 1 * len(_PROPER.findall(sentence))
    return score


def _cap_at_word(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut).rstrip()


def consolidate(
    text: str,
    *,
    summary_words: int = 120,
    max_facts: int = 12,
    fact_min_chars: int = 20,
    fact_max_chars: int = 200,
    **_: Any,
) -> dict[str, Any]:
    turns = _split_turns(text)
    # Rank sentences by answer-bearing score, then by appearance order so ties
    # are stable and earlier context wins.
    ranked = sorted(
        (
            (-_score(s), idx, spk, s)
            for idx, (spk, s) in enumerate(turns)
            if fact_min_chars <= len(s) <= 400
        ),
        key=lambda t: (t[0], t[1]),
    )

    facts: list[dict[str, Any]] = []
    summary_sentences: list[tuple[int, str]] = []  # (orig idx, sentence)
    summary_used = 0
    seen: set[str] = set()
    for neg_score, idx, spk, s in ranked:
        key = s[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        # A sentence with zero answer-bearing signal is not worth a fact slot.
        if neg_score == 0 and len(facts) >= max_facts // 2:
            continue
        # Whole-sentence span (word-boundary cap only for very long sentences).
        span = _cap_at_word(s, fact_max_chars)
        attributed = f"[{spk}] {span}" if spk else span
        toks = re.findall(r"[A-Za-z0-9'-]+", s)
        facts.append({
            "subject": spk or (toks[0] if toks else "?"),
            "predicate": toks[1] if len(toks) > 1 else "said",
            "object": " ".join(toks[2:6]) if len(toks) > 2 else "?",
            "support_span": attributed,
            "confidence": 0.5,
        })
        # Collect WHOLE high-signal sentences for the summary until adding the
        # next one would blow the word budget — never slice mid-sentence.
        wc = len(s.split())
        if summary_used + wc <= summary_words:
            summary_sentences.append((idx, s))
            summary_used += wc
        if len(facts) >= max_facts:
            break

    # Restore original order so the summary reads as coherent prose.
    summary = " ".join(s for _idx, s in sorted(summary_sentences)).strip()
    return {"summary": summary, "facts": facts}
