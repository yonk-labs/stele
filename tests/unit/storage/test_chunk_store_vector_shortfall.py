"""Vector recall-shortfall warning — mirrors pg-raggraph's vector_first guard.

The helper fires WARNING on `stele.retrieval` when vector_search returns
fewer rows than `limit`. Verifies the silent-failure mode is now observable.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.storage.chunk_store._chunkshop_base import _warn_vector_recall_shortfall
from stele.storage.chunk_store.sqlite import SQLiteChunkStore

LOGGER_NAME = "stele.retrieval"


def _artifact(text: str, artifact_id: str = "aid1", ns: str = "default") -> ArtifactRecord:
    from datetime import UTC, datetime

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


def test_helper_fires_warning_with_operator_actionable_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    _warn_vector_recall_shortfall(
        rows_returned=2,
        top_k_requested=10,
        seed_size=10,
        has_reference_filter=False,
    )
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.levelno == logging.WARNING
    assert rec.name == LOGGER_NAME
    msg = rec.getMessage()
    assert "returned=2" in msg
    assert "requested=10" in msg
    assert "seed_size=10" in msg
    assert "vector-recall-shortfall" in msg  # cookbook anchor


def test_helper_extreme_shortfall_renders(caplog: pytest.LogCaptureFixture) -> None:
    """rows_returned=0 must still render without crashing (pg-raggraph parity)."""
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    _warn_vector_recall_shortfall(
        rows_returned=0,
        top_k_requested=5,
        seed_size=5,
        has_reference_filter=True,
    )
    assert "returned=0" in caplog.records[0].getMessage()


def test_helper_mentions_reference_filter_when_set(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    _warn_vector_recall_shortfall(
        rows_returned=1,
        top_k_requested=10,
        seed_size=42,
        has_reference_filter=True,
    )
    msg = caplog.records[0].getMessage()
    assert "has_reference_filter=True" in msg
    assert "broaden the reference filter" in msg


def test_vector_search_fires_warning_on_shortfall(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """End-to-end: a single-chunk corpus + limit=5 must warn."""
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    store = SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "c.db"))
    store.write(_artifact("the user prefers dark mode for the analytics dashboard"))
    hits = store.vector_search("dark mode", limit=5)
    assert 0 < len(hits) < 5
    shortfall = [r for r in caplog.records if "vector recall shortfall" in r.getMessage()]
    assert len(shortfall) == 1
    store.close()


def test_vector_search_no_warning_when_full(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    store = SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "c.db"))
    store.write(_artifact("alpha beta gamma delta epsilon zeta eta theta"))
    hits = store.vector_search("alpha", limit=1)
    assert len(hits) == 1
    shortfall = [r for r in caplog.records if "vector recall shortfall" in r.getMessage()]
    assert shortfall == []
    store.close()
