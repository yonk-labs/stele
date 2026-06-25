"""recall.shortcut — the 3-tier fall-through cascade (outcome -> context -> procedure -> work).

Routes an agent intent + current env through three short-circuit tiers, ordered most-reliable-
first, and returns the first valid hit (or ``tier="work"`` on a miss). The semantic matcher is
``Stele.memory.search_with_score`` (kind-filtered, scored); the tiers differ only in their
validity gate:

  outcome    canary fingerprint + TTL   (most reliable; routed by intent, gated best-first)
  context    source-hash + TTL freshness
  procedure  advisory (no hard gate; the agent re-runs the steps)

This module consumes the Memory facade only (no storage internals, no LLM), so recall stays
oracle-free. Each tier overfetches top-N and applies its gate in score order, returning the best
candidate that passes; a high-score-but-stale candidate never masks a fresh lower-score one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from stele.core import reuse as _reuse

if TYPE_CHECKING:
    from stele.core.memory import Memory
    from stele.core.memory_record import MemoryRecord, MemoryScope


@dataclass(frozen=True)
class ShortcutResult:
    """The cascade verdict: which tier (if any) short-circuited the work, the reusable payload,
    the record behind it, a reason, and routing diagnostics for trust/debugging."""

    tier: str  # "outcome" | "context" | "procedure" | "work"
    hit: bool  # False iff tier == "work"
    payload: str | None
    record: MemoryRecord | None
    reason: str
    diagnostics: dict[str, object] = field(default_factory=dict)


def _floor(floors: dict[str, float] | None, kind: str) -> float:
    return floors.get(kind, 0.0) if floors else 0.0


def _record_stale(
    record: MemoryRecord, source: str | None, now: datetime
) -> tuple[bool, bool]:
    """(is_stale, verified) for a context record under the source-hash + TTL gate. ``verified``
    is True when both a stored hash and a current source were available to compare."""
    meta = record.metadata
    stored = meta.get(_reuse.META_SOURCE_HASH)
    stored_hash = stored if isinstance(stored, str) else None
    ttl_raw = meta.get(_reuse.META_TTL)
    ttl = (
        ttl_raw
        if isinstance(ttl_raw, (int, float)) and not isinstance(ttl_raw, bool)
        else None
    )
    stale = _reuse.is_stale(stored_hash, source, record.created_at, ttl, now)
    return stale, (stored_hash is not None and source is not None)


def _context_tier(
    memory: Memory,
    intent: str,
    key: str | None,
    scope: MemoryScope,
    source: str | None,
    floors: dict[str, float] | None,
    top_n: int,
    now: datetime,
    diag: dict[str, object],
) -> ShortcutResult | None:
    # HYBRID exact-key leg: the context recorded for this exact source_ref (the file path).
    # Precise, no false positives, and still freshness-gated so a just-edited file is NOT reused
    # (the read-edit-reread loop, which is 97% of in-session re-reads). Tried before semantic.
    if key is not None:
        exact = [r for r in memory.by_source_ref(scope, key) if r.kind == "observation"]
        if exact:
            rec = max(exact, key=lambda r: r.created_at)
            stale, verified = _record_stale(rec, source, now)
            if not stale:
                diag["context_leg"] = "exact"
                reason = "exact-fresh" if verified else "exact-fresh-unverified"
                return ShortcutResult("context", True, rec.text, rec, reason, diag)
    # semantic leg: intent similarity over observations, gated the same way.
    floor = _floor(floors, "observation")
    hits = [
        h
        for h in memory.search_with_score(
            intent, scope, limit=top_n, kind_filter="observation"
        )
        if h.score >= floor
    ]
    diag["context_candidates"] = [(h.record.id, round(h.score, 3)) for h in hits]
    for h in hits:
        stale, verified = _record_stale(h.record, source, now)
        if stale:
            continue
        diag.setdefault("context_leg", "semantic")
        reason = "fresh" if verified else "fresh_unverified_source"
        return ShortcutResult("context", True, h.record.text, h.record, reason, diag)
    return None


def _procedure_tier(
    memory: Memory,
    intent: str,
    scope: MemoryScope,
    env: dict[str, str],
    floors: dict[str, float] | None,
    top_n: int,
    diag: dict[str, object],
) -> ShortcutResult | None:
    floor = _floor(floors, "procedure")
    hits = [
        h
        for h in memory.search_with_score(
            intent, scope, limit=top_n, kind_filter="procedure"
        )
        if h.score >= floor
    ]
    diag["procedure_candidates"] = [(h.record.id, round(h.score, 3)) for h in hits]
    if not hits:
        return None
    best = hits[0]  # advisory: best match, no hard gate (the agent re-runs the steps)
    rec_env = best.record.metadata.get(_reuse.META_ENV)
    drift = isinstance(rec_env, dict) and any(
        str(env.get(k)) != str(v) for k, v in rec_env.items()
    )
    reason = "advisory_env_drift" if drift else "advisory"
    return ShortcutResult("procedure", True, best.record.text, best.record, reason, diag)


def run_shortcut(
    memory: Memory,
    *,
    intent: str,
    env: dict[str, str],
    scope: MemoryScope,
    key: str | None = None,
    source: str | None = None,
    floors: dict[str, float] | None = None,
    top_n: int = 5,
    now: datetime | None = None,
) -> ShortcutResult:
    """Run the cascade and return the first valid hit, else ``tier="work"``. ``key`` is an exact
    identifier (e.g. the file's ``source_ref``) tried before semantic routing in the context
    tier (hybrid: exact-key first, semantic fallback)."""
    when = now if now is not None else datetime.now(UTC)
    diag: dict[str, object] = {"intent": intent}

    out = memory.reuse_outcome(scope, env, now=now, intent=intent)
    diag["outcome_reason"] = out.reason
    if out.reuse and out.record is not None:
        return ShortcutResult("outcome", True, out.record.text, out.record, out.reason, diag)

    ctx = _context_tier(memory, intent, key, scope, source, floors, top_n, when, diag)
    if ctx is not None:
        return ctx

    proc = _procedure_tier(memory, intent, scope, env, floors, top_n, diag)
    if proc is not None:
        return proc

    return ShortcutResult("work", False, None, None, "no-reuse", diag)
