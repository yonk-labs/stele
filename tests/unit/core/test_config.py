import pytest

from stele.core.config import StashConfig


def test_minimal_config_defaults_to_memory() -> None:
    config = StashConfig.load(None)

    assert config.backend.type == "memory"
    assert config.pii.enabled is True


def test_yaml_config_loads() -> None:
    config = StashConfig.load(
        """
backend:
  type: memory
interception:
  min_chars: 100
"""
    )

    assert config.backend.type == "memory"
    assert config.interception.min_chars == 100


def test_postgres_graph_config_does_not_import_pg_raggraph() -> None:
    config = StashConfig.load(
        {
            "backend": {"type": "postgres", "dsn": "postgresql://localhost/db"},
            "retrieval": {"default_mode": "graph"},
        }
    )

    assert config.backend.type == "postgres"
    assert config.retrieval.default_mode == "graph"


def test_extraction_config_defaults() -> None:
    from stele.core.config import StashConfig

    cfg = StashConfig()
    assert cfg.extraction.enabled is True
    assert cfg.extraction.min_confidence == 0.6
    assert cfg.extraction.max_candidates_per_doc == 50
    assert cfg.extraction.overlay_patterns_enabled is True
    assert cfg.extraction.summary_kind == "summary"
    assert cfg.extraction.auto_stash_messages is True


def test_extraction_config_override_via_dict() -> None:
    from stele.core.config import StashConfig

    cfg = StashConfig.load({"extraction": {"min_confidence": 0.8, "enabled": False}})
    assert cfg.extraction.enabled is False
    assert cfg.extraction.min_confidence == 0.8
    assert cfg.extraction.overlay_patterns_enabled is True  # unchanged default


def test_recall_config_defaults() -> None:
    from stele.core.config import StashConfig

    cfg = StashConfig()
    assert cfg.recall.enabled is True
    assert cfg.recall.default_strategy == "adaptive"
    assert cfg.recall.confidence_floor == 0.4
    assert cfg.recall.max_memory_hits == 5
    assert cfg.recall.max_artifact_hits == 5
    assert cfg.recall.max_context_chars == 16_000
    assert cfg.recall.adaptive_tier_order == [
        "memory_search",
        "artifact_search",
        "raw_fetch",
        "abstain",
    ]
    assert cfg.recall.adaptive_skip_raw_fetch_without_artifact_id is True
    assert cfg.recall.abstain_default_reason == "no_sufficient_context"


def test_recall_config_rejects_tier_order_without_abstain_last() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError, match="abstain"):
        StashConfig.load(
            {"recall": {"adaptive_tier_order": ["memory_search", "artifact_search"]}}
        )


def test_recall_config_rejects_invalid_strategy_in_tier_order() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load(
            {"recall": {"adaptive_tier_order": ["bogus", "abstain"]}}
        )


def test_recall_config_rejects_confidence_floor_out_of_range() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load({"recall": {"confidence_floor": 1.5}})


def test_indexing_config_phase4_defaults() -> None:
    from stele.core.config import IndexingConfig, StashConfig  # noqa: F401

    cfg = StashConfig()
    ic = cfg.indexing
    assert ic.bakeoff_path is None
    assert ic.similarity == "cosine"
    assert ic.vector_dim is None
    assert ic.hybrid_method == "rrf"
    assert ic.hybrid_weights == {"keyword": 0.5, "vector": 0.5}
    assert ic.hybrid_rrf_k == 60
    assert ic.task_backend == "in_process"
    assert ic.task_backend_dsn is None


def test_indexing_config_rejects_bad_hybrid_weights() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load({"indexing": {"hybrid_weights": {"keyword": 0.5}}})

    with pytest.raises(PydanticValidationError):
        StashConfig.load(
            {
                "indexing": {
                    "hybrid_method": "weighted_sum",
                    "hybrid_weights": {"keyword": 0.0, "vector": 0.0},
                }
            }
        )


def test_indexing_config_rejects_redis_without_dsn() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load({"indexing": {"task_backend": "redis"}})


def test_indexing_config_rejects_negative_vector_dim() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load({"indexing": {"vector_dim": -1}})


def test_retrieval_config_accepts_vector_and_hybrid() -> None:
    from stele.core.config import StashConfig

    cfg_v = StashConfig.load({"retrieval": {"default_mode": "vector"}})
    cfg_h = StashConfig.load({"retrieval": {"default_mode": "hybrid"}})
    assert cfg_v.retrieval.default_mode == "vector"
    assert cfg_h.retrieval.default_mode == "hybrid"
