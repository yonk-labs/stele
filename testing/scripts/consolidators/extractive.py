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

import datetime as _dt
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


# "[Session date: 1:56 pm on 8 May, 2023]" -> capture the "8 May, 2023" part.
_SESSION_DATE = re.compile(r"session date:.*?\bon\s+(.+)$", re.IGNORECASE)
_WEEKDAYS = {d: i for i, d in enumerate(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
_REL_WEEKDAY = re.compile(
    r"\b(?:last|this|next)?\s*"
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE)
_N_AGO = re.compile(r"\b(\d+)\s+(day|week|month|year)s?\s+ago\b", re.IGNORECASE)


def _parse_session_date(raw: str) -> _dt.date | None:
    """'1:56 pm on 8 May, 2023' / '8 May, 2023' -> date(2023,5,8)."""
    m = _SESSION_DATE.search(raw)
    tail = (m.group(1) if m else raw).strip().rstrip(".]").strip()
    for fmt in ("%d %B, %Y", "%d %B %Y"):
        try:
            return _dt.datetime.strptime(tail, fmt).date()
        except ValueError:
            continue
    return None


def _resolve(sentence: str, anchor: _dt.date) -> str | None:
    """Compute an absolute date for the first relative expression we recognise,
    relative to `anchor`. Returns an ISO-ish 'D Month YYYY' string or None.
    stdlib only (no dateutil): weekdays, N-units-ago, yesterday, last week/etc."""
    low = sentence.lower()

    def fmt(d: _dt.date) -> str:
        # ISO so stele can parse it into a filterable fact_date metadata field
        # (and ISO is unambiguous for the answerer too).
        return d.isoformat() if hasattr(d, "isoformat") else str(d)

    if "yesterday" in low:
        return fmt(anchor - _dt.timedelta(days=1))
    m = _N_AGO.search(low)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        return fmt(anchor - _dt.timedelta(days=days))
    if "last week" in low or "a week ago" in low:
        return fmt(anchor - _dt.timedelta(days=7))
    if "last month" in low or "a month ago" in low:
        return fmt(anchor - _dt.timedelta(days=30))
    if "last year" in low or "a year ago" in low:
        return f"{anchor.year - 1}"
    m = _REL_WEEKDAY.search(low)
    if m:
        target = _WEEKDAYS[m.group(1).lower()]
        delta = (anchor.weekday() - target) % 7
        delta = delta or 7  # "last friday" = the most recent prior friday
        return fmt(anchor - _dt.timedelta(days=delta))
    return None


def _split_turns(text: str) -> list[tuple[str, str, _dt.date | None]]:
    """Return [(speaker, sentence, session_date), ...].

    A turn is "[Speaker] free text". "[Session date: ...]" markers (injected
    by the LoCoMo scenario builder) update the current session-date anchor so
    each fact can carry the absolute date its relative expression needs.
    """
    out: list[tuple[str, str, _dt.date | None]] = []
    pos = 0
    speaker = ""
    anchor: _dt.date | None = None
    for m in _TURN.finditer(text):
        chunk = text[pos:m.start()].strip()
        if chunk:
            for s in _SENT.split(chunk):
                s = s.strip()
                if s:
                    out.append((speaker, s, anchor))
        label = m.group(1).strip()
        if label.lower().startswith("session date"):
            anchor = _parse_session_date(label) or anchor
        else:
            speaker = label
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        for s in _SENT.split(tail):
            s = s.strip()
            if s:
                out.append((speaker, s, anchor))
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
    date_mode: str = "none",  # none | anchor | resolve | both
    **_: Any,
) -> dict[str, Any]:
    turns = _split_turns(text)
    # Rank sentences by answer-bearing score, then by appearance order so ties
    # are stable and earlier context wins.
    ranked = sorted(
        (
            (-_score(s), idx, spk, s, anchor)
            for idx, (spk, s, anchor) in enumerate(turns)
            if fact_min_chars <= len(s) <= 400
        ),
        key=lambda t: (t[0], t[1]),
    )

    facts: list[dict[str, Any]] = []
    summary_sentences: list[tuple[int, str]] = []  # (orig idx, sentence)
    summary_used = 0
    seen: set[str] = set()
    for neg_score, idx, spk, s, anchor in ranked:
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
        # Keep each fact's session date with its relative-date expression so a
        # temporal question is answerable from the span alone (the anchor and
        # the "last Friday" no longer get separated by chunking/retrieval).
        if anchor is not None and date_mode in ("anchor", "both"):
            attributed = f"(around {anchor.strftime('%-d %B %Y')}) {attributed}"
        if anchor is not None and date_mode in ("resolve", "both"):
            resolved = _resolve(s, anchor)
            if resolved:
                attributed = f"{attributed} [date: {resolved}]"
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
