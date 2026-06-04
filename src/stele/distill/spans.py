"""Span distillation: group episodes into cross-session topic/task arcs.

The ninth distill view (Phase 3 of episodic recall). A *span* is a topic or task
arc that crosses several sessions: the whole auth refactor, not one sitting.
Episodes are clustered by the embedding similarity of their summaries, reusing
the greedy cosine-threshold clustering pattern that ``base.consolidate`` uses
(``Embedder`` + ``_cosine`` + cluster when cosine >= threshold).

Like the other views this is COMPUTED ON READ. It reuses :func:`build_episodes`
(the shared episode grouping), so the grouping logic lives in one place.

Clustering needs an injected embedder (``stele._distill_embedder``, the same one
``consolidate`` requires). With NO embedder injected the deterministic fallback
is one-episode-per-span (each episode is its own single-member span), so the
view never errors. Each span's summary is composed deterministically from its
members, with an optional injected-LLM refine and a deterministic fallback on
any failure or empty/over-long reply (the same contract as episodes()). This
module imports no LLM client at module top (enforced by
``tests/unit/distill/test_architecture.py``)."""

from __future__ import annotations

import hashlib
from datetime import datetime

from stele.core.memory_record import MemoryScope
from stele.distill.base import Embedder, LLMSynthesizer, _cosine
from stele.distill.episodes import _as_naive_utc, _llm_and_allowed, build_episodes
from stele.distill.models import DistilledItem, DistilledView, EpisodeItem, SpanItem


def _cluster(episodes: list[EpisodeItem], embedder: Embedder, threshold: float) -> list[list[int]]:
    """Greedy cosine-threshold clustering over episode summaries, mirroring
    ``base.consolidate``: each episode joins the first cluster whose seed it is
    near (cosine >= threshold), else seeds a new cluster. Returns lists of
    indices into ``episodes``."""
    vecs = [embedder.embed(e.summary or e.detail) for e in episodes]
    used = [False] * len(episodes)
    clusters: list[list[int]] = []
    for i in range(len(episodes)):
        if used[i]:
            continue
        members = [i]
        used[i] = True
        for j in range(i + 1, len(episodes)):
            if not used[j] and _cosine(vecs[i], vecs[j]) >= threshold:
                members.append(j)
                used[j] = True
        clusters.append(members)
    return clusters


def _span_id(session_ids: list[str], refs: list[str]) -> str:
    """Deterministic id from the member identity (session ids, else refs), so the
    same membership always yields the same span id."""
    basis = "|".join(session_ids) if any(session_ids) else "|".join(refs)
    return "span-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]  # noqa: S324


def _compose_span_summary(members: list[EpisodeItem]) -> str:
    """Deterministic span summary: the member episode summaries joined, prefixed
    with the member count when the span crosses more than one session."""
    lines = [m.summary.strip() for m in members if m.summary.strip()]
    body = " -> ".join(lines) if lines else ""
    n = len(members)
    if n == 1:
        return body
    tag = f"[{n} sessions] "
    return f"{tag}{body}".strip()


def _refine_span_summary(
    llm: LLMSynthesizer, deterministic: str, members: list[EpisodeItem]
) -> str:
    """LLM tightening of the deterministic span summary into one arc sentence.
    Any failure or empty/over-long reply falls back to the deterministic
    summary unchanged (same contract as episodes._refine_summary)."""
    listing = "\n".join(f"- {m.summary.strip()}" for m in members if m.summary.strip())
    if not listing:
        return deterministic
    prompt = (
        "These are the per-session summaries of one multi-session work arc:\n"
        f"{listing}\n\n"
        "Write ONE plain sentence describing the overall arc across these "
        "sessions. Reply with only the sentence, no prose, no quotes."
    )
    try:
        reply = llm(prompt).strip()
    except Exception:  # noqa: BLE001 -- any LLM failure falls back to deterministic
        return deterministic
    if not reply or len(reply) > 500:
        return deterministic
    return reply


def _span_from_members(
    members: list[EpisodeItem],
    llm: LLMSynthesizer | None,
    allowed: bool,
) -> SpanItem:
    refs = list(dict.fromkeys(m.ref for m in members if m.ref))
    session_ids = [m.session_id for m in members if m.session_id]
    whens = [m.when for m in members if m.when is not None]
    started = min(whens, key=_as_naive_utc) if whens else None
    ended = max(whens, key=_as_naive_utc) if whens else None
    summary = _compose_span_summary(members)
    if allowed and llm is not None:
        summary = _refine_span_summary(llm, summary, members)
    merged_refs = list(dict.fromkeys(r for m in members for r in m.source_refs))
    return SpanItem(
        summary=summary,
        detail="; ".join(m.summary.strip() for m in members if m.summary.strip()),
        span_id=_span_id(session_ids, refs),
        refs=refs,
        session_ids=session_ids,
        started=started,
        ended=ended,
        confidence=1.0,
        source_refs=merged_refs,
    )


async def distill_spans(
    d: object,
    scope: MemoryScope,
    threshold: float = 0.82,
) -> DistilledView:
    episodes, _ = build_episodes(d, scope)
    llm, allowed = _llm_and_allowed(d)
    embedder: Embedder | None = d._embedder  # type: ignore[attr-defined]

    if embedder is None:
        # Deterministic fallback: every episode is its own one-member span. No
        # clustering, no error -- spans degrades to "one span per session".
        index_groups: list[list[int]] = [[i] for i in range(len(episodes))]
    else:
        index_groups = _cluster(episodes, embedder, threshold)

    spans = [
        _span_from_members([episodes[i] for i in group], llm, allowed)
        for group in index_groups
    ]
    # Newest-first by span end, mirroring episodes()'s newest-first default.
    spans.sort(
        key=lambda s: _as_naive_utc(s.ended) if s.ended else datetime.min,
        reverse=True,
    )

    items: list[DistilledItem] = list(spans)
    return DistilledView(
        mode="spans",
        items=items,
        used_llm=allowed,
        stats={"n": float(len(items)), "episodes": float(len(episodes))},
    )
