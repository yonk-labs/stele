"""Configuration models and loader."""

from __future__ import annotations

import os
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
    # PII scrubbing is OPT-IN. Off by default: stele's premise is exact bytes,
    # and the common deployment is single-user/local where scrubbing only costs
    # recall. Turn this on for shared/multi-tenant stores. When enabled,
    # model-visible surfaces (summaries, fetch, search hits, memory text) are
    # masked; raw content still round-trips via the artifact store.
    enabled: bool = False
    default_surface_policy: Literal["scrub", "raw", "block"] = "scrub"
    raw_fetch_enabled: bool = False
    # When enabled, how a PII-bearing document is handled for chunk indexing:
    #   "mask" — index it; model-visible hits are scrubbed at read time (default)
    #   "skip" — leave the document out of the chunk index entirely (the artifact
    #            is still stored for exact-byte fetch / keyword retrieval)
    index_on_pii: Literal["mask", "skip"] = "mask"
    providers: list[str] = Field(default_factory=lambda: ["regex"])
    replacement_style: str = "typed_token"


class InterceptionConfig(BaseModel):
    enabled: bool = True
    min_chars: int = 8000
    min_estimated_tokens: int = 2000
    max_replacement_chars: int = 1800
    fail_mode: FailureMode = "raise"


class RetrievalConfig(BaseModel):
    default_mode: RetrievalMode = "hybrid"
    # Opt-in: route natural-language temporal queries ("last week") through
    # parse_temporal into a created_at/metadata date filter (filter-then-rank).
    # Off by default — changes retrieval semantics and needs a clock.
    temporal_routing: bool = False
    # When set, the parsed window targets metadata[<field>] (ISO date strings);
    # when None, it targets the artifact's created_at.
    temporal_date_field: str | None = None
    # Opt-in (Postgres only): give the memory store a vector embedding column so
    # Memory.search_with_score blends semantic similarity (RRF) with the tsvector
    # keyword leg. Off by default; when off, recall is byte-identical to today.
    # The embedder is synthesized internally from the same fastembed model the
    # chunk store uses (shared model), never injected. Requires chunkshop.
    memory_vector: bool = False


class IndexingConfig(BaseModel):
    mode: Literal["async", "sync", "skip"] = "sync"
    provider: Literal["none", "chunkshop"] = "chunkshop"
    chunker: Literal["fixed_overlap", "sentence_aware", "consolidation"] = "sentence_aware"
    # Embedding model for the chunkshop vector index. Default matches chunkshop's
    # de-facto default — Xenova/bge-base-en-v1.5-int8 (768-dim, int8-quantized) —
    # a far stronger retriever than the old all-MiniLM-L6-v2 (384). dim is
    # auto-derived from the model unless vector_dim is set explicitly.
    embed_model: str = "Xenova/bge-base-en-v1.5-int8"
    # Chunk sizes are tuned to bge-base's 512-token window (~2x MiniLM's 256).
    # 220 words (~290 tokens) wasted half that capacity and produced too many
    # tiny chunks — hurting coverage and recall. ~350 words (~460 tokens) fills
    # the window with headroom under 512 before the embedder truncates.
    chunk_words: int = 350
    chunk_overlap_words: int = 80
    # sentence_aware chunker (used iff chunker == "sentence_aware"): split on
    # full-sentence boundaries (never mid-sentence), packing up to
    # sentence_max_chars. neighbor_window > 0 wraps each chunk with ±N adjacent
    # chunks for context (chunkshop NeighborExpandChunker).
    sentence_max_chars: int = 1000
    sentence_min_chars: int = 300
    neighbor_window: int = 1
    # Consolidation chunker fields (used iff chunker == "consolidation").
    # The consolidator is loaded by import path on the chunkshop side via
    # CallableConsolidator(module=..., function=..., kwargs=...). API keys
    # and other secrets MUST be read from env inside the consolidator —
    # never persisted via consolidator_kwargs.
    consolidator_module: str | None = None
    consolidator_function: str = "consolidate"
    consolidator_kwargs: dict[str, Any] = Field(default_factory=dict)
    fact_max_chars: int = Field(default=200, ge=1)
    # Phase 4 fields
    bakeoff_path: str | None = None
    similarity: Literal["cosine", "ip", "l2"] = "cosine"
    # Vector index for the chunk sink. HNSW (approximate ANN) is the default, but
    # on small reference-filtered stores its seed can miss candidates (see the
    # "vector recall shortfall" path); set False for an exact/brute-force scan.
    hnsw: bool = True
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
        if self.chunker == "consolidation" and not self.consolidator_module:
            raise ValueError(
                "chunker='consolidation' requires consolidator_module to be set"
            )
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
    # Surface behavioral rule/skill/practice sentences (a deterministic
    # sentence/line scan) that lede's importance ranking drops. Required for
    # distill_rules/skills/best_practices to work end-to-end from raw text.
    extract_rules: bool = True
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


class DistillConfig(BaseModel):
    overlay_patterns_enabled: bool = True  # rules must not collapse to fact
    synthesis: str = "auto"  # "auto" uses injected LLM if present, else deterministic


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
    # Opt-in, non-default graph extraction. "none" keeps the LLM-free
    # default (no graph built). "llm" projects an entity/relationship graph
    # via the endpoint below — the LLM stays inside the Revisor adapter, so
    # recall/ remains LLM-free.
    fact_extractor: Literal["none", "llm", "lede_spacy"] = "none"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str = ""
    # Opt-in graph-query tuning. Default ("smart"/False) is the untuned
    # path; with a real graph, ("hybrid"/True) is the documented lever.
    query_mode: Literal[
        "smart", "naive", "naive_boost", "local", "global", "hybrid"
    ] = "smart"
    rerank: bool = False
    # Graph-path embedding provider. Default "local" keeps the per-worker
    # fastembed model (byte-identical to pre-WS1 behavior). Set "openai" or
    # "ollama" to point the graph at a shared remote embedding deployment.
    # pg-raggraph 0.3.0a3 has no dedicated embedding endpoint field; its
    # remote embedder reads ``llm_base_url`` / ``llm_api_key``, so
    # embedding_base_url/embedding_api_key map onto those in the Revisor.
    #
    # pg-raggraph 0.3.0a3 CAVEATS (loud, do not skip):
    # - provider="openai" ALWAYS targets api.openai.com and IGNORES
    #   embedding_base_url. For a self-hosted / OpenAI-compatible embedding
    #   endpoint you MUST use provider="ollama" (it honors llm_base_url).
    # - pg-raggraph shares ONE llm_base_url/llm_api_key for BOTH the
    #   entity-extraction LLM and the embedding endpoint, so with
    #   fact_extractor="llm" the extraction and embedding endpoints CANNOT
    #   differ (the extraction endpoint wins).
    embedding_provider: Literal["local", "openai", "ollama"] = "local"
    embedding_model: str | None = None
    embedding_dim: int | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str = ""


class EmbeddingConfig(BaseModel):
    """The single core embedding-deployment lever (WS2). Default is the
    per-worker local fastembed model (byte-identical to pre-WS2). Set
    ``provider="openai-compatible"`` + ``base_url`` to point every Stele
    instance at one shared remote ``/v1/embeddings`` deployment instead
    of N local model loads.

    ``STELE_EMBED_*`` env overrides each field (operator override wins),
    so a deployment can flip embedding globally without touching call
    sites. ``dim`` MUST match the vector index's dim — a mismatch
    silently corrupts similarity, so it is guarded at construction
    (see ``StashConfig`` validator)."""

    provider: Literal["local", "openai-compatible"] = "local"
    base_url: str | None = None
    model: str | None = None
    dim: int | None = None
    api_key: str = ""


_EMBED_ENV = {
    "provider": "STELE_EMBED_PROVIDER",
    "base_url": "STELE_EMBED_BASE_URL",
    "model": "STELE_EMBED_MODEL",
    "dim": "STELE_EMBED_DIM",
    "api_key": "STELE_EMBED_API_KEY",
}


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
    distill: DistillConfig = Field(default_factory=DistillConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)

    @model_validator(mode="after")
    def _embedding_env_and_dim_guard(self) -> StashConfig:
        # STELE_EMBED_* env overrides config (operator override wins).
        overrides: dict[str, Any] = {}
        for field, env in _EMBED_ENV.items():
            raw = os.environ.get(env)
            if raw is None:
                continue
            if field == "dim":
                try:
                    overrides[field] = int(raw)
                except ValueError as exc:
                    raise ConfigError(
                        f"{env} must be an integer, got {raw!r}"
                    ) from exc
            else:
                overrides[field] = raw
        if overrides:
            self.embedding = self.embedding.model_copy(update=overrides)
        # A remote model whose output dim differs from the existing vector
        # index silently corrupts similarity with no other error — reject
        # it loudly. Unconstrained when either side is unset (the default
        # path: vector_dim is None).
        e_dim = self.embedding.dim
        i_dim = self.indexing.vector_dim
        if e_dim is not None and i_dim is not None and e_dim != i_dim:
            raise ConfigError(
                f"embedding.dim ({e_dim}) must equal indexing.vector_dim "
                f"({i_dim}) — a different embedding dim invalidates the "
                "vector index and silently corrupts similarity."
            )
        return self

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
