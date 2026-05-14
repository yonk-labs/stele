"""Score normalization and hit merging — pure functions, no I/O."""

from __future__ import annotations

from stele.recall.models import Citation


def normalize_scores(citations: list[Citation]) -> list[Citation]:
    """Linearly normalize scores across the input list to [0, 1].

    Special cases:
    - Empty input → empty output.
    - Single hit → score becomes 1.0.
    - All equal scores → all become 1.0 (preserves the "we found stuff" signal).
    """
    if not citations:
        return []
    scores = [c.score for c in citations]
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [c.model_copy(update={"score": 1.0}) for c in citations]
    span = hi - lo
    return [
        c.model_copy(update={"score": (c.score - lo) / span}) for c in citations
    ]


def merge_hits(*sources: list[Citation]) -> list[Citation]:
    """Merge citation lists, dedup by (kind, id) keeping max score, sort desc."""
    best: dict[tuple[str, str], Citation] = {}
    for source in sources:
        for c in source:
            key = (c.kind, c.id)
            existing = best.get(key)
            if existing is None or c.score > existing.score:
                best[key] = c
    return sorted(best.values(), key=lambda c: c.score, reverse=True)
