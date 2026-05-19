"""Artifact→WorkGraph capture (T-RAM-005).

Turns observed runtime events into source-backed graph events. Large tool
payloads become Stele artifacts FIRST; the graph event carries only refs +
a compact summary (never the raw payload). Adapter code calls these; core
Stele only defines models/stores.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from stele.workgraph.models import TaskTraceEvent

if TYPE_CHECKING:
    from stele.core.stash import Stele
    from stele.recall.models import RecallResult
    from stele.workgraph.store import WorkGraphStore

_SUMMARY_MAX = 480  # < RAW_CONTENT_MAX (512); keeps the event compact


def _compact(text: str, limit: int = _SUMMARY_MAX) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def capture_tool_result(
    *,
    stele: Stele,
    wg_store: WorkGraphStore,
    graph_id: str,
    tool_name: str,
    result: str,
    namespace: str,
    session_id: str | None = None,
    threshold: int = 512,
) -> TaskTraceEvent:
    """Store the result as a Stele artifact, then record a graph event with
    only the ref + a compact summary. The artifact carries the PII/raw
    policy; the graph never holds the raw payload."""
    stored = stele.store(result, namespace=namespace, session_id=session_id)
    now = datetime.now(UTC)
    ev = TaskTraceEvent(
        id=uuid.uuid4().hex,
        graph_id=graph_id,
        node_id=None,
        event_kind="tool_result",
        summary=f"{tool_name}: {_compact(stored.summary)}",
        source_refs=[stored.reference],
        timestamp=now,
        metadata={
            "tool": tool_name,
            "bytes": len(result),
            "above_threshold": len(result) > threshold,
            "token_savings": stored.estimated_token_savings,
        },
    )
    return wg_store.add_event(ev)


def record_recall_used(
    *,
    wg_store: WorkGraphStore,
    graph_id: str,
    recall_result: RecallResult,
    namespace: str,
) -> TaskTraceEvent:
    """Record which memory/artifact refs were injected into context."""
    del namespace  # graph_id already scopes it; kept for adapter symmetry
    ev = TaskTraceEvent(
        id=uuid.uuid4().hex,
        graph_id=graph_id,
        node_id=None,
        event_kind="recall_used",
        summary=(
            f"recall[{recall_result.strategy_used}] "
            f"{len(recall_result.citations)} citations"
        ),
        source_refs=list(recall_result.source_refs),
        timestamp=datetime.now(UTC),
        metadata={"strategy": recall_result.strategy_used},
    )
    return wg_store.add_event(ev)


def close_session_graphs(
    *,
    wg_store: WorkGraphStore,
    namespace: str,
    session_id: str,
    status: str = "completed",
) -> int:
    """Close/pause only the active graphs for this session. Idempotent:
    re-running finds nothing active and returns 0."""
    active = wg_store.list_graphs(
        namespace=namespace, session_id=session_id, status="active"
    )
    for g in active:
        wg_store.update_graph(g.id, {"status": status})
    return len(active)
