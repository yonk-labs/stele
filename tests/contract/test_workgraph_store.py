"""WorkGraphStore contract — every backend passes the same suite.

T-RAM-002 adds the in-memory backend; T-RAM-003 appends the SQLite backend
to ``STORES`` so it runs the identical contract.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele.core.exceptions import ArtifactNotFound, CapabilityError, ValidationError
from stele.workgraph.models import (
    NodeStatus,
    TaskEdge,
    TaskNode,
    TaskTraceEvent,
    WorkGraph,
    WorkGraphStatus,
)
from stele.workgraph.sqlite_store import SQLiteWorkGraphStore
from stele.workgraph.store import InProcessWorkGraphStore, WorkGraphStore

StoreFactory = Callable[[], WorkGraphStore]


def _sqlite_store() -> WorkGraphStore:
    path = Path(tempfile.gettempdir()) / f"wg_{uuid.uuid4().hex}.db"
    return SQLiteWorkGraphStore(str(path))


STORES: list[tuple[str, StoreFactory]] = [
    ("memory", lambda: InProcessWorkGraphStore()),
    ("sqlite", _sqlite_store),
]


@pytest.fixture(params=[f for _, f in STORES], ids=[n for n, _ in STORES])
def store(request: pytest.FixtureRequest) -> WorkGraphStore:
    factory: StoreFactory = request.param
    return factory()


def _now() -> datetime:
    return datetime.now(UTC)


def _graph(gid: str = "g1", ns: str = "ns", sid: str | None = "s1",
           status: WorkGraphStatus = "active") -> WorkGraph:
    return WorkGraph(
        id=gid, namespace=ns, session_id=sid, scope=None, title="T",
        status=status, created_at=_now(), updated_at=_now(),
        source_refs=[f"stele://{ns}/seed"],
    )


def _node(nid: str, gid: str = "g1", label: str = "do x",
          status: NodeStatus = "pending") -> TaskNode:
    return TaskNode(
        id=nid, graph_id=gid, kind="goal", label=label, summary=label,
        status=status, source_refs=["stele://ns/seed"], artifact_refs=[],
        memory_refs=[], created_at=_now(), updated_at=_now(),
    )


def test_create_get_graph(store: WorkGraphStore) -> None:
    g = store.create_graph(_graph())
    assert g.id == "g1"
    got = store.get_graph("g1")
    assert got is not None and got.namespace == "ns"
    assert store.get_graph("missing") is None


def test_list_graphs_filters_deterministic(store: WorkGraphStore) -> None:
    store.create_graph(_graph("g1", ns="a", sid="s1", status="active"))
    store.create_graph(_graph("g2", ns="a", sid="s2", status="completed"))
    store.create_graph(_graph("g3", ns="b", sid="s1", status="active"))
    a = store.list_graphs(namespace="a")
    assert {g.id for g in a} == {"g1", "g2"}
    assert [g.id for g in store.list_graphs(namespace="a")] == \
           [g.id for g in store.list_graphs(namespace="a")]  # deterministic
    assert {g.id for g in store.list_graphs(namespace="a", session_id="s1")} == {"g1"}
    assert {g.id for g in store.list_graphs(namespace="a", status="active")} == {"g1"}


def test_add_node_edge_event(store: WorkGraphStore) -> None:
    store.create_graph(_graph())
    n1 = store.add_node(_node("n1"))
    store.add_node(_node("n2"))
    assert n1.id == "n1"
    e = store.add_edge(TaskEdge(
        id="e1", graph_id="g1", from_node_id="n1", to_node_id="n2",
        kind="depends_on", source_refs=["stele://ns/seed"], created_at=_now(),
    ))
    assert e.kind == "depends_on"
    ev = store.add_event(TaskTraceEvent(
        id="t1", graph_id="g1", node_id="n1", event_kind="tool_result",
        summary="ran", source_refs=["stele://ns/seed"], timestamp=_now(),
    ))
    assert ev.id == "t1"


def test_update_node_validates_transition(store: WorkGraphStore) -> None:
    store.create_graph(_graph())
    store.add_node(_node("n1", status="pending"))
    assert store.update_node("n1", {"status": "active"}).status == "active"
    assert store.update_node("n1", {"status": "done"}).status == "done"
    with pytest.raises(ValidationError):
        store.update_node("n1", {"status": "active"})  # done is terminal
    with pytest.raises(ArtifactNotFound):
        store.update_node("missing", {"status": "active"})
    # non-status patch (label) still re-validates the model
    store.add_node(_node("n2", status="pending"))
    assert store.update_node("n2", {"label": "renamed"}).label == "renamed"


def test_query_graph_deterministic(store: WorkGraphStore) -> None:
    store.create_graph(_graph("g1", ns="ns", sid="s1", status="active"))
    store.create_graph(_graph("g2", ns="ns", sid="s2", status="completed"))
    store.add_node(_node("n1", "g1", label="deploy the service"))
    store.add_node(_node("n2", "g1", label="write the report"))
    store.add_node(_node("n3", "g2", label="deploy the docs"))
    hits = store.query_graph(namespace="ns", query="deploy")
    assert {n.id for n in hits} == {"n1"}  # active_only excludes g2's node
    again = store.query_graph(namespace="ns", query="deploy")
    assert [n.id for n in hits] == [n.id for n in again]
    allhits = store.query_graph(namespace="ns", query="deploy", active_only=False)
    assert {n.id for n in allhits} == {"n1", "n3"}
    assert store.query_graph(namespace="ns", query="deploy",
                             session_id="s1") and not store.query_graph(
        namespace="ns", query="deploy", session_id="s2")


def test_as_of_capability_honesty(store: WorkGraphStore) -> None:
    store.create_graph(_graph())
    # memory backend: as_of is explicitly unsupported, not silently ignored
    if isinstance(store, InProcessWorkGraphStore):
        with pytest.raises(CapabilityError):
            store.get_graph("g1", as_of=_now() - timedelta(hours=1))
    else:  # durable backend implements it
        assert store.get_graph("g1", as_of=_now()) is not None
