"""SC-015: vector + hybrid retrieval end-to-end across all 5 backends.

memory + sqlite run for real (fastembed model cached). postgres runs when
STELE_PG_DSN is set. mariadb/clickhouse are gated on their DSN env AND the
chunkshop sink being importable (recon §3 T25). No false chunkshop skips.
"""

from __future__ import annotations

import os
import re
import uuid
from importlib.util import find_spec
from pathlib import Path

import pytest

from stele import Stele

_CHUNK_ID = re.compile(r"^[0-9a-f]+:\d+$")


def _backends() -> list[str]:
    bk = ["memory", "sqlite"]
    if os.environ.get("STELE_PG_DSN"):
        bk.append("postgres")
    if os.environ.get("STELE_MARIADB_DSN") and find_spec("chunkshop.sinks.mariadb"):
        bk.append("mariadb")
    if os.environ.get("STELE_CLICKHOUSE_DSN") and find_spec("chunkshop.sinks.clickhouse"):
        bk.append("clickhouse")
    return bk


def _stash(backend: str, tmp_path: Path) -> Stele:
    idx = {"indexing": {"mode": "sync"}}
    if backend == "memory":
        return Stele.from_config({"backend": {"type": "memory"}, **idx})
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp_path / "s.db")}, **idx}
        )
    if backend == "postgres":
        return Stele.from_config(
            {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}, **idx}
        )
    if backend == "mariadb":
        return Stele.from_config(
            {"backend": {"type": "mariadb", "dsn": os.environ["STELE_MARIADB_DSN"]}, **idx}
        )
    return Stele.from_config(
        {"backend": {"type": "clickhouse", "dsn": os.environ["STELE_CLICKHOUSE_DSN"]}, **idx}
    )


@pytest.mark.parametrize("backend", _backends())
def test_vector_retrieval_end_to_end(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, tmp_path)
    ns = f"vec_{uuid.uuid4().hex[:8]}"
    stored = stash.store(
        "The incident root cause was a missing database index on the orders table.",
        namespace=ns,
    )
    hits = stash.search(stored.reference, "database index", mode="vector")
    assert hits, f"{backend}: vector search returned nothing"
    top = hits[0]
    assert top.retrieval_mode == "vector"
    # chunk_id == {artifact_id}:{ordinal} round-trips, no native id leaks.
    assert top.chunk_id is not None and _CHUNK_ID.match(top.chunk_id)
    assert top.chunk_id.split(":")[0] == stored.artifact_id
    assert top.artifact_id == stored.artifact_id
    # No chunkshop-native object escapes into the public hit.
    assert type(top).__module__.startswith("stele.")
    assert isinstance(top.text, str) and isinstance(top.metadata, dict)
    stash.close()


@pytest.mark.parametrize("backend", _backends())
def test_hybrid_retrieval_end_to_end(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, tmp_path)
    ns = f"hyb_{uuid.uuid4().hex[:8]}"
    stored = stash.store(
        "Rebuild the postgres index to fix the slow deployment pipeline.",
        namespace=ns,
    )
    hits = stash.search(stored.reference, "postgres index", mode="hybrid")
    assert hits, f"{backend}: hybrid search returned nothing"
    assert hits[0].retrieval_mode == "hybrid"
    assert hits[0].chunk_id is not None and _CHUNK_ID.match(hits[0].chunk_id)
    stash.close()
