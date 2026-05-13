"""Configuration models and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from stele.core.exceptions import ConfigError
from stele.core.types import FailureMode, RetrievalMode


class BackendConfig(BaseModel):
    type: Literal["memory", "sqlite", "mariadb", "postgres", "clickhouse"] = "memory"
    path: str | None = None
    dsn: str | None = None
    table: str = "artifacts"
    database: str | None = None


class SummaryConfig(BaseModel):
    provider: str = "lede"
    max_chars: int = 1200


class PIIConfig(BaseModel):
    enabled: bool = True
    default_surface_policy: Literal["scrub", "raw", "block"] = "scrub"
    raw_fetch_enabled: bool = False
    providers: list[str] = Field(default_factory=lambda: ["regex"])
    replacement_style: str = "typed_token"


class InterceptionConfig(BaseModel):
    enabled: bool = True
    min_chars: int = 8000
    min_estimated_tokens: int = 2000
    max_replacement_chars: int = 1800
    fail_mode: FailureMode = "raise"


class RetrievalConfig(BaseModel):
    default_mode: RetrievalMode = "keyword"


class IndexingConfig(BaseModel):
    mode: Literal["async", "sync", "skip"] = "skip"
    provider: Literal["none", "chunkshop"] = "none"
    chunker: Literal["fixed_overlap"] = "fixed_overlap"
    chunk_words: int = 220
    chunk_overlap_words: int = 60


class SigningConfig(BaseModel):
    mode: Literal["disabled", "optional", "required"] = "disabled"
    secret: str | None = None
    default_ttl_seconds: int | None = None


class ExtractionConfig(BaseModel):
    enabled: bool = True
    min_confidence: float = 0.6
    max_candidates_per_doc: int = 50
    overlay_patterns_enabled: bool = True
    summary_kind: Literal[
        "fact",
        "preference",
        "decision",
        "instruction",
        "commitment",
        "issue",
        "summary",
    ] = "summary"
    auto_stash_messages: bool = True


class StashConfig(BaseModel):
    backend: BackendConfig = Field(default_factory=BackendConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    pii: PIIConfig = Field(default_factory=PIIConfig)
    interception: InterceptionConfig = Field(default_factory=InterceptionConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    signing: SigningConfig = Field(default_factory=SigningConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)

    @classmethod
    def load(cls, value: StashConfig | dict[str, Any] | str | Path | None) -> StashConfig:
        if value is None:
            return cls()
        if isinstance(value, StashConfig):
            return value
        if isinstance(value, dict):
            return cls.model_validate(value)
        if isinstance(value, Path):
            return cls._load_path(value)
        if isinstance(value, str):
            maybe_path = Path(value)
            if "\n" not in value and maybe_path.exists():
                return cls._load_path(maybe_path)
            loaded = yaml.safe_load(value) or {}
            if not isinstance(loaded, dict):
                raise ConfigError("YAML config must decode to a mapping")
            return cls.model_validate(loaded)
        raise ConfigError(f"Unsupported config value: {type(value)!r}")

    @classmethod
    def _load_path(cls, path: Path) -> StashConfig:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigError("YAML config must decode to a mapping")
        return cls.model_validate(loaded)
