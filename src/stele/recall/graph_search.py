"""GraphSearchStrategy — stub until Phase 5 wires pg-raggraph."""

from __future__ import annotations

from stele.core.exceptions import CapabilityError
from stele.recall.base import _RecallDeps
from stele.recall.models import RecallRequest, RecallResult


class GraphSearchStrategy:
    name = "graph_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        del request, deps
        raise CapabilityError(
            "graph_search requires Phase 5 pg-raggraph adapter"
        )
