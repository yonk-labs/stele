#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON=.venv/bin/python

"$PYTHON" - <<'PY'
"""Stele supersession demo: prove living-knowledge semantics at the data layer."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope

with tempfile.TemporaryDirectory() as tmp:
    stele = Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(Path(tmp) / "demo.db")}}
    )
    scope = MemoryScope(user_id="alice", namespace="demo")

    # T0: user prefers Helix
    old = stele.memory.add(
        text="user prefers Helix editor",
        kind="preference",
        source_refs=["stele://demo/onboarding-2026-01"],
        scope=scope,
    )
    print(f"T0  added memory {old.record.id[:8]}: 'user prefers Helix editor'")

    t_between = datetime.now(UTC) + timedelta(milliseconds=50)

    import time
    time.sleep(0.1)  # ensure new memory effective_from > t_between

    # T1: user switches to Zed; supersede the old preference
    new = stele.memory.add(
        text="user prefers Zed editor",
        kind="preference",
        source_refs=["stele://demo/chat-2026-05"],
        scope=scope,
        supersedes=[old.record.id],
    )
    print(f"T1  added memory {new.record.id[:8]}: 'user prefers Zed editor'")
    print(f"    superseded: {new.superseded_ids}")
    print()

    # Default search returns Zed only
    hits = stele.memory.search(MemoryQuery(query="prefers", scope=scope))
    print("DEFAULT search('prefers'):")
    for h in hits:
        print(f"  {h.id[:8]} [{h.status}] {h.text!r}")
    print()

    # as_of=t_between returns Helix
    hits = stele.memory.search(
        MemoryQuery(query="prefers", scope=scope, as_of=t_between)
    )
    print(f"AS_OF={t_between.isoformat()} search('prefers'):")
    for h in hits:
        print(f"  {h.id[:8]} [{h.status}] {h.text!r}")
    print()

    # include_superseded shows both
    hits = stele.memory.search(
        MemoryQuery(query="prefers", scope=scope, include_superseded=True)
    )
    print("INCLUDE_SUPERSEDED=True search('prefers'):")
    for h in hits:
        print(f"  {h.id[:8]} [{h.status}] {h.text!r}")
PY
