"""Pure deterministic extraction core.

This module is PURE — no clock, no filesystem, no DB, no backend. The
scrubber is a pure-object dependency (RegexPIIScrubber is in-memory regex);
its presence here does not violate purity.
"""

from __future__ import annotations

import re
from typing import Protocol

from stele.core.artifact import ScrubResult
from stele.extraction.classifier import classify_kind
from stele.extraction.models import LedeSource, MemoryCandidate

# Behavioral / decision kinds the rule-aware pass surfaces. lede's
# importance-ranked passes (key_facts/summary/stats) drop short rule sentences
# ("NEVER use gpt-4o"), so distill_rules/skills/best_practices got nothing from
# raw text. This pass scans sentences for these kinds so they become candidates.
_RULE_CLASS_KINDS = frozenset(
    {"pitfall", "workaround", "instruction", "preference", "decision", "commitment"}
)


class _Scrubber(Protocol):
    def scrub(self, text: str, *, context: dict[str, object] | None = None) -> ScrubResult: ...


def extract_candidates(
    *,
    text: str,
    source_refs: list[str],
    scrubber: _Scrubber,
    overlay_enabled: bool,
    max_candidates: int,
    extract_rules: bool = True,
) -> list[MemoryCandidate]:
    """Surface candidates from text, classify each, return them.

    Two passes: a rule-aware sentence/line scan (``_rule_pass``) that surfaces
    behavioral rule language lede would drop, then lede's importance-ranked
    distillation (``_lede_pass``). Rule-pass items come first so the
    ``max_candidates`` cap never crowds out a rule. ``extract_rules=False``
    restores the lede-only behavior.

    source_refs is accepted but not embedded in the candidate (the orchestrator
    composes the eventual MemoryRecord's source_refs from its input). We accept
    it here as a contract reminder: extraction is always source-traced.
    """
    del source_refs  # contract signal only

    if not text or not text.strip():
        return []

    rule_items = _rule_pass(text) if extract_rules else []
    raw_items = _merge_dedup(rule_items, _lede_pass(text))
    candidates: list[MemoryCandidate] = []
    for item_text, lede_source in raw_items:
        if len(candidates) >= max_candidates:
            break
        scrubbed = scrubber.scrub(item_text)
        classification = classify_kind(
            text=scrubbed.text,
            lede_source=lede_source,
            overlay_enabled=overlay_enabled,
        )
        candidates.append(
            MemoryCandidate(
                text=scrubbed.text,
                kind=classification.kind,
                confidence=classification.confidence,
                lede_source=lede_source,
                classifier_path=classification.classifier_path,
                pattern_match=classification.pattern_match,
            )
        )
    return candidates


def _merge_dedup(
    first: list[tuple[str, LedeSource]], second: list[tuple[str, LedeSource]]
) -> list[tuple[str, LedeSource]]:
    """Concatenate, keeping the first occurrence of each normalized text. Rule
    items are passed first so they are never displaced by lede duplicates."""
    seen: set[str] = set()
    out: list[tuple[str, LedeSource]] = []
    for item_text, source in [*first, *second]:
        key = item_text.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((item_text, source))
    return out


def _rule_pass(text: str) -> list[tuple[str, LedeSource]]:
    """Surface line/sentence units that match a behavioral rule pattern.

    Line-oriented on purpose: CLAUDE.md-style rules are markdown bullets, which
    lede's importance ranking drops. We strip markdown markers, split long lines
    on sentence enders, and keep only units whose first pattern match is a
    rule-class kind. Deterministic, no lede dependency (lede is optional). The
    items are emitted as ``key_fact`` so the (always-on) classifier overlay,
    which carries the higher rule-kind weight, decides the final kind."""
    from stele.extraction.patterns import match_first_kind

    out: list[tuple[str, LedeSource]] = []
    for line in re.split(r"\n+", text):
        cleaned = re.sub(r"^[\s\-*#>`]+", "", line).strip().strip("*`").strip()
        if not cleaned:
            continue
        for unit in re.split(r"(?<=[.!?])\s+", cleaned):
            unit = unit.strip()
            if not unit or len(unit) > 400:
                continue
            pack = match_first_kind(unit)
            if pack is not None and pack.kind in _RULE_CLASS_KINDS:
                out.append((unit, "key_fact"))
    return out


def _lede_pass(text: str) -> list[tuple[str, LedeSource]]:
    """Run the lede passes, returning (text, source) pairs."""
    try:
        from lede import summarize
        from lede.extract import key_facts, metadata, phrases, stats
        from lede.sentences import split_sentences
    except ModuleNotFoundError:
        return []

    items: list[tuple[str, LedeSource]] = []
    stripped = text.strip()

    # 1. summary: single document-level summary, suppressed when identical
    summary_result = summarize(text, max_length=1200)
    summary_text = str(getattr(summary_result, "summary", summary_result)).strip()
    if summary_text and summary_text != stripped:
        items.append((summary_text, "summary"))

    # 2. key_facts: list of sentence-level facts; fall back to split_sentences
    fact_results = key_facts(text) or ()
    if fact_results:
        for fact in fact_results:
            fact_text = str(fact).strip()
            if fact_text:
                items.append((fact_text, "key_fact"))
    else:
        for sentence in split_sentences(text) or ():
            sentence_text = str(sentence).strip()
            if sentence_text:
                items.append((sentence_text, "key_fact"))

    # 3. stats: list of Stat objects
    for stat in stats(text) or ():
        stat_text = str(stat).strip()
        if stat_text:
            items.append((stat_text, "stat"))

    # 4. metadata: doc-level metadata
    meta = metadata(text)
    if meta is not None:
        meta_text = str(meta).strip()
        if meta_text and meta_text != "Metadata(dates=(), amounts=(), urls=(), entities=())":
            items.append((meta_text, "metadata"))

    # 5. phrases: PhraseFact items
    for phrase in phrases(text) or ():
        phrase_text = str(phrase).strip()
        if phrase_text:
            items.append((phrase_text, "phrase"))

    return items
