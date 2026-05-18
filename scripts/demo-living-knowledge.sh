#!/usr/bin/env bash
# Living-knowledge demo: the real pg-raggraph Revisor loop (Phase 5).
#
# Requires a Postgres backend with the [postgres-graph] extra. Point
# STELE_PG_RAGGRAPH_DSN at a pg-raggraph-ready Postgres. The bundled harness
# gives you one for free:
#
#   make -C deploy up-all
#   STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele \
#     scripts/demo-living-knowledge.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${STELE_PG_RAGGRAPH_DSN:-}" ]]; then
  echo "STELE_PG_RAGGRAPH_DSN unset — start the harness then re-run:" >&2
  echo "  make -C deploy up-all" >&2
  echo "  STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele scripts/demo-living-knowledge.sh" >&2
  exit 2
fi

PYTHON=.venv/bin/python

"$PYTHON" - <<'PY'
"""Living knowledge: supersede / retract / as_of, every hit cites stele://."""

import os
import time
import uuid
from datetime import UTC, datetime

from stele import Stele
from stele.core.memory_record import MemoryScope

ns = "lkdemo_" + uuid.uuid4().hex[:8]
stele = Stele.from_config({
    "backend": {"type": "postgres", "dsn": os.environ["STELE_PG_RAGGRAPH_DSN"]},
    "graph": {"enabled": True, "namespace": ns},
})
scope = MemoryScope(namespace=ns)


def show(label, res):
    print(f"{label}:")
    if not res.citations:
        print("  (no hits)")
    for c in res.citations:
        print(f"  {c.reference}  ::  {c.snippet[:70]!r}")
    print()


# 1. A fact, then it changes — supersede atomically
old = stele.memory.add(text="API v1: auth uses API keys.", kind="fact",
                        source_refs=[f"stele://{ns}/doc-v1"], scope=scope)
time.sleep(1)
t_mid = datetime.now(UTC)        # historical window: v1 effective, v2 not yet
time.sleep(1)
stele.memory.add(text="API v2: auth uses OAuth2 bearer tokens.", kind="fact",
                 source_refs=[f"stele://{ns}/doc-v2"], scope=scope,
                 supersedes=[old.record.id])

show("CURRENT graph_search('API auth')",
     stele.recall(query="how does API auth work", scope=scope,
                  strategy="graph_search"))
show(f"AS_OF={t_mid.isoformat()} (before the supersession)",
     stele.recall(query="how does API auth work", scope=scope,
                  strategy="graph_search", as_of=t_mid))

# 2. A claim, then retracted — policy decides what graph_search does
m = stele.memory.add(text="Study X: compound Z prevents disease.", kind="fact",
                      source_refs=[f"stele://{ns}/study-x"], scope=scope)
stele.memory.retract(m.record.id, reason="retracted by journal")

show("retracted_behavior=hide (erased from all views)",
     stele.recall(query="does compound Z prevent disease", scope=scope,
                  strategy="graph_search", retracted_behavior="hide"))
show("retracted_behavior=flag (still CITED, marked retracted)",
     stele.recall(query="does compound Z prevent disease", scope=scope,
                  strategy="graph_search", retracted_behavior="flag"))

print("Every hit above carries its exact stele:// source — that is the bar.")
PY
