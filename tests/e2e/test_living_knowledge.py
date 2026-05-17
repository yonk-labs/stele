"""Phase 5 Living Knowledge Verification Bar — placeholder.

Skip-gated on STELE_PG_RAGGRAPH_DSN until Phase 5 wires the Revisor. Written
NOW to lock the acceptance bar before implementation (inverse of the Phase 4
fiction problem). Bar (docs/sovereign-memory-system-plan.md): new evidence
supersedes old; superseded deprioritized/hidden by policy; retracted
hidden/flagged/surfaced by policy; as_of recovers history; version_filter
returns one family; every hit cites stele:// evidence.
"""

from __future__ import annotations

import os

import pytest

_RAGGRAPH_DSN = os.environ.get("STELE_PG_RAGGRAPH_DSN")

pytestmark = pytest.mark.skipif(
    not _RAGGRAPH_DSN,
    reason="STELE_PG_RAGGRAPH_DSN unset — Phase 5 not wired (see "
    "docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md)",
)


def test_supersede_then_current_view_excludes_old() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")


def test_retract_honors_policy_hide_flag_surface_both() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")


def test_as_of_recovers_historical_view() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")


def test_version_filter_returns_one_family() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")


def test_every_living_knowledge_hit_cites_stele_ref() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")
