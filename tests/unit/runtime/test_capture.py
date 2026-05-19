from datetime import UTC, datetime

from stele.core.stash import Stele
from stele.recall.models import RecallResult, RecallStats
from stele.runtime.capture import (
    capture_tool_result,
    close_session_graphs,
    record_recall_used,
)
from stele.workgraph.models import WorkGraph
from stele.workgraph.store import InProcessWorkGraphStore


def _stele() -> Stele:
    return Stele.from_config({"backend": {"type": "memory"}})


def _graph(wg: InProcessWorkGraphStore, gid: str, ns: str, sid: str) -> None:
    now = datetime.now(UTC)
    wg.create_graph(WorkGraph(
        id=gid, namespace=ns, session_id=sid, scope=None, title="t",
        status="active", created_at=now, updated_at=now,
        source_refs=[f"stele://{ns}/seed"],
    ))


def test_large_tool_result_stored_as_artifact_event_has_refs_only() -> None:
    s = _stele()
    wg = InProcessWorkGraphStore()
    _graph(wg, "g1", "ns", "s1")
    raw = "SECRET_BIG_PAYLOAD " + ("x" * 5000)
    ev = capture_tool_result(
        stele=s, wg_store=wg, graph_id="g1", tool_name="Bash",
        result=raw, namespace="ns", session_id="s1",
    )
    assert ev.event_kind == "tool_result"
    assert ev.source_refs and ev.source_refs[0].startswith("stele://")
    assert len(ev.summary) <= 512
    assert "x" * 5000 not in ev.summary  # no raw payload in the graph
    s.close()


def test_record_recall_used_records_injected_refs() -> None:
    wg = InProcessWorkGraphStore()
    _graph(wg, "g1", "ns", "s1")
    rr = RecallResult(
        strategy_used="memory_search", context="ctx", citations=[],
        escalations=[], source_refs=["stele://ns/m1", "stele://ns/m2"],
        stats=RecallStats(),
    )
    ev = record_recall_used(wg_store=wg, graph_id="g1", recall_result=rr,
                            namespace="ns")
    assert ev.event_kind == "recall_used"
    assert ev.source_refs == ["stele://ns/m1", "stele://ns/m2"]


def test_close_session_graphs_is_session_scoped() -> None:
    wg = InProcessWorkGraphStore()
    _graph(wg, "g1", "ns", "s1")
    _graph(wg, "g2", "ns", "s2")
    n = close_session_graphs(wg_store=wg, namespace="ns", session_id="s1")
    assert n == 1
    assert wg.get_graph("g1") is not None
    g1 = wg.get_graph("g1")
    g2 = wg.get_graph("g2")
    assert g1 is not None and g1.status == "completed"
    assert g2 is not None and g2.status == "active"  # other session untouched
