"""PostgresChunkStore via chunkshop 0.4.3 pg/pgvector sink.

Runs for real when STELE_PG_DSN is set (it is in CI/dev). Unique table
per test so the shared db has no cross-test collisions. SC-008, SC-010,
SC-012, SC-026.
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
from stele.storage.chunk_store.postgres import PostgresChunkStore

_PG_DSN = os.environ.get("STELE_PG_DSN")
pytestmark = pytest.mark.skipif(not _PG_DSN, reason="STELE_PG_DSN unset")


def _artifact(text: str, artifact_id: str = "aid1", ns: str = "default") -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        reference=f"stele://{ns}/{artifact_id}",
        namespace=ns,
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


def _store() -> PostgresChunkStore:
    table = f"chunks_{uuid4().hex[:8]}"
    return PostgresChunkStore(IndexingConfig(), dsn=_PG_DSN or "", table=table)


def test_write_and_vector_search() -> None:
    store = _store()
    n = store.write(_artifact("the user strongly prefers dark mode for the analytics dashboard"))
    assert n >= 1
    hits = store.vector_search("dark mode dashboard", limit=5)
    assert hits
    top = hits[0]
    assert top.retrieval_mode == "vector"
    assert top.chunk_id == "aid1:0"
    assert 0.0 <= top.score <= 1.0
    assert "dark mode" in top.text
    for h in hits:
        assert type(h).__module__.startswith("stele.")
    store.close()


def test_keyword_search_is_stele_local() -> None:
    store = _store()
    store.write(_artifact("the migration deadline is the thirtieth of june"))
    hits = store.keyword_search("migration", limit=5)
    assert hits
    assert hits[0].retrieval_mode == "keyword"
    store.close()


def test_reference_filter() -> None:
    store = _store()
    store.write(_artifact("apple banana cherry vector content", artifact_id="aid_a"))
    store.write(_artifact("apple banana cherry vector content", artifact_id="aid_b"))
    hits = store.vector_search("apple banana", limit=5, reference="stele://default/aid_a")
    assert hits
    assert {h.reference for h in hits} == {"stele://default/aid_a"}
    store.close()


def test_delete() -> None:
    store = _store()
    store.write(_artifact("apple banana cherry", artifact_id="aid_a"))
    store.delete("stele://default/aid_a")
    assert store.vector_search("apple", limit=5) == []
    store.close()


def test_dim_similarity_name() -> None:
    store = _store()
    assert store.name == "postgres"
    assert store.dim == 384
    assert store.similarity == "cosine"
    store.close()


def test_pii_assertion_on_write() -> None:
    store = _store()
    with pytest.raises(BackendError, match="PII"):
        store.write(_artifact("ping the user at jane.doe@example.com now"))
    store.close()


@pytest.mark.skipif(
    find_spec("chunkshop") is not None,
    reason="chunkshop installed — OptionalDependencyError path only when absent",
)
def test_missing_chunkshop_raises() -> None:
    from stele.core.exceptions import OptionalDependencyError

    with pytest.raises(OptionalDependencyError, match="chunkshop"):
        PostgresChunkStore(IndexingConfig(), dsn=_PG_DSN or "")
