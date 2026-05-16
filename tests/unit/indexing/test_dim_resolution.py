"""Tests for the dim + similarity resolution cascade (SC-006, SC-007)."""

from __future__ import annotations

import json
from pathlib import Path

from stele.core.config import IndexingConfig
from stele.indexing.dim_resolution import resolve_dim_and_similarity
from stele.storage.chunk_store.memory import InProcessChunkStore


def test_bakeoff_file_wins(tmp_path: Path) -> None:
    """SC-005/cascade: bakeoff_path set + loads -> source='bakeoff_file'."""
    bo = tmp_path / "bo.json"
    bo.write_text(
        json.dumps(
            {
                "chunker": {"type": "fixed_overlap", "params": {"window_words": 300}},
                "embedder": {"name": "bge-large", "dim": 1024},
                "similarity": "ip",
            }
        ),
        encoding="utf-8",
    )
    cfg = IndexingConfig(bakeoff_path=str(bo))
    summary = resolve_dim_and_similarity(cfg, store=InProcessChunkStore(cfg))
    assert summary.source == "bakeoff_file"
    assert summary.similarity == "ip"
    assert summary.embedder is not None and summary.embedder.dim == 1024
    assert summary.chunker is not None and summary.chunker.type == "fixed_overlap"
    assert summary.file_path == str(bo)


def test_auto_detected_from_store_probe() -> None:
    """SC-006: no bakeoff -> probe store.embed -> source='auto_detected'."""
    cfg = IndexingConfig()  # no bakeoff_path
    store = InProcessChunkStore(cfg)
    summary = resolve_dim_and_similarity(cfg, store=store)
    assert summary.source == "auto_detected"
    assert summary.embedder is not None
    assert summary.embedder.dim == len(store.embed("__stele_probe__")) == 384
    assert summary.similarity == "cosine"  # from config.similarity default
    assert summary.chunker is None


def test_auto_detected_honors_config_similarity() -> None:
    """auto_detect carries config.similarity, not a hardcoded value."""
    cfg = IndexingConfig(similarity="l2")
    summary = resolve_dim_and_similarity(cfg, store=InProcessChunkStore(cfg))
    assert summary.source == "auto_detected"
    assert summary.similarity == "l2"


def test_default_when_no_store_no_bakeoff() -> None:
    """SC-007: neither bakeoff nor store -> dim 384, cosine, source='default'."""
    cfg = IndexingConfig()
    summary = resolve_dim_and_similarity(cfg, store=None)
    assert summary.source == "default"
    assert summary.similarity == "cosine"
    assert summary.embedder is not None and summary.embedder.dim == 384
    assert summary.chunker is None


def test_default_when_store_probe_raises() -> None:
    """A store whose embed() raises falls through to the hard default."""

    class BrokenStore:
        def embed(self, text: str) -> list[float]:
            raise RuntimeError("no embedder")

    cfg = IndexingConfig()
    summary = resolve_dim_and_similarity(cfg, store=BrokenStore())  # type: ignore[arg-type]
    assert summary.source == "default"
    assert summary.embedder is not None and summary.embedder.dim == 384
