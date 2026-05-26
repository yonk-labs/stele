"""Strategy Protocol + dependency-injection struct."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from stele.recall.models import RecallRequest, RecallResult

if TYPE_CHECKING:
    from stele.core.artifact import SearchHit
    from stele.core.config import RecallConfig
    from stele.core.memory import Memory
    from stele.core.stash import Stele
    from stele.pii.regex import RegexPIIScrubber
    from stele.pii.scrubber import DisabledPIIScrubber


class DigestPacker(Protocol):
    """Packs retrieved hits into a summary+facts+top-chunks context string.

    The concrete impl lives under ``summary/`` (lede is allowed there) and is
    injected so ``recall/`` stays free of lede/chunkshop imports.
    """

    def pack(self, hits: Sequence[SearchHit], query: str) -> str: ...


@dataclass(frozen=True)
class _RecallDeps:
    """Injected to every Strategy.execute call. Kept private — strategies don't construct these."""

    stele: Stele
    memory: Memory
    scrubber: RegexPIIScrubber | DisabledPIIScrubber
    config: RecallConfig
    digest_packer: DigestPacker | None = None


class Strategy(Protocol):
    name: str  # equals one of StrategyName literals; used as registry key in adaptive

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult: ...
