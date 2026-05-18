"""Configuration models and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

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
    # Phase 4 fields
    bakeoff_path: str | None = None
    similarity: Literal["cosine", "ip", "l2"] = "cosine"
    vector_dim: int | None = None
    hybrid_method: Literal["rrf", "weighted_sum"] = "rrf"
    hybrid_weights: dict[str, float] = Field(
        default_factory=lambda: {"keyword": 0.5, "vector": 0.5}
    )
    hybrid_rrf_k: int = Field(default=60, ge=1)
    task_backend: Literal["in_process", "redis", "celery"] = "in_process"
    task_backend_dsn: str | None = None

    @field_validator("hybrid_weights")
    @classmethod
    def _check_weights(cls, v: dict[str, float]) -> dict[str, float]:
        if set(v.keys()) != {"keyword", "vector"}:
            raise ValueError("hybrid_weights keys must be exactly {'keyword', 'vector'}")
        return v

    @field_validator("vector_dim")
    @classmethod
    def _check_dim(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("vector_dim must be > 0 when set")
        return v

    @model_validator(mode="after")
    def _check_task_backend_dsn(self) -> IndexingConfig:
        if self.task_backend in {"redis", "celery"} and not self.task_backend_dsn:
            raise ValueError(f"{self.task_backend} task_backend requires task_backend_dsn")
        if (
            self.hybrid_method == "weighted_sum"
            and sum(self.hybrid_weights.values()) == 0
        ):
            raise ValueError("hybrid_method='weighted_sum' requires non-zero weights")
        return self


class SigningConfig(BaseModel):
    mode: Literal["disabled", "optional", "required"] = "disabled"
    secret: str | None = None
    default_ttl_seconds: int | None = None


StrategyName = Literal[
    "summary_only",
    "memory_search",
    "artifact_search",
    "graph_search",
    "adaptive",
    "raw_fetch",
    "abstain",
]


class RecallConfig(BaseModel):
    enabled: bool = True
    default_strategy: StrategyName = "adaptive"
    confidence_floor: float = Field(default=0.4, ge=0.0, le=1.0)
    max_memory_hits: int = Field(default=5, ge=1)
    max_artifact_hits: int = Field(default=5, ge=1)
    max_context_chars: int = Field(default=16_000, ge=256)
    adaptive_tier_order: list[StrategyName] = Field(
        default_factory=lambda: cast(
            list[StrategyName],
            ["memory_search", "artifact_search", "raw_fetch", "abstain"],
        )
    )
    adaptive_skip_raw_fetch_without_artifact_id: bool = True
    abstain_default_reason: str = "no_sufficient_context"

    @field_validator("adaptive_tier_order")
    @classmethod
    def _abstain_last(cls, v: list[str]) -> list[str]:
        if not v or v[-1] != "abstain":
            raise ValueError("adaptive_tier_order must end with 'abstain'")
        return v


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
    # Retain each message verbatim as a candidate (in addition to the
    # lede-distilled passes) so exact answer-bearing literals — dates,
    # names, ids — survive extraction. Stele's "exact evidence" thesis;
    # materially lifts conversational recall (LoCoMo).
    retain_message_text: bool = True


class GraphConfig(BaseModel):
    """Living-knowledge projection (Phase 5). Batteries-included: the DSN is
    reused from the Postgres artifact backend; users never set pg-raggraph
    config. Default leans ``surface_both`` so a retracted source can still be
    cited (Task-0 proven: ``hide`` erases the citation in all views)."""

    enabled: bool = False
    namespace: str = "stele"
    evolution_tier: Literal["structural", "fact_aware", "full"] = "structural"
    retracted_behavior: Literal["hide", "flag", "surface_both"] = "surface_both"
    supersession_behavior: Literal["hide", "prefer_new", "surface_both"] = "prefer_new"


class StashConfig(BaseModel):
    backend: BackendConfig = Field(default_factory=BackendConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    pii: PIIConfig = Field(default_factory=PIIConfig)
    interception: InterceptionConfig = Field(default_factory=InterceptionConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    signing: SigningConfig = Field(default_factory=SigningConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    recall: RecallConfig = Field(default_factory=RecallConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)

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
