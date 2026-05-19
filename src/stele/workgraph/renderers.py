"""WorkGraph renderers (T-RAM-004).

Pure projections — Mermaid (visual), Markdown (human + drill-down refs),
JSON (lossless round-trip). Renderers NEVER write and are NEVER
authoritative; the store is truth.
"""

from __future__ import annotations

from pydantic import BaseModel

from stele.workgraph.models import TaskEdge, TaskNode, TaskTraceEvent, WorkGraph

_LABEL_MAX = 60


class WorkGraphBundle(BaseModel):
    """A graph plus its nodes/edges/events — the renderer input + the JSON
    round-trip unit."""

    graph: WorkGraph
    nodes: list[TaskNode] = []
    edges: list[TaskEdge] = []
    events: list[TaskTraceEvent] = []


def _mermaid_label(text: str) -> str:
    flat = " ".join(text.split())          # collapse newlines/whitespace
    flat = flat.replace('"', "").replace("|", "/").replace("[", "(").replace("]", ")")
    if len(flat) > _LABEL_MAX:
        flat = flat[: _LABEL_MAX - 1] + "…"
    return flat


def render_mermaid(bundle: WorkGraphBundle) -> str:
    lines = ["flowchart TD"]
    for n in bundle.nodes:
        lines.append(f'  {n.id}["{_mermaid_label(f"{n.kind}: {n.label}")}"]')
    for e in bundle.edges:
        lines.append(f"  {e.from_node_id} -->|{e.kind}| {e.to_node_id}")
    return "\n".join(lines)


def _refs_line(*groups: list[str]) -> str:
    refs = [r for g in groups for r in g]
    return ", ".join(refs) if refs else "(derived)"


def render_markdown(bundle: WorkGraphBundle) -> str:
    g = bundle.graph
    out = [
        f"# {g.title}",
        "",
        f"- graph: `{g.id}`  ·  namespace: `{g.namespace}`  ·  "
        f"session: `{g.session_id}`  ·  status: **{g.status}**",
        f"- evidence: {_refs_line(g.source_refs)}",
        "",
        "## Nodes",
    ]
    for n in bundle.nodes:
        out.append(f"- `{n.id}` **[{n.kind}/{n.status}]** {n.label}")
        out.append(f"  - {n.summary}")
        out.append(
            f"  - refs: {_refs_line(n.source_refs, n.artifact_refs, n.memory_refs)}"
        )
    if bundle.edges:
        out.append("")
        out.append("## Edges")
        for e in bundle.edges:
            out.append(
                f"- `{e.from_node_id}` —{e.kind}→ `{e.to_node_id}` "
                f"({_refs_line(e.source_refs)})"
            )
    if bundle.events:
        out.append("")
        out.append("## Trace")
        for ev in bundle.events:
            node = f" node=`{ev.node_id}`" if ev.node_id else ""
            out.append(
                f"- `{ev.id}` [{ev.event_kind}]{node}: {ev.summary} "
                f"({_refs_line(ev.source_refs)})"
            )
    return "\n".join(out)


def render_json(bundle: WorkGraphBundle) -> str:
    return bundle.model_dump_json(indent=2)
