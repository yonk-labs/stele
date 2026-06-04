"""Episode distillation: one "what happened" summary per past session.

The seventh distill view. An *episode* is one session: a stored session
artifact (``metadata.source == "session-ingest"``) plus the memories
back-linked to it via ``source_refs``. This view groups the scope's ACTIVE
memories by their session artifact and synthesizes ONE :class:`EpisodeItem` per
session.

Like the other six views, this is COMPUTED ON READ. It writes no new store
rows: it reads already-stored memories + their session artifacts and composes a
summary in memory. Nothing is persisted.

Deterministic by default: the summary is composed from the session's decisions,
pitfalls, and a count. When an LLM is injected (``stele._distill_llm``) and
synthesis is allowed, it tightens the "what happened" line, with a deterministic
fallback on any failure or empty output. This module imports no LLM client at
module top (enforced by ``tests/unit/distill/test_architecture.py``); the LLM is
injected through the facade.
"""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord
from stele.core.memory_record import MemoryRecord, MemoryScope
from stele.distill.base import LLMSynthesizer, active_memories
from stele.distill.models import DistilledItem, DistilledView, EpisodeItem

# Session artifacts carry this metadata source; mirrors recall/episodic.py's
# SESSION_SOURCE without importing recall (distill stays self-contained).
SESSION_SOURCE = "session-ingest"


def _llm_and_allowed(d: object) -> tuple[LLMSynthesizer | None, bool]:
    llm = d._llm  # type: ignore[attr-defined]
    synthesis = getattr(d._config, "synthesis", "auto")  # type: ignore[attr-defined]
    return llm, (llm is not None and synthesis != "deterministic")


def _episode_when(record: ArtifactRecord) -> datetime:
    """The episode's temporal anchor: ``metadata.session_mtime`` if present and
    parseable, else the artifact ``created_at``."""
    raw = record.metadata.get("session_mtime")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return record.created_at
    return record.created_at


def _as_naive_utc(value: datetime) -> datetime:
    """Normalize to tz-naive UTC so window comparisons are total (parse_temporal
    returns tz-naive bounds; artifact times are tz-aware UTC)."""
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _session_records(stele: object, namespace: str) -> dict[str, ArtifactRecord]:
    """All session-ingest artifacts in the namespace, keyed by reference. When
    no artifact carries the session tag, every artifact is treated as a possible
    episode (mirrors recall/episodic.py's fallback)."""
    page = stele.list(namespace=namespace, limit=10_000)  # type: ignore[attr-defined]
    records = list(page.items)
    tagged = {r.reference: r for r in records if r.metadata.get("source") == SESSION_SOURCE}
    return tagged or {r.reference: r for r in records}


def _line(m: MemoryRecord) -> str:
    return (m.summary or m.text).strip()


def _compose_summary(rec: ArtifactRecord, mems: list[MemoryRecord]) -> str:
    """Deterministic 'what happened' line: lead with the decisions, then the
    pitfalls, then the count. Falls back to the artifact summary when the
    session produced no kinded memories worth naming."""
    decisions = [_line(m) for m in mems if m.kind == "decision"]
    pitfalls = [_line(m) for m in mems if m.kind == "pitfall"]
    parts: list[str] = []
    if decisions:
        parts.append("decided " + "; ".join(decisions))
    if pitfalls:
        parts.append("hit " + "; ".join(pitfalls))
    head = ". ".join(parts) if parts else (rec.summary or "").strip()
    count = len(mems)
    tail = f"({count} memor{'y' if count == 1 else 'ies'})"
    return f"{head} {tail}".strip() if head else tail


def _refine_summary(llm: LLMSynthesizer, deterministic: str, mems: list[MemoryRecord]) -> str:
    """LLM tightening of the deterministic 'what happened' line. The model sees
    the session's memory lines and writes one tighter sentence. Any failure or
    empty/over-long reply falls back to the deterministic summary unchanged."""
    listing = "\n".join(f"- {_line(m)}" for m in mems)
    if not listing:
        return deterministic
    prompt = (
        "These are the memories produced in one work session:\n"
        f"{listing}\n\n"
        "Write ONE plain sentence describing what happened in this session. "
        "Reply with only the sentence, no prose, no quotes."
    )
    try:
        reply = llm(prompt).strip()
    except Exception:  # noqa: BLE001 -- any LLM failure falls back to deterministic
        return deterministic
    if not reply or len(reply) > 500:
        return deterministic
    return reply


def build_episodes(
    d: object,
    scope: MemoryScope,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[EpisodeItem], bool]:
    """Compute the scope's episodes once: group ACTIVE memories by their session
    artifact, window by ``since``/``until``, and synthesize one
    :class:`EpisodeItem` per session (deterministic, optional LLM refine).

    Returns ``(episodes, used_llm)`` UNSORTED. The shared core for the episodes,
    timeline, and spans views; each orders/clusters the result its own way so
    none of them re-derives the grouping."""
    memory = d._memory  # type: ignore[attr-defined]
    stele = d._stele  # type: ignore[attr-defined]
    llm, allowed = _llm_and_allowed(d)

    sessions = _session_records(stele, scope.namespace)

    # Group ACTIVE memories by the session artifact they cite. A memory may cite
    # several refs; it joins every session ref it carries.
    by_session: dict[str, list[MemoryRecord]] = {ref: [] for ref in sessions}
    for m in active_memories(memory, scope):
        for ref in m.source_refs:
            if ref in by_session:
                by_session[ref].append(m)

    since_n = _as_naive_utc(since) if since is not None else None
    until_n = _as_naive_utc(until) if until is not None else None

    episodes: list[EpisodeItem] = []
    for ref, rec in sessions.items():
        mems = by_session[ref]
        if not mems:
            continue  # a session that produced no memories is not an episode
        when = _episode_when(rec)
        wn = _as_naive_utc(when)
        if since_n is not None and wn < since_n:
            continue
        if until_n is not None and wn > until_n:
            continue
        summary = _compose_summary(rec, mems)
        if allowed and llm is not None:
            summary = _refine_summary(llm, summary, mems)
        merged_refs = list(dict.fromkeys([ref, *(r for m in mems for r in m.source_refs)]))
        episodes.append(
            EpisodeItem(
                summary=summary,
                detail=(rec.summary or "").strip(),
                when=when,
                session_id=rec.session_id,
                ref=ref,
                decisions=[_line(m) for m in mems if m.kind == "decision"],
                pitfalls=[_line(m) for m in mems if m.kind == "pitfall"],
                facts=[_line(m) for m in mems if m.kind == "fact"],
                confidence=1.0,
                source_refs=merged_refs,
            )
        )
    return episodes, allowed


async def distill_episodes(
    d: object,
    scope: MemoryScope,
    since: datetime | None = None,
    until: datetime | None = None,
) -> DistilledView:
    episodes, used_llm = build_episodes(d, scope, since, until)

    # Newest-first by the episode's temporal anchor.
    episodes.sort(
        key=lambda it: _as_naive_utc(it.when) if it.when else datetime.min,
        reverse=True,
    )
    # Widen to the base item type so the invariant DistilledView.items list
    # accepts it (every element is an EpisodeItem subclass).
    items: list[DistilledItem] = list(episodes)
    return DistilledView(
        mode="episodes",
        items=items,
        used_llm=used_llm,
        stats={"n": float(len(items))},
    )
