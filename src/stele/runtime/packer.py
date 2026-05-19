"""Context packer (T-RAM-006).

Packages recall + WorkGraph state into separate stable / dynamic sections
with recovery handles, under a hard token budget. Pure: never mutates the
recall result, the WorkGraph, or stored artifacts. Budget overflow is
deterministic and visible in ``omitted``. Every packed claim carries a ref.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from pydantic import BaseModel, Field

from stele.core.artifact import estimate_tokens

if TYPE_CHECKING:
    from stele.recall.models import RecallResult
    from stele.workgraph.models import TaskNode

# Lower = packed earlier and dropped later. Blockers/decisions beat
# in-progress, which beats finished work (spec budget rule).
_STATUS_PRIORITY = {"blocked": 0, "failed": 0, "active": 1, "pending": 2}
_TERMINAL = {"done", "superseded", "abandoned"}


class ContextPolicy(BaseModel):
    stable_claims: list[str] = Field(default_factory=list)
    max_workgraph_nodes: int = 10
    max_citations: int = 50


class ContextPack(NamedTuple):
    stable_context: str
    dynamic_context: str
    recovery_handles: list[str]
    token_estimate: int
    omitted: list[str]


def _flat(text: str) -> str:
    """One claim == one line. Collapse embedded newlines/whitespace so the
    'every packed line carries a ref' invariant holds physically."""
    return " ".join(text.split())


def _node_ref(node: TaskNode) -> str | None:
    for group in (node.source_refs, node.artifact_refs, node.memory_refs):
        if group:
            return group[0]
    return None


def _node_rank(node: TaskNode) -> int:
    if node.status in _TERMINAL:
        return 9
    base = _STATUS_PRIORITY.get(node.status, 5)
    if node.kind in ("blocker", "decision"):
        base = min(base, 0)
    return base


def pack_context(
    *,
    recall_result: RecallResult,
    workgraph_nodes: list[TaskNode] | None = None,
    budget_tokens: int,
    policy: ContextPolicy | None = None,
) -> ContextPack:
    policy = policy or ContextPolicy()
    stable = "\n".join(policy.stable_claims)

    # Ordered candidate (line, handle, omit_id) tuples — citations first
    # (by score desc), then WorkGraph nodes by rank then recency.
    candidates: list[tuple[str, str, str]] = []
    for c in sorted(
        recall_result.citations, key=lambda c: c.score, reverse=True
    )[: policy.max_citations]:
        candidates.append(
            (f"- {_flat(c.snippet)} [{c.reference}]", c.reference,
             f"citation:{c.id}")
        )

    nodes = list(workgraph_nodes or [])
    nodes.sort(key=lambda n: (_node_rank(n), -n.updated_at.timestamp()))
    omitted: list[str] = []
    kept_nodes = 0
    for n in nodes:
        ref = _node_ref(n)
        if ref is None:
            omitted.append(f"node:{n.id}:no-ref")
            continue
        if kept_nodes >= policy.max_workgraph_nodes:
            omitted.append(f"node:{n.id}")
            continue
        kept_nodes += 1
        candidates.append((
            f"- [{n.kind}/{n.status}] {_flat(n.label)}: {_flat(n.summary)} [{ref}]",
            ref,
            f"node:{n.id}",
        ))

    dynamic_lines: list[str] = []
    handles: list[str] = []
    used = 0
    for line, handle, omit_id in candidates:
        cost = estimate_tokens(line)
        if used + cost > budget_tokens:
            omitted.append(omit_id)
            continue
        used += cost
        dynamic_lines.append(line)
        if handle not in handles:
            handles.append(handle)

    dynamic = "\n".join(dynamic_lines)
    return ContextPack(
        stable_context=stable,
        dynamic_context=dynamic,
        recovery_handles=handles,
        token_estimate=estimate_tokens(f"{stable}\n{dynamic}"),
        omitted=omitted,
    )
