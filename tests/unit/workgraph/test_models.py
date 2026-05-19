from datetime import UTC, datetime

import pytest

from stele.core.exceptions import ValidationError
from stele.workgraph.models import TaskEdge, TaskNode, TaskTraceEvent, WorkGraph
from stele.workgraph.validators import (
    RAW_CONTENT_MAX,
    assert_no_raw_content,
    validate_refs,
    validate_status_transition,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_models_serialize_round_trip() -> None:
    g = WorkGraph(
        id="g1", namespace="ns", session_id="s1", scope=None, title="T",
        status="active", created_at=_now(), updated_at=_now(),
        source_refs=["stele://ns/a"],
    )
    dumped = g.model_dump_json()
    assert WorkGraph.model_validate_json(dumped).id == "g1"

    n = TaskNode(
        id="n1", graph_id="g1", kind="goal", label="goal", summary="do the thing",
        status="pending", source_refs=["stele://ns/a"], artifact_refs=[],
        memory_refs=[], created_at=_now(), updated_at=_now(),
    )
    assert TaskNode.model_validate_json(n.model_dump_json()).kind == "goal"

    e = TaskEdge(
        id="e1", graph_id="g1", from_node_id="n1", to_node_id="n2",
        kind="depends_on", source_refs=["stele://ns/a"], created_at=_now(),
    )
    assert TaskEdge.model_validate_json(e.model_dump_json()).kind == "depends_on"

    ev = TaskTraceEvent(
        id="t1", graph_id="g1", node_id="n1", event_kind="tool_result",
        summary="ran tool", source_refs=["stele://ns/a"], timestamp=_now(),
    )
    assert TaskTraceEvent.model_validate_json(ev.model_dump_json()).event_kind == "tool_result"


def test_validate_refs_rejects_bad_ref() -> None:
    validate_refs(["stele://ns/ok"])  # no raise
    with pytest.raises(ValidationError):
        validate_refs(["not-a-ref"])
    with pytest.raises(ValidationError):
        validate_refs(["http://ns/x"])


def test_assert_no_raw_content_threshold() -> None:
    assert_no_raw_content("short summary")  # ok
    with pytest.raises(ValidationError):
        assert_no_raw_content("x" * (RAW_CONTENT_MAX + 1))


def test_status_transitions() -> None:
    validate_status_transition("pending", "active")
    validate_status_transition("active", "done")
    validate_status_transition("active", "abandoned")
    validate_status_transition("blocked", "active")
    with pytest.raises(ValidationError):
        validate_status_transition("done", "active")  # terminal
    with pytest.raises(ValidationError):
        validate_status_transition("pending", "done")  # must go via active


def test_node_requires_evidence_or_derived_from() -> None:
    with pytest.raises(ValidationError):
        TaskNode(
            id="n", graph_id="g", kind="finding", label="l", summary="s",
            status="pending", source_refs=[], artifact_refs=[], memory_refs=[],
            created_at=_now(), updated_at=_now(),
        )
    # explicit derived_from in metadata satisfies the evidence rule
    ok = TaskNode(
        id="n", graph_id="g", kind="finding", label="l", summary="s",
        status="pending", source_refs=[], artifact_refs=[], memory_refs=[],
        created_at=_now(), updated_at=_now(),
        metadata={"derived_from": "n-parent"},
    )
    assert ok.metadata["derived_from"] == "n-parent"


def test_node_summary_rejects_raw_blob() -> None:
    with pytest.raises(ValidationError):
        TaskNode(
            id="n", graph_id="g", kind="finding", label="l",
            summary="z" * (RAW_CONTENT_MAX + 1),
            status="pending", source_refs=["stele://ns/a"], artifact_refs=[],
            memory_refs=[], created_at=_now(), updated_at=_now(),
        )
