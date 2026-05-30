"""Enriching consolidator — keep the text, add the structure (no compression).

The consolidation chunker's value was never the distillation (which loses to
raw_fetch on every benchmark) — it was the metadata attached along the way
(speaker->subject coref, resolved dates, entity tags). This keeps all of that
and drops the lossy part.

Granularity matters: the first cut emitted one fact PER SENTENCE, producing
hundreds of tiny chunks so top-k retrieval starved the model (~312 tokens, 70%
abstain). This emits one fact PER TURN — coherent, retrievable units that keep
the speaker tag (coref anchor) and a resolved [date: ISO] in the span.

Drop-in: consolidator_module="benchmarks.external.consolidators.enriching".
"""
from __future__ import annotations

import re
from typing import Any

from benchmarks.external.consolidators.extractive import _parse_session_date, _resolve

_SESSION_LINE = re.compile(r"^\[session date:", re.IGNORECASE)
_TURN_LINE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


def consolidate(
    text: str,
    *,
    max_facts: int = 1000,
    date_mode: str = "both",
    granularity: str = "turn",  # turn | sentence
    **_: Any,
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    seen_dates: list[str] = []
    seen_units: set[str] = set()  # dedup: same turn/sentence text -> one fact
    anchor = None
    # _dialog() emits one turn per line: "[Session date: ...]" or "[Speaker] text".
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if _SESSION_LINE.match(line):
            anchor = _parse_session_date(line) or anchor
            if anchor and anchor.isoformat() not in seen_dates:
                seen_dates.append(anchor.isoformat())
            continue
        m = _TURN_LINE.match(line)
        if not m:
            continue
        spk, body = m.group(1).strip(), m.group(2).strip()
        if not body:
            continue
        units = [body] if granularity == "turn" else re.split(r"(?<=[.!?])\s+", body)
        for unit in units:
            unit = unit.strip()
            if not unit or unit.lower() in seen_units:
                continue
            seen_units.add(unit.lower())
            span = f"[{spk}] {unit}"
            if anchor is not None and date_mode in ("anchor", "both"):
                span = f"(around {anchor.isoformat()}) {span}"
            if anchor is not None and date_mode in ("resolve", "both"):
                resolved = _resolve(unit, anchor)
                if resolved:
                    span = f"{span} [date: {resolved}]"
            toks = span.split()
            facts.append({
                "subject": spk or "?",          # speaker = coref-resolved entity
                "predicate": "said",
                "object": " ".join(toks[1:5]) if len(toks) > 1 else "?",
                "support_span": span,           # VERBATIM turn text — not distilled
                "confidence": 1.0,
            })
            if len(facts) >= max_facts:
                break
        if len(facts) >= max_facts:
            break
    summary = "Session dates: " + ", ".join(seen_dates) if seen_dates else ""
    return {"summary": summary, "facts": facts}
