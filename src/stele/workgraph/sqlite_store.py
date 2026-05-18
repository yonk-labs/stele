"""SQLite WorkGraph store (T-RAM-003).

Durable backend that passes the SAME contract as the in-memory store, plus
real `as_of` (graph-existence-as-of: a graph is visible only if it existed
at/at-or-before the timestamp — deterministic, no node-level history, which
is out of T-RAM-003 scope). Records are stored as validated-model JSON with
indexed filter columns. Deletion policy: explicit row delete is not exposed;
graphs reach a terminal `status` (tombstone via status, consistent with the
rest of Stele's soft-state model).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stele.core.exceptions import ArtifactNotFound, CapabilityError
from stele.workgraph.models import TaskEdge, TaskNode, TaskTraceEvent, WorkGraph
from stele.workgraph.validators import validate_status_transition

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wg_graphs (
  id TEXT PRIMARY KEY, namespace TEXT NOT NULL, session_id TEXT,
  status TEXT NOT NULL, created_ts REAL NOT NULL, doc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_wg_graphs_ns ON wg_graphs(namespace, session_id, status);
CREATE TABLE IF NOT EXISTS wg_nodes (
  id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, created_ts REAL NOT NULL,
  doc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_wg_nodes_g ON wg_nodes(graph_id);
CREATE TABLE IF NOT EXISTS wg_edges (
  id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, doc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wg_events (
  id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, doc TEXT NOT NULL
);
"""


class SQLiteWorkGraphStore:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def create_graph(self, graph: WorkGraph) -> WorkGraph:
        self.conn.execute(
            "INSERT OR REPLACE INTO wg_graphs "
            "(id, namespace, session_id, status, created_ts, doc) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (graph.id, graph.namespace, graph.session_id, graph.status,
             graph.created_at.timestamp(), graph.model_dump_json()),
        )
        self.conn.commit()
        return graph

    def get_graph(
        self, graph_id: str, *, as_of: datetime | None = None
    ) -> WorkGraph | None:
        if as_of is not None:
            if as_of.tzinfo is None:
                raise CapabilityError("WorkGraph as_of must be timezone-aware")
            row = self.conn.execute(
                "SELECT doc FROM wg_graphs WHERE id=? AND created_ts<=?",
                (graph_id, as_of.timestamp()),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT doc FROM wg_graphs WHERE id=?", (graph_id,)
            ).fetchone()
        return WorkGraph.model_validate_json(row[0]) if row else None

    def list_graphs(
        self,
        *,
        namespace: str,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[WorkGraph]:
        sql = ["SELECT doc FROM wg_graphs WHERE namespace=?"]
        params: list[Any] = [namespace]
        if session_id is not None:
            sql.append("AND session_id=?")
            params.append(session_id)
        if status is not None:
            sql.append("AND status=?")
            params.append(status)
        sql.append("ORDER BY created_ts, id LIMIT ?")
        params.append(limit)
        rows = self.conn.execute(" ".join(sql), params).fetchall()
        return [WorkGraph.model_validate_json(r[0]) for r in rows]

    def add_node(self, node: TaskNode) -> TaskNode:
        self.conn.execute(
            "INSERT OR REPLACE INTO wg_nodes (id, graph_id, created_ts, doc) "
            "VALUES (?, ?, ?, ?)",
            (node.id, node.graph_id, node.created_at.timestamp(),
             node.model_dump_json()),
        )
        self.conn.commit()
        return node

    def update_node(self, node_id: str, patch: Mapping[str, Any]) -> TaskNode:
        row = self.conn.execute(
            "SELECT doc FROM wg_nodes WHERE id=?", (node_id,)
        ).fetchone()
        if row is None:
            raise ArtifactNotFound(f"WorkGraph node not found: {node_id}")
        existing = TaskNode.model_validate_json(row[0])
        if "status" in patch and patch["status"] != existing.status:
            validate_status_transition(existing.status, str(patch["status"]))
        merged = existing.model_dump()
        merged.update(patch)
        merged["updated_at"] = datetime.now(UTC)
        updated = TaskNode(**merged)
        return self.add_node(updated)

    def add_edge(self, edge: TaskEdge) -> TaskEdge:
        self.conn.execute(
            "INSERT OR REPLACE INTO wg_edges (id, graph_id, doc) VALUES (?, ?, ?)",
            (edge.id, edge.graph_id, edge.model_dump_json()),
        )
        self.conn.commit()
        return edge

    def add_event(self, event: TaskTraceEvent) -> TaskTraceEvent:
        self.conn.execute(
            "INSERT OR REPLACE INTO wg_events (id, graph_id, doc) VALUES (?, ?, ?)",
            (event.id, event.graph_id, event.model_dump_json()),
        )
        self.conn.commit()
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
        sql = [
            "SELECT n.doc FROM wg_nodes n JOIN wg_graphs g "
            "ON n.graph_id = g.id WHERE g.namespace=?"
        ]
        params: list[Any] = [namespace]
        if session_id is not None:
            sql.append("AND g.session_id=?")
            params.append(session_id)
        if active_only:
            sql.append("AND g.status='active'")
        sql.append("ORDER BY n.created_ts, n.id")
        rows = self.conn.execute(" ".join(sql), params).fetchall()
        q = query.lower()
        hits: list[TaskNode] = []
        for r in rows:
            n = TaskNode.model_validate_json(r[0])
            if q in n.label.lower() or q in n.summary.lower():
                hits.append(n)
        return hits[:limit]

    def close(self) -> None:
        self.conn.close()
