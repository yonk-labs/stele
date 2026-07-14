"""DistilledView model shapes -- single source of truth for distill outputs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DistilledItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str = ""
    detail: str = ""
    confidence: float = 1.0
    source_refs: list[str] = Field(default_factory=list)
    # Id of the source memory when the item maps 1:1 to a stored record
    # (facts/state/precedents/skills/best_practices/rules; dedup keeps the
    # first occurrence's id, matching its "first record wins" convention).
    # Empty for synthesized aggregates (episodes/spans). Lets consumers join
    # a view item back to the store exactly instead of by string equality on
    # detail (bento#962).
    memory_id: str = ""


class Rule(DistilledItem):
    """A guardrail distilled as a don't/do pair. do_instead must be in-family
    (same provider/family as dont); cross-vendor substitutions are forbidden."""

    dont: str = ""
    do_instead: str = ""
    domain: str = "prose"


class EpisodeItem(DistilledItem):
    """One distilled episode: a "what happened" summary for a single session,
    synthesized from the memories that session produced (NOT a new store row).

    ``when`` is the episode's temporal anchor (the session artifact's
    ``session_mtime`` if present, else its ``created_at``). ``decisions`` and
    ``pitfalls`` are the key kinded items that session yielded. ``source_refs``
    merges the session artifact ref with every back-linked memory's refs."""

    when: datetime | None = None
    session_id: str | None = None
    ref: str = ""
    decisions: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class SpanItem(DistilledItem):
    """A cross-session span: a topic or task arc that crosses several sessions
    (the whole auth refactor, not one sitting). Built by clustering episodes by
    the embedding similarity of their summaries (Phase 3); with no embedder
    injected, every episode is its own one-member span.

    ``span_id`` is deterministic (derived from the member session ids). ``refs``
    and ``session_ids`` are the member episodes. ``started`` / ``ended`` bracket
    the span's time range (the earliest and latest member ``when``)."""

    span_id: str = ""
    refs: list[str] = Field(default_factory=list)
    session_ids: list[str] = Field(default_factory=list)
    started: datetime | None = None
    ended: datetime | None = None


class DistilledView(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: str
    items: list[Rule | EpisodeItem | SpanItem | DistilledItem] = Field(default_factory=list)
    used_llm: bool = False
    stats: dict[str, float] = Field(default_factory=dict)
