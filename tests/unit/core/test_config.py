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
