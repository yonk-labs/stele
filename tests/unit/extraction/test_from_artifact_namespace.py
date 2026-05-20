"""Regression: extract.from_artifact must work in non-default namespaces.

Previously the facade hardcoded `namespace="default"` when reconstructing
the stele:// ref from a bare artifact_id, so artifacts stored in any other
namespace looked like "artifact not found" even when they existed.

Caught by examples/mcp_tour.py during Phase C documentation work; this
test pins the fix.
"""

from __future__ import annotations

from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele


def test_from_artifact_accepts_full_ref_with_non_default_namespace() -> None:
    stele = Stele.from_config({"backend": {"type": "memory"}})

    stored = stele.store("Project uses Postgres 17 in prod.", namespace="tour")
    ref = str(stored.reference)

    report = stele.extract.from_artifact(
        artifact_id=ref,
        scope=MemoryScope(namespace="tour"),
    )

    # No exception; report covers the stored text.
    assert report is not None
    assert any("Postgres" in c.text for c in report.candidates)


def test_from_artifact_still_accepts_bare_id_for_default_namespace() -> None:
    """Backwards compatibility: existing callers that pass a bare id keep working."""
    stele = Stele.from_config({"backend": {"type": "memory"}})

    stored = stele.store("Note: default namespace.")
    ref = str(stored.reference)
    bare_id = ref.rsplit("/", 1)[-1]

    report = stele.extract.from_artifact(
        artifact_id=bare_id,
        scope=MemoryScope(),
    )

    assert report is not None
