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

