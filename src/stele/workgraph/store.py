"""WorkGraphStore Protocol + in-memory backend (T-RAM-002).

Backend-neutral contract. Deterministic ordering. `as_of` is part of the
contract but capability-honest: the in-memory backend raises
`CapabilityError` rather than silently ignoring it (a durable backend
implements it — T-RAM-003).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from stele.core.exceptions import ArtifactNotFound, CapabilityError
from stele.workgraph.models import TaskEdge, TaskNode, TaskTraceEvent, WorkGraph
from stele.workgraph.validators import validate_status_transition


class WorkGraphStore(Protocol):
    def create_graph(self, graph: WorkGraph) -> WorkGraph: ...

    def get_graph(
        self, graph_id: str, *, as_of: datetime | None = None
    ) -> WorkGraph | None: ...

    def update_graph(self, graph_id: str, patch: Mapping[str, Any]) -> WorkGraph: ...

    def list_graphs(
        self,
        *,
        namespace: str,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[WorkGraph]: ...

    def add_node(self, node: TaskNode) -> TaskNode: ...

    def update_node(self, node_id: str, patch: Mapping[str, Any]) -> TaskNode: ...

    def add_edge(self, edge: TaskEdge) -> TaskEdge: ...

    def add_event(self, event: TaskTraceEvent) -> TaskTraceEvent: ...

    def query_graph(
        self,
        *,
        namespace: str,
        query: str,
        session_id: str | None = None,
        active_only: bool = True,
        limit: int = 20,
    ) -> list[TaskNode]: ...


def _key(g: WorkGraph) -> tuple[datetime, str]:
    return (g.created_at, g.id)


class InProcessWorkGraphStore:
    """Dict-backed. For models, contract tests, and the memory backend."""

    def __init__(self) -> None:
        self._graphs: dict[str, WorkGraph] = {}
        self._nodes: dict[str, TaskNode] = {}
        self._edges: dict[str, TaskEdge] = {}
        self._events: dict[str, TaskTraceEvent] = {}

    def create_graph(self, graph: WorkGraph) -> WorkGraph:
        self._graphs[graph.id] = graph
        return graph

    def get_graph(
        self, graph_id: str, *, as_of: datetime | None = None
    ) -> WorkGraph | None:
        if as_of is not None:
            raise CapabilityError(
                "WorkGraph as_of is not supported by the in-memory backend; "
                "use the SQLite WorkGraph store"
            )
        return self._graphs.get(graph_id)

    def update_graph(self, graph_id: str, patch: Mapping[str, Any]) -> WorkGraph:
        existing = self._graphs.get(graph_id)
        if existing is None:
            raise ArtifactNotFound(f"WorkGraph not found: {graph_id}")
        merged = existing.model_dump()
        merged.update(patch)
        merged["updated_at"] = datetime.now(UTC)
        updated = WorkGraph(**merged)  # re-validates
        self._graphs[graph_id] = updated
        return updated

    def list_graphs(
        self,
        *,
        namespace: str,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[WorkGraph]:
        out = [
            g
            for g in self._graphs.values()
            if g.namespace == namespace
            and (session_id is None or g.session_id == session_id)
            and (status is None or g.status == status)
        ]
        out.sort(key=_key)
        return out[:limit]

    def add_node(self, node: TaskNode) -> TaskNode:
        self._nodes[node.id] = node
        return node

    def update_node(self, node_id: str, patch: Mapping[str, Any]) -> TaskNode:
        existing = self._nodes.get(node_id)
        if existing is None:
            raise ArtifactNotFound(f"WorkGraph node not found: {node_id}")
        if "status" in patch and patch["status"] != existing.status:
            validate_status_transition(existing.status, str(patch["status"]))
        merged = existing.model_dump()
        merged.update(patch)
        merged["updated_at"] = datetime.now(UTC)
        updated = TaskNode(**merged)  # re-runs all model validators
        self._nodes[node_id] = updated
        return updated

    def add_edge(self, edge: TaskEdge) -> TaskEdge:
        self._edges[edge.id] = edge
        return edge

    def add_event(self, event: TaskTraceEvent) -> TaskTraceEvent:
        self._events[event.id] = event
        return event

    def query_graph(
        self,
        *,
        namespace: str,
        query: str,
        session_id: str | None = None,
        active_only: bool = True,
        limit: int = 20,
    ) -> list[TaskNode]:
        q = query.lower()
        hits: list[TaskNode] = []
        for n in self._nodes.values():
            g = self._graphs.get(n.graph_id)
            if g is None or g.namespace != namespace:
                continue
            if session_id is not None and g.session_id != session_id:
                continue
            if active_only and g.status != "active":
                continue
            if q in n.label.lower() or q in n.summary.lower():
                hits.append(n)
        hits.sort(key=lambda n: (n.created_at, n.id))
        return hits[:limit]
