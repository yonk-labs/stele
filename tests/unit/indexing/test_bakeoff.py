"""Tests for BakeoffConfig models + loader + overlay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError as PydanticValidationError

from stele.core.config import IndexingConfig
from stele.core.exceptions import ConfigError
from stele.indexing.bakeoff import (
    BakeoffChunker,
    BakeoffConfig,
    BakeoffEmbedder,
    BakeoffSummary,
    load_bakeoff_file,
    overlay_onto_indexing_config,
)


def test_bakeoff_embedder_required_fields() -> None:
    e = BakeoffEmbedder(name="test-model", dim=768)
    assert e.dim == 768
    assert e.revision is None


def test_bakeoff_chunker_params_passthrough() -> None:
    c = BakeoffChunker(type="fixed_overlap", params={"window_words": 220, "overlap_words": 60})
    assert c.params["window_words"] == 220


def test_bakeoff_config_full() -> None:
    cfg = BakeoffConfig(
        chunker=BakeoffChunker(type="fixed_overlap", params={"window_words": 220}),
        embedder=BakeoffEmbedder(name="all-MiniLM-L6-v2", dim=384),
        similarity="cosine",
        benchmark_recall_at_5=0.82,
    )
    assert cfg.similarity == "cosine"


def test_bakeoff_config_rejects_unknown_similarity() -> None:
    with pytest.raises(PydanticValidationError):
        BakeoffConfig(
            chunker=BakeoffChunker(type="x", params={}),
            embedder=BakeoffEmbedder(name="x", dim=1),
            similarity="manhattan",  # type: ignore[arg-type]
        )


def test_bakeoff_summary_sources() -> None:
    s = BakeoffSummary(source="auto_detected", chunker=None, embedder=None, similarity="cosine")
    assert s.source == "auto_detected"


def _sample_dict() -> dict:  # type: ignore[type-arg]
    return {
        "chunker": {"type": "fixed_overlap", "params": {"window_words": 220}},
        "embedder": {"name": "all-MiniLM-L6-v2", "dim": 384},
        "similarity": "cosine",
    }


def test_load_bakeoff_json(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps(_sample_dict()))
    cfg = load_bakeoff_file(str(p))
    assert cfg.embedder.dim == 384


def test_load_bakeoff_yaml(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text(yaml.safe_dump(_sample_dict()))
    cfg = load_bakeoff_file(str(p))
    assert cfg.similarity == "cosine"


def test_load_bakeoff_missing_file_raises_configerror(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_bakeoff_file(str(tmp_path / "missing.json"))


def test_load_bakeoff_invalid_content_raises_configerror(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text('{"chunker": {}}')  # missing embedder + similarity
    with pytest.raises(ConfigError, match="invalid"):
        load_bakeoff_file(str(p))


def test_overlay_onto_indexing_config(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps(_sample_dict()))
    bakeoff = load_bakeoff_file(str(p))
    ic = IndexingConfig()
    overlaid = overlay_onto_indexing_config(ic, bakeoff)
    assert overlaid.similarity == "cosine"
    assert overlaid.vector_dim == 384
