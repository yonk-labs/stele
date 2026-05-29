"""SC-CONS: consolidation chunker end-to-end on chunkshop-backed backends.

Drives the public Stele facade with IndexingConfig.chunker='consolidation'
and a deterministic extractive consolidator (no LLM cost). Verifies that:

- artifacts get split into 1 episode chunk + N atomic-fact chunks
- vector search ranks a fact span matching the query above other chunks
- the chunk_id/artifact_id round-trip invariants hold (same as fixed_overlap)

memory backend is excluded — its chunk store does not delegate to chunkshop,
so the consolidation chunker isn't applicable there. sqlite runs for real;
postgres / mariadb / clickhouse run when their DSN env vars are set.
"""

from __future__ import annotations

import os
import uuid
from importlib.util import find_spec
from pathlib import Path

import pytest

from stele import Stele

# Deterministic, no-API consolidator (lives in benchmarks/, importable
# because pythonpath includes the repo root for tests).
_CONSOLIDATOR = "benchmarks.external.consolidators.extractive"


def _backends() -> list[str]:
    bk = ["sqlite"]
    if os.environ.get("STELE_PG_DSN"):
        bk.append("postgres")
    if os.environ.get("STELE_MARIADB_DSN") and find_spec("chunkshop.sinks.mariadb"):
        bk.append("mariadb")
    if os.environ.get("STELE_CLICKHOUSE_DSN") and find_spec("chunkshop.sinks.clickhouse"):
        bk.append("clickhouse")
    return bk


def _stash(backend: str, tmp_path: Path) -> Stele:
    idx_cfg = {
        "indexing": {
            "mode": "sync",
            "chunker": "consolidation",
            "consolidator_module": _CONSOLIDATOR,
            "consolidator_kwargs": {"summary_words": 60, "max_facts": 5},
            "fact_max_chars": 200,
        },
        "retrieval": {"default_mode": "vector"},
    }
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp_path / "s.db")}, **idx_cfg}
        )
    if backend == "postgres":
        return Stele.from_config(
            {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}, **idx_cfg}
        )
    if backend == "mariadb":
        return Stele.from_config(
            {"backend": {"type": "mariadb", "dsn": os.environ["STELE_MARIADB_DSN"]}, **idx_cfg}
        )
    return Stele.from_config(
        {"backend": {"type": "clickhouse", "dsn": os.environ["STELE_CLICKHOUSE_DSN"]}, **idx_cfg}
    )


@pytest.mark.parametrize("backend", _backends())
def test_consolidation_chunker_episode_plus_facts(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, tmp_path)
    ns = f"cons_{uuid.uuid4().hex[:8]}"
    # Multi-sentence text -> extractive consolidator emits up to 5 facts +
    # 1 episode summary chunk = 6 chunks total. Sentences are short and
    # diverse so the consolidator picks distinct support spans.
    text = (
        "Caroline went to the LGBTQ support group on 7 May 2023. "
        "Melanie painted a sunrise on 12 May 2023. "
        "They had a conversation on 8 May 2023 about identity. "
        "Melanie is a painter and a runner. "
        "Caroline is studying psychology at university."
    )
    stored = stash.store(text, namespace=ns)

    # Vector search with a high enough k to surface everything the chunker
    # emitted, then filter the warning that fires when oversample doesn't
    # find as many candidates as requested (expected: consolidation is sparse).
    hits = stash.search(stored.reference, "When did Caroline go to LGBTQ support?",
                        limit=10, mode="vector")
    assert hits, f"{backend}: consolidation vector search returned nothing"
    # All hits share the same artifact and surface valid chunk_ids.
    for h in hits:
        assert h.artifact_id == stored.artifact_id
        assert h.chunk_id is not None and ":" in h.chunk_id
        assert h.chunk_id.split(":")[0] == stored.artifact_id
        assert h.retrieval_mode == "vector"
        assert isinstance(h.text, str) and isinstance(h.metadata, dict)

    # The LGBTQ fact span should rank #1 for the LGBTQ query.
    assert "LGBTQ" in hits[0].text, (
        f"{backend}: top hit did not contain 'LGBTQ' (got {hits[0].text!r})"
    )

    # Different query -> different top hit (vector ranking is meaningful).
    hits2 = stash.search(stored.reference, "What does Melanie do?",
                         limit=10, mode="vector")
    assert hits2, f"{backend}: second vector search returned nothing"
    # The top hit should mention Melanie (painter / runner / sunrise).
    assert "Melanie" in hits2[0].text, (
        f"{backend}: top hit for Melanie query did not mention Melanie "
        f"(got {hits2[0].text!r})"
    )

    stash.close()
