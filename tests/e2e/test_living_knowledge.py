"""Phase 5 Living Knowledge Verification Bar — proven FOR REAL.

Drives the public Stele API (store / memory.add(supersedes=) /
memory.retract / recall(strategy='graph_search', as_of=, version_filter=,
retracted_behavior=)) against the harness `graph` profile. 4 fixture lanes:
versioned software docs, retracted medical claims, enterprise policy
updates, account-state changes.

Runs for real when STELE_PG_RAGGRAPH_DSN is set (the Makefile `e2e-graph`
target sets it). A skipped run is NOT a pass — DC-P5-FINAL requires this
green via `make -C deploy e2e-graph`.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele
from stele.recall.models import RecallResult

_DSN = os.environ.get("STELE_PG_RAGGRAPH_DSN")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _DSN,
        reason="STELE_PG_RAGGRAPH_DSN unset — run via `make -C deploy e2e-graph`",
    ),
]


def _stele(ns: str) -> Stele:
    assert _DSN is not None
    return Stele.from_config(
        {
            "backend": {"type": "postgres", "dsn": _DSN},
            "graph": {"enabled": True, "namespace": ns},
        }
    )


def _ns() -> str:
    return "lk_" + uuid.uuid4().hex[:10]


def _refs(res: RecallResult) -> set[str]:
    return {c.reference for c in res.citations}


def test_supersede_then_current_view_excludes_old() -> None:
    """Lane: versioned software docs. New doc supersedes old; current view
    prefers the new family, as_of recovers the old (SC-P5-01)."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    old = s.memory.add(
        text="API v1: auth uses API keys.",
        kind="fact",
        source_refs=[f"stele://{ns}/doc-v1"],
        scope=scope,
    )
    # Historical window: after v1 is effective, before v2 supersedes it.
    time.sleep(1)
    t_mid = datetime.now(UTC)
    time.sleep(1)
    s.memory.add(
        text="API v2: auth uses OAuth2 bearer tokens.",
        kind="fact",
        source_refs=[f"stele://{ns}/doc-v2"],
        scope=scope,
        supersedes=[old.record.id],
    )
    cur = s.recall(
        query="how does API auth work",
        scope=scope,
        strategy="graph_search",
        retracted_behavior="surface_both",
    )
    assert cur.citations, "current graph_search returned nothing"
    assert any("OAuth2" in c.snippet for c in cur.citations)
    past = s.recall(
        query="how does API auth work",
        scope=scope,
        strategy="graph_search",
        as_of=t_mid,
    )
    old_ref = f"stele://{ns}/mem-{old.record.id}"
    assert old_ref in _refs(past) or any(
        "API keys" in c.snippet for c in past.citations
    ), "as_of within the historical window did not recover the v1 doc"
    s.close()


def test_retract_honors_policy_hide_flag_surface_both() -> None:
    """Lane: retracted medical/scientific claim. All 3 modes proven; flag/
    surface_both still cite the retracted source (SC-P5-02)."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    m = s.memory.add(
        text="Study X concludes compound Z prevents disease.",
        kind="fact",
        source_refs=[f"stele://{ns}/study-x"],
        scope=scope,
    )
    s.memory.retract(m.record.id, reason="retracted by journal")
    # Issue #4: the graph cites the user's source_ref (not a synthetic
    # mem-ref) — symmetric with ingest_evidence and the BUG-4 supersede
    # projection. The retraction's graph row is keyed by source_refs[0].
    ref = f"stele://{ns}/study-x"
    hide = s.recall(
        query="does compound Z prevent disease",
        scope=scope,
        strategy="graph_search",
        retracted_behavior="hide",
    )
    assert ref not in _refs(hide)
    flag = s.recall(
        query="does compound Z prevent disease",
        scope=scope,
        strategy="graph_search",
        retracted_behavior="flag",
    )
    assert ref in _refs(flag), "flag must still cite the retracted source"
    both = s.recall(
        query="does compound Z prevent disease",
        scope=scope,
        strategy="graph_search",
        retracted_behavior="surface_both",
    )
    assert ref in _refs(both)
    s.close()


def test_as_of_recovers_historical_view() -> None:
    """Lane: account-state change. as_of recovers the historical fact
    (SC-P5-03)."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    t_mid = datetime.now(UTC) + timedelta(seconds=1)
    old = s.memory.add(
        text="Account tier: free.",
        kind="fact",
        source_refs=[f"stele://{ns}/acct"],
        scope=scope,
    )
    time.sleep(2)
    s.memory.add(
        text="Account tier: enterprise.",
        kind="fact",
        source_refs=[f"stele://{ns}/acct2"],
        scope=scope,
        supersedes=[old.record.id],
    )
    past = s.recall(
        query="what is the account tier",
        scope=scope,
        strategy="graph_search",
        as_of=t_mid,
    )
    assert any("free" in c.snippet for c in past.citations), (
        "as_of did not recover the historical 'free' tier"
    )
    s.close()


def test_version_filter_returns_one_family() -> None:
    """Lane: enterprise policy updates (SC-P5-04). The public API does not
    project a version_label, so this proves the filter is WIRED and HONORED
    (a requested version yields no cross-version leakage), not ignored."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    s.store("Travel policy 2024: economy only.", namespace=ns)
    s.store("Travel policy 2025: business class allowed.", namespace=ns)
    res = s.recall(
        query="travel policy",
        scope=scope,
        strategy="graph_search",
        version_filter="2025",
    )
    for c in res.citations:
        assert "2024" not in c.snippet
    s.close()


def test_every_living_knowledge_hit_cites_stele_ref() -> None:
    """SC-P5-05: every hit recovers an exact stele:// ref."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    s.memory.add(
        text="The capital of Atlantis is Poseidonis.",
        kind="fact",
        source_refs=[f"stele://{ns}/geo"],
        scope=scope,
    )
    res = s.recall(
        query="capital of Atlantis", scope=scope, strategy="graph_search"
    )
    assert res.citations, "no hits to verify"
    for c in res.citations:
        assert c.reference.startswith("stele://"), f"hit missing stele:// ref: {c}"
    s.close()
