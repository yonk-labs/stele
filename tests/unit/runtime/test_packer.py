from datetime import UTC, datetime

from stele.recall.models import Citation, RecallResult, RecallStats
from stele.runtime.packer import ContextPolicy, pack_context
from stele.workgraph.models import NodeKind, NodeStatus, TaskNode


def _rr(n: int = 3) -> RecallResult:
    cites = [
        Citation(kind="memory", id=f"m{i}", reference=f"stele://ns/m{i}",
                 score=1.0 - i * 0.1, snippet=f"fact number {i}")
        for i in range(n)
    ]
    return RecallResult(
        strategy_used="memory_search", context="\n".join(c.snippet for c in cites),
        citations=cites, escalations=[],
        source_refs=[c.reference for c in cites], stats=RecallStats(),
    )


def _node(nid: str, status: NodeStatus, kind: NodeKind = "finding") -> TaskNode:
    now = datetime.now(UTC)
    return TaskNode(
        id=nid, graph_id="g1", kind=kind, label=f"{kind} {nid}",
        summary=f"summary {nid}", status=status,
        source_refs=[f"stele://ns/{nid}"], artifact_refs=[], memory_refs=[],
        created_at=now, updated_at=now,
    )


def test_stable_and_dynamic_are_separate_and_ref_backed() -> None:
    rr = _rr()
    pack = pack_context(
        recall_result=rr, workgraph_nodes=[_node("n1", "blocked")],
        budget_tokens=10_000,
        policy=ContextPolicy(stable_claims=["Project: Stele", "Team: core"]),
    )
    assert "Project: Stele" in pack.stable_context
    assert "Project: Stele" not in pack.dynamic_context
    assert "fact number 0" in pack.dynamic_context
    # every dynamic line carries a stele:// ref
    for line in [ln for ln in pack.dynamic_context.splitlines() if ln.strip()]:
        assert "stele://" in line
    assert any(h.startswith("stele://") for h in pack.recovery_handles)
    assert pack.token_estimate > 0


def test_inputs_not_mutated() -> None:
    rr = _rr()
    before = [c.snippet for c in rr.citations]
    pack_context(recall_result=rr, workgraph_nodes=None, budget_tokens=10_000)
    assert [c.snippet for c in rr.citations] == before


def test_budget_overflow_is_deterministic_and_visible() -> None:
    rr = _rr(8)
    p1 = pack_context(recall_result=rr, workgraph_nodes=None, budget_tokens=12)
    p2 = pack_context(recall_result=rr, workgraph_nodes=None, budget_tokens=12)
    assert p1.omitted == p2.omitted and p1.omitted  # deterministic + non-empty
    assert p1.dynamic_context == p2.dynamic_context


def test_blockers_prioritized_and_node_cap() -> None:
    nodes = [
        _node("done1", "done"),
        _node("blk1", "blocked", "blocker"),
        _node("act1", "active"),
        _node("done2", "done"),
    ]
    pack = pack_context(
        recall_result=_rr(0), workgraph_nodes=nodes, budget_tokens=10_000,
        policy=ContextPolicy(max_workgraph_nodes=2),
    )
    # cap honored: only 2 nodes packed, the rest omitted
    packed_ids = [n for n in ("blk1", "act1", "done1", "done2")
                  if n in pack.dynamic_context]
    assert len(packed_ids) == 2
    assert "blk1" in pack.dynamic_context  # blocker prioritized
    assert any("done" in o for o in pack.omitted)
