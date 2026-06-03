"""DistilledView model shapes -- single source of truth for distill outputs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DistilledItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str = ""
    detail: str = ""
    confidence: float = 1.0
    source_refs: list[str] = Field(default_factory=list)


class Rule(DistilledItem):
    """A guardrail distilled as a don't/do pair. do_instead must be in-family
    (same provider/family as dont); cross-vendor substitutions are forbidden."""

    dont: str = ""
    do_instead: str = ""
    domain: str = "prose"


class DistilledView(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: str
    items: list[Rule | DistilledItem] = Field(default_factory=list)
    used_llm: bool = False
    stats: dict[str, float] = Field(default_factory=dict)
