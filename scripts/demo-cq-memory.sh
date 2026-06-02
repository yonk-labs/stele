#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON=.venv/bin/python

"$PYTHON" - <<'PY'
"""Stele cq/Zep-shaped memory demo (v0.4.0).

Shows the additive memory features:
  - tripartite insight (summary / detail / action) + composed search
  - evidence that evolves: re-observation confirms instead of duplicating
  - cq lifecycle kinds (workaround -> tool_recommendation)
No network, no LLM, runs on a throwaway SQLite store.
"""

import tempfile
from pathlib import Path

from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope

with tempfile.TemporaryDirectory() as tmp:
    stele = Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(Path(tmp) / "demo.db")}}
    )
    scope = MemoryScope(user_id="alice", namespace="demo")
    ref = stele.store(content="Kafka ops note for Alice.").reference

    # 1) Tripartite insight: observation / detail / action.
    r = stele.memory.add(
        text="cooperative-sticky avoids the rebalancing storm",
        summary="consumers rebalance on every deploy",
        detail="the cooperative-sticky assignor keeps partitions put across restarts",
        action="set partition.assignment.strategy=cooperative-sticky",
        kind="fact",
        source_refs=[ref],
        scope=scope,
    )
    got = stele.memory.get(r.record.id)
    print("TRIPARTITE")
    print(f"  summary: {got.summary}")
    print(f"  action : {got.action}")
    # 'assignor' lives only in detail; composed search still finds it.
    hits = stele.memory.search(MemoryQuery(query="assignor", scope=scope))
    print(f"  search('assignor') finds it: {r.record.id in {h.id for h in hits}}")
    print()

    # 2) Evidence evolves: re-observe the same fact -> confirm, not duplicate.
    print("EVIDENCE (re-observation merges)")
    first = stele.memory.add(
        text="prod runs in us-east-1", kind="fact",
        source_refs=[ref], scope=scope, confidence=0.5,
    )
    print(f"  first : id={first.record.id[:8]} confirmations={first.record.confirmations} "
          f"confidence={first.record.confidence:.2f}")
    again = stele.memory.add(
        text="prod runs in us-east-1", kind="fact",
        source_refs=[ref], scope=scope, confidence=0.5,
    )
    print(f"  again : id={again.record.id[:8]} confirmations={again.record.confirmations} "
          f"confidence={again.record.confidence:.2f} duplicate_of={again.duplicate_of[:8]}")
    same_row = again.record.id == first.record.id
    one_row = len([m for m in stele.memory.list(scope, limit=50)
                   if m.text == "prod runs in us-east-1"]) == 1
    print(f"  same row (no twin): {same_row} | exactly one row: {one_row}")
    print()

    # 3) cq lifecycle kinds: workaround -> tool_recommendation (supersession).
    print("LIFECYCLE KINDS")
    wa = stele.memory.add(
        text="pin the transitive dep to dodge the resolver bug",
        kind="workaround", source_refs=[ref], scope=scope,
    )
    rec = stele.memory.add(
        text="use the resolver's --strict flag, which fixes it natively",
        kind="tool_recommendation", source_refs=[ref], scope=scope,
        supersedes=[wa.record.id],
    )
    print(f"  workaround {wa.record.id[:8]} superseded by "
          f"tool_recommendation {rec.record.id[:8]}: {rec.superseded_ids == [wa.record.id]}")

    stele.close()
PY
