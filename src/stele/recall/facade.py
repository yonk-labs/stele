"""Recall facade — callable property exposing canonical + shim entries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from stele.core.exceptions import CapabilityError
from stele.recall.abstain import AbstainStrategy
from stele.recall.adaptive import AdaptiveStrategy
from stele.recall.artifact_search import ArtifactSearchStrategy
from stele.recall.base import DigestPacker, Strategy, _RecallDeps
from stele.recall.digest import DigestStrategy
from stele.recall.graph_search import GraphSearchStrategy
from stele.recall.memory_search import MemorySearchStrategy
from stele.recall.models import (
    RecallContext,
    RecallRequest,
    RecallResult,
    StrategyName,
)
from stele.recall.raw_fetch import RawFetchStrategy
from stele.recall.summary_only import SummaryOnlyStrategy

if TYPE_CHECKING:
    from stele.core.config import RecallConfig
    from stele.core.memory import Memory
    from stele.core.memory_record import MemoryScope
    from stele.core.stash import Stele
    from stele.pii.regex import RegexPIIScrubber
    from stele.pii.scrubber import DisabledPIIScrubber


class Recall:
    def __init__(
        self,
        *,
        stele: Stele,
        memory: Memory,
        scrubber: RegexPIIScrubber | DisabledPIIScrubber,
        config: RecallConfig,
        digest_packer: DigestPacker | None = None,
    ) -> None:
        self._deps = _RecallDeps(
            stele=stele,
            memory=memory,
            scrubber=scrubber,
            config=config,
            digest_packer=digest_packer,
        )
        self._registry: dict[StrategyName, Strategy] = {
            "summary_only": SummaryOnlyStrategy(),
            "memory_search": MemorySearchStrategy(),
            "artifact_search": ArtifactSearchStrategy(),
            "graph_search": GraphSearchStrategy(),
            "adaptive": AdaptiveStrategy(),
            "raw_fetch": RawFetchStrategy(),
            "abstain": AbstainStrategy(),
            "digest": DigestStrategy(),
        }

    def __call__(
        self,
        *,
        query: str = "",
        scope: MemoryScope,
        strategy: StrategyName | None = None,
        artifact_id: str | None = None,
        sufficient: Callable[[RecallContext], bool] | None = None,
        max_memory_hits: int | None = None,
        max_artifact_hits: int | None = None,
        confidence_floor: float | None = None,
        as_of: datetime | None = None,
        version_filter: str | None = None,
        retracted_behavior: str | None = None,
        supersession_behavior: str | None = None,
    ) -> RecallResult:
        if not self._deps.config.enabled:
            raise CapabilityError("recall is disabled in config")
        req = RecallRequest(
            query=query,
            scope=scope,
            strategy=strategy or self._deps.config.default_strategy,
            artifact_id=artifact_id,
            sufficient=sufficient,
            max_memory_hits=(
                max_memory_hits
                if max_memory_hits is not None
                else self._deps.config.max_memory_hits
            ),
            max_artifact_hits=(
                max_artifact_hits
                if max_artifact_hits is not None
                else self._deps.config.max_artifact_hits
            ),
            confidence_floor=confidence_floor,
            as_of=as_of,
            version_filter=version_filter,
            retracted_behavior=retracted_behavior,  # type: ignore[arg-type]
            supersession_behavior=supersession_behavior,  # type: ignore[arg-type]
        )
        return self._registry[req.strategy].execute(req, self._deps)

    # Convenience shims — each is a one-liner around __call__.

    def summary_only(self, *, artifact_id: str, scope: MemoryScope) -> RecallResult:
        return self(scope=scope, strategy="summary_only", artifact_id=artifact_id)

    def memory_search(
        self, *, query: str, scope: MemoryScope, artifact_id: str | None = None
    ) -> RecallResult:
        return self(query=query, scope=scope, strategy="memory_search", artifact_id=artifact_id)

    def artifact_search(
        self, *, query: str, scope: MemoryScope, artifact_id: str | None = None
    ) -> RecallResult:
        return self(
            query=query, scope=scope, strategy="artifact_search", artifact_id=artifact_id
        )

    def graph_search(
        self,
        *,
        query: str,
        scope: MemoryScope,
        artifact_id: str | None = None,
        as_of: datetime | None = None,
        version_filter: str | None = None,
        retracted_behavior: str | None = None,
        supersession_behavior: str | None = None,
    ) -> RecallResult:
        return self(
            query=query,
            scope=scope,
            strategy="graph_search",
            artifact_id=artifact_id,
            as_of=as_of,
            version_filter=version_filter,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
        )

    def adaptive(
        self,
        *,
        query: str,
        scope: MemoryScope,
        artifact_id: str | None = None,
        sufficient: Callable[[RecallContext], bool] | None = None,
    ) -> RecallResult:
        return self(
            query=query,
            scope=scope,
            strategy="adaptive",
            artifact_id=artifact_id,
            sufficient=sufficient,
        )

    def raw_fetch(self, *, artifact_id: str, scope: MemoryScope) -> RecallResult:
        return self(scope=scope, strategy="raw_fetch", artifact_id=artifact_id)

    def abstain(
        self,
        *,
        query: str = "",
        scope: MemoryScope,
        reason: str | None = None,
    ) -> RecallResult:
        if not self._deps.config.enabled:
            raise CapabilityError("recall is disabled in config")
        req = RecallRequest(query=query, scope=scope, strategy="abstain")
        if reason is not None:
            object.__setattr__(req, "_abstain_reason", reason)
        return self._registry["abstain"].execute(req, self._deps)

    def close(self) -> None:
        # The facade owns no resources beyond the deps struct.
        pass
