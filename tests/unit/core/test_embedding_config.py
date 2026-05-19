"""RED spec (TDD) — WS2: a single core embedding-deployment surface.

`StashConfig.embedding` is the ONE operator lever for pointing every
Stele instance at a shared remote embedding deployment instead of each
worker loading a local fastembed model. The DEFAULT must be unchanged
(provider="local", no endpoint) so nothing existing breaks.

`STELE_EMBED_*` env overrides the config (operator override wins), so a
deployment can flip embedding globally without touching call sites.

The dim-vs-index invariant is a real footgun guard: a remote model whose
output dim differs from the existing vector index silently corrupts
similarity with no other error — construction must reject it loudly.

Pure unit tests: no DB, no network, no model load.
"""

from __future__ import annotations

import pytest

from stele.core.config import EmbeddingConfig, StashConfig
from stele.core.exceptions import ConfigError


def test_default_is_local_no_endpoint() -> None:
    """Back-compat lock: default config embeds locally, no remote keys."""
    cfg = StashConfig.load(None)
    assert cfg.embedding == EmbeddingConfig()
    assert cfg.embedding.provider == "local"
    assert cfg.embedding.base_url is None
    assert cfg.embedding.model is None
    assert cfg.embedding.dim is None
    assert cfg.embedding.api_key == ""


def test_embedding_config_loads_from_yaml() -> None:
    cfg = StashConfig.load(
        """
embedding:
  provider: openai-compatible
  base_url: http://embed.svc/v1
  model: bge-small
  dim: 384
  api_key: sek-test
"""
    )
    assert cfg.embedding.provider == "openai-compatible"
    assert cfg.embedding.base_url == "http://embed.svc/v1"
    assert cfg.embedding.model == "bge-small"
    assert cfg.embedding.dim == 384
    assert cfg.embedding.api_key == "sek-test"


def test_env_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """STELE_EMBED_* wins over the loaded config (operator override)."""
    monkeypatch.setenv("STELE_EMBED_PROVIDER", "openai-compatible")
    monkeypatch.setenv("STELE_EMBED_BASE_URL", "http://env.svc/v1")
    monkeypatch.setenv("STELE_EMBED_MODEL", "env-model")
    monkeypatch.setenv("STELE_EMBED_DIM", "768")
    monkeypatch.setenv("STELE_EMBED_API_KEY", "env-key")
    cfg = StashConfig.load(
        {"embedding": {"provider": "local", "model": "cfg-model"}}
    )
    assert cfg.embedding.provider == "openai-compatible"
    assert cfg.embedding.base_url == "http://env.svc/v1"
    assert cfg.embedding.model == "env-model"
    assert cfg.embedding.dim == 768
    assert cfg.embedding.api_key == "env-key"


def test_env_absent_leaves_config_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STELE_EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("STELE_EMBED_MODEL", raising=False)
    cfg = StashConfig.load({"embedding": {"model": "cfg-model"}})
    assert cfg.embedding.provider == "local"
    assert cfg.embedding.model == "cfg-model"


def test_dim_mismatch_raises_configerror() -> None:
    """embedding.dim != indexing.vector_dim (both set) is rejected."""
    with pytest.raises(ConfigError, match="embedding.dim"):
        StashConfig.load(
            {
                "embedding": {"dim": 768},
                "indexing": {"vector_dim": 384},
            }
        )


def test_dim_match_is_accepted() -> None:
    cfg = StashConfig.load(
        {"embedding": {"dim": 384}, "indexing": {"vector_dim": 384}}
    )
    assert cfg.embedding.dim == 384


def test_dim_unconstrained_when_index_dim_unset() -> None:
    """vector_dim is None by default — no constraint, default path safe."""
    cfg = StashConfig.load({"embedding": {"dim": 1536}})
    assert cfg.embedding.dim == 1536
    assert cfg.indexing.vector_dim is None
