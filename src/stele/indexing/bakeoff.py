"""Bakeoff config models + loader + overlay logic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from stele.core.config import IndexingConfig
from stele.core.exceptions import ConfigError


class BakeoffEmbedder(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    dim: int
    revision: str | None = None


class BakeoffChunker(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: str
    params: dict[str, object]


class BakeoffConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    chunker: BakeoffChunker
    embedder: BakeoffEmbedder
    similarity: Literal["cosine", "ip", "l2"]
    benchmark_recall_at_5: float | None = None
    notes: str | None = None


class BakeoffSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: Literal["bakeoff_file", "auto_detected", "default"]
    chunker: BakeoffChunker | None
    embedder: BakeoffEmbedder | None
    similarity: Literal["cosine", "ip", "l2"]
    file_path: str | None = None


def load_bakeoff_file(path: str) -> BakeoffConfig:
    """Load and validate a bakeoff config from a JSON or YAML file."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"bakeoff_path {path!r} does not exist")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    try:
        data = yaml.safe_load(text) or {} if suffix in {".yaml", ".yml"} else json.loads(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"bakeoff config invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("bakeoff config invalid: top-level must be a mapping")
    try:
        return BakeoffConfig.model_validate(data)
    except PydanticValidationError as exc:
        raise ConfigError(f"bakeoff config invalid: {exc}") from exc


def overlay_onto_indexing_config(
    indexing: IndexingConfig, bakeoff: BakeoffConfig
) -> IndexingConfig:
    """Apply bakeoff settings on top of IndexingConfig. Returns a new instance."""
    return indexing.model_copy(
        update={
            "similarity": bakeoff.similarity,
            "vector_dim": bakeoff.embedder.dim,
        }
    )
