"""ClickHouseChunkStore via chunkshop 0.4.3 clickhouse vector sink.

Gated on STELE_CLICKHOUSE_DSN + the chunkshop clickhouse sink being
importable (recon §3 T17). Skips cleanly when no live ClickHouse.
SC-008, SC-012, SC-026.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from importlib.util import find_spec
from uuid import uuid4

import pytest

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.core.exceptions import BackendError
from stele.storage.chunk_store.clickhouse import ClickHouseChunkStore

_DSN = os.environ.get("STELE_CLICKHOUSE_DSN")
pytestmark = pytest.mark.skipif(
    not _DSN or find_spec("chunkshop.sinks.clickhouse") is None,
    reason="STELE_CLICKHOUSE_DSN unset or chunkshop clickhouse sink unavailable",
)


def _artifact(text: str, artifact_id: str = "aid1") -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        reference=f"stele://default/{artifact_id}",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=len(text.split()),
        summary=text[:200],
        digest_sha256="x" * 64,
        metadata={},
        created_at=datetime.now(UTC),
    )


def _store() -> ClickHouseChunkStore:
    return ClickHouseChunkStore(
        IndexingConfig(), dsn=_DSN or "", table=f"chunks_{uuid4().hex[:8]}"
    )


def test_write_and_vector_search() -> None:
    store = _store()
    store.write(_artifact("the user strongly prefers dark mode for the dashboard"))
    hits = store.vector_search("dark mode dashboard", limit=5)
    assert hits
    assert hits[0].retrieval_mode == "vector"
    assert hits[0].chunk_id == "aid1:0"
    assert 0.0 <= hits[0].score <= 1.0
    store.close()


def test_dim_similarity_name() -> None:
    store = _store()
    assert store.name == "clickhouse"
    assert store.dim == 768  # bge-base-en-v1.5 default
    assert store.similarity == "cosine"
    store.close()


def test_pii_assertion_on_write() -> None:
    store = _store()
    with pytest.raises(BackendError, match="PII"):
        store.write(_artifact("reach the user at jane.doe@example.com"))
    store.close()
