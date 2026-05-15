"""Bakeoff config models + loader + overlay logic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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
