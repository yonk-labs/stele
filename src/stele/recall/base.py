"""Strategy Protocol + dependency-injection struct."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from stele.recall.models import RecallRequest, RecallResult

if TYPE_CHECKING:
    from stele.core.config import RecallConfig
    from stele.core.memory import Memory
    from stele.core.stash import Stele
    from stele.pii.regex import RegexPIIScrubber
    from stele.pii.scrubber import DisabledPIIScrubber


@dataclass(frozen=True)
class _RecallDeps:
    """Injected to every Strategy.execute call. Kept private — strategies don't construct these."""

    stele: Stele
    memory: Memory
    scrubber: RegexPIIScrubber | DisabledPIIScrubber
    config: RecallConfig


class Strategy(Protocol):
    name: str  # equals one of StrategyName literals; used as registry key in adaptive

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult: ...
