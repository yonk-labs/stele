"""Pure planner for evolving-fact consolidation: assign session memories to
(subject, aspect) slots and order each slot chronologically. No DB, no LLM."""
from __future__ import annotations

from dataclasses import dataclass

from stele.extraction.identity import canonical_aspect
from stele.extraction.session import SessionMemory


@dataclass(frozen=True)
class SlotKey:
    scope_key: str
    subject_type: str
    subject_id: str
    aspect: str


@dataclass(frozen=True)
class Slotted:
    order: tuple[int, int]          # (window_index, emission_index): chronological
    memory: SessionMemory
    slot: SlotKey | None            # None => commit standalone (today's behavior)


def slot_for(
    mem: SessionMemory,
    *,
    scope_key: str,
    subject_id: str,
    subject_type: str,
) -> SlotKey | None:
    if mem.kind != "fact":
        return None
    asp = canonical_aspect(mem.aspect)
    if not subject_id or not asp:
        return None
    return SlotKey(scope_key, subject_type, subject_id, asp)


def plan_chains(
    items: list[Slotted],
) -> tuple[dict[SlotKey, list[Slotted]], list[Slotted]]:
    """(chains, standalone). chains[slot] = states in chronological order;
    standalone = memories with no slot, committed unchanged."""
    chains: dict[SlotKey, list[Slotted]] = {}
    standalone: list[Slotted] = []
    for it in sorted(items, key=lambda x: x.order):
        if it.slot is None:
            standalone.append(it)
        else:
            chains.setdefault(it.slot, []).append(it)
    return chains, standalone


def overlap_warnings(chains: dict[SlotKey, list[Slotted]]) -> list[tuple[str, list[str]]]:
    """Aspect-drift detector (log-only): one subject_id carrying >1 aspect slot."""
    by_subject: dict[str, list[str]] = {}
    for slot in chains:
        by_subject.setdefault(slot.subject_id, []).append(slot.aspect)
    return [(s, asp) for s, asp in by_subject.items() if len(asp) > 1]


def is_newer(this_recency: float | None, other_recency: float | None) -> bool:
    """Strictly-newer compare on recency floats. Unknown `this_recency` never
    wins on mtime (caller falls back to store timestamp)."""
    if this_recency is None or other_recency is None:
        return False
    return this_recency > other_recency
