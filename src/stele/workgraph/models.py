"""WorkGraph domain models (T-RAM-001).

A third first-class, source-backed record type. Every node/event carries a
path back to Stele evidence; raw blobs are forbidden inline; PII scrubbing
runs at the store boundary (T-RAM-002), not here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stele.core.exceptions import ValidationError
from stele.workgraph.validators import assert_no_raw_content, validate_refs

WorkGraphStatus = Literal["active", "paused", "completed", "failed", "abandoned"]
NodeKind = Literal[
    "goal", "tool_call", "decision", "finding",
    "blocker", "artifact", "handoff", "verification",
]
NodeStatus = Literal["pending", "active", "done", "blocked", "failed", "superseded"]
EdgeKind = Literal[
    "depends_on", "caused", "derived", "supersedes",
    "verifies", "blocks", "continues",
]
EventKind = Literal[
    "message", "tool_call", "tool_result", "artifact_stored",
    "memory_extracted", "recall_used", "decision", "verification", "error",
]
_CAUSAL_EDGES = {"caused", "derived", "supersedes", "verifies"}


class WorkGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    namespace: str
    session_id: str | None = None
    scope: str | None = None
    title: str
    status: WorkGraphStatus = "active"
    created_at: datetime
    updated_at: datetime
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> WorkGraph:
        validate_refs(self.source_refs)
        assert_no_raw_content(self.title, field="title")
        return self


class TaskNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    graph_id: str
    kind: NodeKind
    label: str
    summary: str
    status: NodeStatus = "pending"
    source_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> TaskNode:
        validate_refs(self.source_refs)
        validate_refs(self.artifact_refs)
        validate_refs(self.memory_refs)
        assert_no_raw_content(self.label, field="label")
        assert_no_raw_content(self.summary, field="summary")
        has_evidence = bool(
            self.source_refs or self.artifact_refs or self.memory_refs
        ) or "derived_from" in self.metadata
        if not has_evidence:
            raise ValidationError(
                "TaskNode must cite >=1 source/artifact/memory ref or set "
                "metadata['derived_from']"
            )
        return self


class TaskEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    graph_id: str
    from_node_id: str
    to_node_id: str
    kind: EdgeKind
    source_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> TaskEdge:
        validate_refs(self.source_refs)
        return self


class TaskTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    graph_id: str
    node_id: str | None = None
    event_kind: EventKind
    summary: str
    source_refs: list[str] = Field(default_factory=list)
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> TaskTraceEvent:
        validate_refs(self.source_refs)
        assert_no_raw_content(self.summary, field="summary")
        return self
