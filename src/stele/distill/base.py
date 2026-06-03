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


def active_memories(memory: object, scope: MemoryScope, limit: int = 1000) -> list[MemoryRecord]:
    """All ACTIVE (newest-valid) memories in scope, via the public Memory facade.

    `memory` is a stele.core.memory.Memory; typed as object to avoid a heavy
    import here. Passes status_filter=["active"] so superseded/retracted records
    are excluded -- callers that name themselves "active_memories" should only
    return current truth."""
    result = memory.list(scope, ["active"], limit=limit)  # type: ignore[attr-defined]
    return list(result)
