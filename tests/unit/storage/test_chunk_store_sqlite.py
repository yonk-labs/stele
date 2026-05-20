"""SQLiteChunkStore via chunkshop 0.4.3 sink — runs for real (model cached).

SC-008 (Protocol surface), SC-010 (OptionalDependencyError), SC-012
(vector top-K), SC-026 (PII boundary assertion).
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path

import pytest

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.core.exceptions import BackendError
from stele.storage.chunk_store.sqlite import SQLiteChunkStore


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


def _store(tmp_path: Path) -> SQLiteChunkStore:
    return SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "chunks.db"))


def test_write_and_vector_search(tmp_path: Path) -> None:
    store = _store(tmp_path)
    n = store.write(_artifact("the user strongly prefers dark mode for the analytics dashboard"))
    assert n >= 1
    hits = store.vector_search("dark mode dashboard", limit=5)
    assert hits, "real fastembed vector search should return the indexed chunk"
    top = hits[0]
    assert top.retrieval_mode == "vector"
    assert top.chunk_id == "aid1:0"
    assert 0.0 <= top.score <= 1.0
    assert "dark mode" in top.text  # hydrated from locally-retained text
    # No chunkshop-native object leaks into the SearchHit.
    assert type(store).__module__.startswith("stele.")
    for h in hits:
        assert type(h).__module__.startswith("stele.")
        assert isinstance(h.text, str) and isinstance(h.metadata, dict)
    store.close()


def test_keyword_search_is_stele_local(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write(_artifact("the migration deadline is the thirtieth of june"))
    hits = store.keyword_search("migration", limit=5)
    assert hits
    assert "migration" in hits[0].text.lower()
    assert hits[0].retrieval_mode == "keyword"
    store.close()


def test_reference_filter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write(_artifact("apple banana cherry vector content", artifact_id="aid_a"))
    store.write(_artifact("apple banana cherry vector content", artifact_id="aid_b"))
    hits = store.vector_search("apple banana", limit=5, reference="stele://default/aid_a")
    assert hits
    assert {h.reference for h in hits} == {"stele://default/aid_a"}
    store.close()


def test_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write(_artifact("apple banana cherry", artifact_id="aid_a"))
    store.delete("stele://default/aid_a")
    assert store.vector_search("apple", limit=5) == []
    store.close()


def test_dim_similarity_name(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.name == "sqlite"
    assert store.dim == 384
    assert store.similarity == "cosine"
    assert len(store.embed("probe")) == 384
    store.close()


def test_pii_assertion_on_write(tmp_path: Path) -> None:
    """SC-026: unscrubbed PII reaching the chunk store fails loud."""
    store = _store(tmp_path)
    with pytest.raises(BackendError, match="PII"):
        store.write(_artifact("contact the user at jane.doe@example.com immediately"))
    store.close()


def test_protocol_surface(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for attr in ("write", "delete", "keyword_search", "vector_search", "embed", "close"):
        assert callable(getattr(store, attr))
    store.close()


@pytest.mark.skipif(
    find_spec("chunkshop") is not None,
    reason="chunkshop installed — OptionalDependencyError path only when absent",
)
def test_missing_chunkshop_raises(tmp_path: Path) -> None:
    from stele.core.exceptions import OptionalDependencyError

    with pytest.raises(OptionalDependencyError, match="chunkshop"):
        SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "x.db"))


def test_delete_namespace_drops_target_only(tmp_path: Path) -> None:
    """Per #8b — chunkshop-backed chunk store must purge by namespace."""
    store = SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "ns.db"))
    store.write(_artifact("alpha widget alpha", artifact_id="aa", ns="ns_a"))
    store.write(_artifact("beta widget beta", artifact_id="ba", ns="ns_b"))

    removed = store.delete_namespace("ns_a")

    assert removed == 1
    # ns_b survives.
    survivors = store.vector_search("widget", limit=5)
    assert survivors and all(h.reference == "stele://ns_b/ba" for h in survivors)
    store.close()


def test_optionaldep_when_chunkshop_absent_simulated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-010 (passing, not skipped): simulate chunkshop missing via
    find_spec -> OptionalDependencyError with the pip hint."""
    from stele.core.exceptions import OptionalDependencyError
    from stele.storage.chunk_store import _chunkshop_base

    monkeypatch.setattr(_chunkshop_base, "find_spec", lambda name: None)
    with pytest.raises(OptionalDependencyError, match=r"chunkshop.*stele-core\[chunkshop\]"):
        SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "x.db"))
