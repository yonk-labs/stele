"""Stele.purge_namespace — full-stack integration tests for #8b.

Verifies that purge_namespace traverses all four surfaces in one call:
artifact storage, memory store, chunk index, and revisor projection.
"""

from __future__ import annotations

from pathlib import Path

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.revisor.base import NoOpRevisor, RetractedBehavior


class SpyRevisor(NoOpRevisor):
    """Captures purge_namespace calls + returns a fixed evidence count."""

    active = True

    def __init__(self, evidence_count: int = 7) -> None:
        self._evidence_count = evidence_count
        self.purged: list[str] = []

    def ingest_evidence(self, *, stele_ref, text, namespace,
                        effective_from=None, session_id=None, extra=None):
        return None

    def supersede(self, *, old_ref, new_ref, reason=None):
        return 0

    def retract(self, *, stele_ref, reason="", retracted_at=None):
        return 0

    def search_current(self, query, *, namespace, limit,
                       retracted_behavior: RetractedBehavior, version_filter):
        return []

    def search_as_of(self, query, *, namespace, limit, as_of,
                     retracted_behavior: RetractedBehavior, version_filter):
        return []

    def purge_namespace(self, namespace: str) -> int:
        self.purged.append(namespace)
        return self._evidence_count


def test_purge_namespace_drops_chunks_when_index_configured(tmp_path: Path) -> None:
    """Chunk-store delete_namespace fires when an indexer is configured."""
    # mode=sync triggers chunk-store construction on the memory backend
    # (provider stays "none"; InProcessChunkStore is the default).
    s = Stele.from_config(
        {
            "backend": {"type": "memory"},
            "indexing": {"mode": "sync"},
        }
    )
    ns = "purge_chunks_ns"
    s.store("alpha document one", namespace=ns)
    s.store("alpha document two", namespace=ns)
    # Sanity — chunks present.
    assert s._chunk_store is not None
    pre_hits = s._chunk_store.keyword_search("alpha", limit=5)
    assert pre_hits

    report = s.purge_namespace(ns)

    assert report.chunks == 2
    assert s._chunk_store.keyword_search("alpha", limit=5) == []
    s.close()


def test_purge_namespace_calls_revisor_when_active(tmp_path: Path) -> None:
    """Revisor.purge_namespace fires when a Revisor is active; the
    returned count flows into PurgeReport.graph_evidence."""
    s = Stele.from_config({"backend": {"type": "memory"}})
    spy = SpyRevisor(evidence_count=3)
    s._revisor = spy
    ns = "graph_ns"

    report = s.purge_namespace(ns)

    assert spy.purged == [ns]
    assert report.graph_evidence == 3
    s.close()


def test_purge_namespace_skips_revisor_when_inactive(tmp_path: Path) -> None:
    """NoOpRevisor is the default; graph_evidence must stay 0."""
    s = Stele.from_config({"backend": {"type": "memory"}})
    assert s.revisor.active is False  # NoOp baseline

    report = s.purge_namespace("anywhere")

    assert report.graph_evidence == 0
    s.close()


def test_purge_namespace_zero_chunks_when_no_index(tmp_path: Path) -> None:
    """Without a chunk index configured, chunks field is 0."""
    # mode=skip means no chunk_store is built at all.
    s = Stele.from_config(
        {
            "backend": {"type": "memory"},
            "indexing": {"mode": "skip"},
        }
    )
    ns = "nochunk_ns"
    s.store("hello", namespace=ns)

    report = s.purge_namespace(ns)

    assert report.chunks == 0
    s.close()


def test_purge_namespace_full_report_shape(tmp_path: Path) -> None:
    """PurgeReport carries all four surface counts in one call."""
    s = Stele.from_config(
        {
            "backend": {"type": "memory"},
            "indexing": {"mode": "sync"},
        }
    )
    spy = SpyRevisor(evidence_count=5)
    s._revisor = spy
    ns = "full_ns"
    s.store("artifact one", namespace=ns)
    s.memory.add(
        text="fact one",
        kind="fact",
        source_refs=[f"stele://{ns}/a"],
        scope=MemoryScope(namespace=ns),
    )

    report = s.purge_namespace(ns)

    assert report.artifacts == 1
    assert report.memories == 1
    assert report.chunks == 1
    assert report.graph_evidence == 5
    s.close()
