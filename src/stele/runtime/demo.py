"""In-process demo adapter (Phase 7 first adapter — proves the loop).

No network, no LLM, CI-testable. Wires the runtime SDK into the canonical
loop:

    observe tool result -> store artifact -> update WorkGraph
    -> extract memory -> recall/pack context -> resume

This is the chosen first adapter (recon decision Q4): LangChain/MCP/OpenAI
adapters are Phase 8. It exercises the real public Stele surface +
WorkGraph + capture/packer/health/scheduling deterministically.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from stele.core.memory_record import MemoryScope
from stele.runtime.capture import (
    capture_tool_result,
    close_session_graphs,
    record_recall_used,
)
from stele.runtime.health import AdapterHealth, build_health
from stele.runtime.packer import ContextPack, ContextPolicy, pack_context
from stele.runtime.scheduling import SchedulingPolicy, SessionScheduler
from stele.workgraph.models import TaskNode, WorkGraph
from stele.workgraph.renderers import WorkGraphBundle, render_markdown

if TYPE_CHECKING:
    from stele.core.stash import Stele
    from stele.workgraph.store import WorkGraphStore

_SUMMARY_MAX = 400


def _compact(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _SUMMARY_MAX else flat[: _SUMMARY_MAX - 1] + "…"


class SteleAgentSession:
    def __init__(
        self,
        *,
        stele: Stele,
        wg_store: WorkGraphStore,
        namespace: str,
        session_id: str,
        policy: SchedulingPolicy | None = None,
    ) -> None:
        self._stele = stele
        self._wg = wg_store
        self._ns = namespace
        self._sid = session_id
        self._scope = MemoryScope(namespace=namespace, session_id=session_id)
        self._scheduler = SessionScheduler(policy=policy)
        self._graph_id = uuid.uuid4().hex
        self._nodes: list[TaskNode] = []

    def start(self, title: str) -> str:
        seed = self._stele.store(
            f"session {self._sid} start: {title}",
            namespace=self._ns,
            session_id=self._sid,
        )
        now = datetime.now(UTC)
        self._wg.create_graph(WorkGraph(
            id=self._graph_id, namespace=self._ns, session_id=self._sid,
            scope=None, title=title, status="active",
            created_at=now, updated_at=now, source_refs=[seed.reference],
        ))
        return self._graph_id

    def observe_tool(self, tool_name: str, result: str) -> TaskNode:
        """Store the raw result as a (PII-scrubbed) artifact, record a graph
        event + node, and distil a source-backed memory atom."""
        ev = capture_tool_result(
            stele=self._stele, wg_store=self._wg, graph_id=self._graph_id,
            tool_name=tool_name, result=result, namespace=self._ns,
            session_id=self._sid,
        )
        ref = ev.source_refs[0]
        # capture -> memory atom -> stele:// artifact (the invariant chain).
        # Deterministic extraction is best-effort; the explicit finding below
        # is the source-backed guarantee that recall has something to return.
        self._stele.extract.from_text(
            text=result, source_refs=[ref], scope=self._scope
        )
        fetched = self._stele.fetch(ref).content
        scrubbed_text = (
            fetched if isinstance(fetched, str)
            else fetched.decode("utf-8", "replace")
        )
        self._stele.memory.add(
            text=_compact(scrubbed_text),
            kind="fact",
            source_refs=[ref],
            scope=self._scope,
        )
        now = datetime.now(UTC)
        node = TaskNode(
            id=uuid.uuid4().hex, graph_id=self._graph_id, kind="tool_call",
            label=f"{tool_name} result",
            summary=_compact(ev.summary), status="done",
            source_refs=[ref], artifact_refs=[ref], memory_refs=[],
            created_at=now, updated_at=now,
        )
        self._wg.add_node(node)
        self._nodes.append(node)
        self._scheduler.enqueue(self._sid, node.id)
        return node

    def recall_and_pack(self, query: str, *, budget_tokens: int = 2000) -> ContextPack:
        rr = self._stele.recall(query=query, scope=self._scope)
        record_recall_used(
            wg_store=self._wg, graph_id=self._graph_id,
            recall_result=rr, namespace=self._ns,
        )
        active = self._wg.query_graph(
            namespace=self._ns, query=query, session_id=self._sid,
            active_only=True,
        )
        return pack_context(
            recall_result=rr, workgraph_nodes=active or self._nodes,
            budget_tokens=budget_tokens,
            policy=ContextPolicy(stable_claims=[f"session={self._sid}"]),
        )

    def resume(self) -> str:
        g = self._wg.get_graph(self._graph_id)
        assert g is not None
        return render_markdown(WorkGraphBundle(graph=g, nodes=self._nodes))

    def end(self) -> int:
        return close_session_graphs(
            wg_store=self._wg, namespace=self._ns, session_id=self._sid
        )

    def health(self) -> AdapterHealth:
        caps = self._stele.capabilities()
        return build_health(
            exact_store_available=True,
            memory_store_available=True,
            index_available=caps.vector_enabled,
            recall_available=True,
            pii_mode=("scrub" if self._stele.config.pii.enabled else "off"),
            pending_queue_depth=self._scheduler.queue_depth(self._sid),
        )
