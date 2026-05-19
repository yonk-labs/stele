from datetime import UTC, datetime

from stele.workgraph.models import TaskEdge, TaskNode, TaskTraceEvent, WorkGraph
from stele.workgraph.renderers import (
    WorkGraphBundle,
    render_json,
    render_markdown,
    render_mermaid,
)


def _bundle() -> WorkGraphBundle:
    now = datetime.now(UTC)
    g = WorkGraph(
        id="g1", namespace="ns", session_id="s1", scope=None, title="Ship it",
        status="active", created_at=now, updated_at=now,
        source_refs=["stele://ns/seed"],
    )
    n1 = TaskNode(
        id="n1", graph_id="g1", kind="goal", label="Deploy service",
        summary="deploy the API service to prod", status="active",
        source_refs=["stele://ns/plan"], artifact_refs=["stele://ns/run-log"],
        memory_refs=[], created_at=now, updated_at=now,
    )
    n2 = TaskNode(
        id="n2", graph_id="g1", kind="blocker", label="DB migration pending",
        summary="migration 0042 not applied", status="blocked",
        source_refs=["stele://ns/ticket"], artifact_refs=[], memory_refs=[],
        created_at=now, updated_at=now,
    )
    e = TaskEdge(
        id="e1", graph_id="g1", from_node_id="n2", to_node_id="n1",
        kind="blocks", source_refs=["stele://ns/ticket"], created_at=now,
    )
    ev = TaskTraceEvent(
        id="t1", graph_id="g1", node_id="n1", event_kind="tool_result",
        summary="kubectl apply ok", source_refs=["stele://ns/run-log"],
        timestamp=now,
    )
    return WorkGraphBundle(graph=g, nodes=[n1, n2], edges=[e], events=[ev])


def test_mermaid_has_ids_and_compact_labels() -> None:
    out = render_mermaid(_bundle())
    assert out.startswith("flowchart TD")
    assert "n1" in out and "n2" in out
    assert "Deploy service" in out
    assert "n2 -->|blocks| n1" in out


def test_markdown_includes_citations_and_drilldown_refs() -> None:
    out = render_markdown(_bundle())
    assert "# Ship it" in out
    assert "stele://ns/plan" in out          # node source ref (citation)
    assert "stele://ns/run-log" in out       # artifact drill-down ref
    assert "g1" in out and "n1" in out       # ids for drill-down


def test_json_round_trips() -> None:
    b = _bundle()
    s = render_json(b)
    back = WorkGraphBundle.model_validate_json(s)
    assert back.graph.id == "g1"
    assert [n.id for n in back.nodes] == ["n1", "n2"]
    assert back.edges[0].kind == "blocks"
    assert back.events[0].summary == "kubectl apply ok"
    assert render_json(back) == s  # stable / deterministic


def test_mermaid_label_sanitized() -> None:
    b = _bundle()
    b.nodes[0].label = 'weird "quoted"\nlabel | pipe'
    out = render_mermaid(b)
    # no raw quote/newline/pipe should break the node label token
    assert '"quoted"' not in out
    assert "\n" not in out.split("n1[")[1].split("]")[0]
