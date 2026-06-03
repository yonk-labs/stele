from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from stele.core.memory_record import MemoryRecord, MemoryScope

if TYPE_CHECKING:
    from stele.distill.models import DistilledItem


@runtime_checkable
class LLMSynthesizer(Protocol):
    """Optional, injected. The distill package imports no LLM client at module
    top (enforced by test_architecture). When None, distillation runs
    deterministically."""

    def __call__(self, prompt: str) -> str: ...


@runtime_checkable
class Embedder(Protocol):
    """Optional, injected (duck-typed; the storage embedder satisfies it). Used
    for semantic dedup. distill imports no embedder module (architecture-gated)."""

    def embed(self, text: str) -> list[float]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def semantic_dedup(items: list[DistilledItem], embedder: Embedder,
                   threshold: float = 0.82) -> list[DistilledItem]:
    """Collapse items whose summaries are SEMANTICALLY near-duplicates (cosine of
    their embeddings >= threshold), merging source_refs. Catches paraphrases that
    normalized-exact dedup misses ("edit a file without reading" vs "write to a
    file without reading" vs "edit design.md without reading"). Greedy: each item
    joins the first representative it is close to, else becomes a new one."""
    if len(items) < 2:
        return list(items)
    reps: list[tuple[list[float], int]] = []  # (vector, index into out)
    out: list[DistilledItem] = []
    for it in items:
        vec = embedder.embed(it.summary)
        match: int | None = None
        for rvec, idx in reps:
            if _cosine(vec, rvec) >= threshold:
                match = idx
                break
        if match is None:
            reps.append((vec, len(out)))
            out.append(it)
        else:
            kept = out[match]
            merged = list(dict.fromkeys([*kept.source_refs, *it.source_refs]))
            out[match] = kept.model_copy(update={"source_refs": merged})
    return out


def _norm(text: str) -> str:
    """Normalize for dedup: lowercase, collapse whitespace, drop punctuation."""
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", text.lower())).strip()


def dedup_distilled(items: list[DistilledItem]) -> list[DistilledItem]:
    """Collapse cross-session duplicates by normalized summary, merging their
    source_refs (recurrence across sessions = stronger evidence). The first
    occurrence's concrete type (Rule/DistilledItem) and fields are kept. Applied
    AFTER the LLM refine, which normalizes wording so the same rule phrased two
    different ways across sessions becomes one item carrying both refs."""
    by_key: dict[str, DistilledItem] = {}
    for it in items:
        key = _norm(it.summary)
        if not key:
            continue
        if key not in by_key:
            by_key[key] = it
        else:
            kept = by_key[key]
            merged = list(dict.fromkeys([*kept.source_refs, *it.source_refs]))
            by_key[key] = kept.model_copy(update={"source_refs": merged})
    return list(by_key.values())


def _recency(m: MemoryRecord) -> float:
    """Ordering key for 'which is current': the session's mtime if the distiller
    stamped it (true session recency), else the record's created_at."""
    md = m.metadata or {}
    raw = md.get("session_mtime")
    if isinstance(raw, int | float | str):
        try:
            return float(raw)
        except ValueError:
            pass
    return m.created_at.timestamp() if m.created_at else 0.0


def consolidate(memory: object, embedder: Embedder, scope: MemoryScope,
                threshold: float = 0.82) -> dict[str, int]:
    """Temporal supersession over the stored memories. Within each kind, cluster
    ACTIVE memories by embedding similarity and RETRACT all but the newest in
    each cluster (newest by session_mtime, else created_at), so the long-lived
    store reflects current truth instead of accumulating contradictions across
    periodic runs ("version 0.5" superseded by "version 0.6"). A maintenance
    pass: run it after a distill batch. Returns {clusters, retracted}."""
    from collections import defaultdict

    records: list[MemoryRecord] = memory.list(scope, ["active"], limit=10_000)  # type: ignore[attr-defined]
    by_kind: dict[str, list[MemoryRecord]] = defaultdict(list)
    for m in records:
        by_kind[m.kind].append(m)
    clusters = retracted = 0
    for group in by_kind.values():
        if len(group) < 2:
            continue
        vecs = [embedder.embed(m.summary or m.text) for m in group]
        used = [False] * len(group)
        for i in range(len(group)):
            if used[i]:
                continue
            members = [i]
            used[i] = True
            for j in range(i + 1, len(group)):
                if not used[j] and _cosine(vecs[i], vecs[j]) >= threshold:
                    members.append(j)
                    used[j] = True
            if len(members) < 2:
                continue
            clusters += 1
            members.sort(key=lambda k: _recency(group[k]), reverse=True)  # newest first
            newest = group[members[0]]
            for k in members[1:]:
                memory.retract(  # type: ignore[attr-defined]
                    group[k].id,
                    reason=f"consolidated: superseded by newer equivalent {newest.id}",
                )
                retracted += 1
    return {"clusters": clusters, "retracted": retracted}


def active_memories(memory: object, scope: MemoryScope, limit: int = 1000) -> list[MemoryRecord]:
    """All ACTIVE (newest-valid) memories in scope, via the public Memory facade.

    `memory` is a stele.core.memory.Memory; typed as object to avoid a heavy
    import here. Passes status_filter=["active"] so superseded/retracted records
    are excluded -- callers that name themselves "active_memories" should only
    return current truth."""
    result = memory.list(scope, ["active"], limit=limit)  # type: ignore[attr-defined]
    return list(result)
