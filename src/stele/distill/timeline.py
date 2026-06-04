"""Timeline distillation: the same episodes, ordered oldest-first.

The eighth distill view (Phase 3 of episodic recall). Where ``episodes`` is
newest-first ("what are the most recent things that happened"), ``timeline`` is
the ordered narrative ("show me the sequence of what happened"), optionally
within a ``since``/``until`` window and optionally filtered to episodes relevant
to a ``query``.

Like the other views this is COMPUTED ON READ. It reuses :func:`build_episodes`
(the shared episode grouping/windowing), so the grouping logic lives in one
place. The optional ``query`` filter is semantic when an embedder is injected
(``stele._distill_embedder``, cosine of episode summary vs query), with a
deterministic token-overlap fallback when none is injected, so it never errors
and stays oracle-free. This module imports no LLM client at module top
(enforced by ``tests/unit/distill/test_architecture.py``)."""

from __future__ import annotations

import re
from datetime import datetime

from stele.core.memory_record import MemoryScope
from stele.distill.base import Embedder, _cosine
from stele.distill.episodes import _as_naive_utc, build_episodes
from stele.distill.models import DistilledItem, DistilledView, EpisodeItem

# An episode passes the deterministic (no-embedder) query filter when at least
# this fraction of the query's content tokens appear in its text.
_TOKEN_OVERLAP_FLOOR = 0.5
# An episode passes the semantic (embedder) query filter at or above this cosine.
_QUERY_SIM_FLOOR = 0.3


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _episode_text(item: EpisodeItem) -> str:
    """Everything an episode says, for matching a query against it."""
    parts = [item.summary, item.detail, *item.decisions, *item.pitfalls, *item.facts]
    return " ".join(p for p in parts if p)


def _matches_query(item: EpisodeItem, query: str, embedder: Embedder | None) -> bool:
    if embedder is not None:
        sim = _cosine(embedder.embed(query), embedder.embed(_episode_text(item)))
        return sim >= _QUERY_SIM_FLOOR
    q = _tokens(query)
    if not q:
        return True
    overlap = len(q & _tokens(_episode_text(item))) / len(q)
    return overlap >= _TOKEN_OVERLAP_FLOOR


async def distill_timeline(
    d: object,
    scope: MemoryScope,
    since: datetime | None = None,
    until: datetime | None = None,
    query: str | None = None,
) -> DistilledView:
    episodes, used_llm = build_episodes(d, scope, since, until)

    if query:
        embedder: Embedder | None = d._embedder  # type: ignore[attr-defined]
        episodes = [e for e in episodes if _matches_query(e, query, embedder)]

    # Oldest-first: the narrative order, the opposite of episodes().
    episodes.sort(key=lambda it: _as_naive_utc(it.when) if it.when else datetime.min)

    items: list[DistilledItem] = list(episodes)
    return DistilledView(
        mode="timeline",
        items=items,
        used_llm=used_llm,
        stats={"n": float(len(items))},
    )
