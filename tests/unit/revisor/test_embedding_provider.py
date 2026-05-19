"""RED spec (TDD): the Revisor exposes a configurable embedding provider
so a shared remote embedding deployment can be used instead of forcing a
per-worker local fastembed model. The DEFAULT (provider="local", no remote
fields) MUST keep ``_cfg()``'s output byte-identical to the pre-change
behavior — that back-compat invariant is load-bearing (a Stele with no
embedding config must behave EXACTLY as before).

pg-raggraph 0.3.0a3 reality (verified against the installed package):
``PGRGConfig`` has ONLY ``embedding_provider`` / ``embedding_model`` /
``embedding_dim``. It has NO ``embedding_base_url`` / ``embedding_api_key``
fields and rejects unknown kwargs (``extra_forbidden``). The
``get_embedding_provider`` factory resolves a remote (openai|ollama)
endpoint from ``config.llm_base_url`` and the key from
``config.llm_api_key``. So stele's ``embedding_base_url`` /
``embedding_api_key`` surface maps onto pg-raggraph's real ``llm_base_url``
/ ``llm_api_key`` cfg keys for the remote path.

Pure unit test — construction does not connect; ``_cfg()`` builds a dict
with no DB. Fails today: no embedding_provider passthrough exists.
"""

from __future__ import annotations

from typing import Any

import pytest

from stele.core.config import EmbeddingConfig, GraphConfig, StashConfig
from stele.core.stash import _resolve_graph_embedding
from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

_DSN = "postgresql://x:y@localhost:1/db"


def _rev(**kw: object) -> PgRaggraphRevisor:
    return PgRaggraphRevisor(
        dsn=_DSN, namespace="n", evolution_tier="structural", **kw
    )


def test_back_compat_default_cfg_is_byte_identical() -> None:
    """Default config -> _cfg() emits provider 'local' and NO remote keys.

    This is the back-compat lock: the exact pre-change dict shape.
    """
    rev = _rev()
    assert rev._embedding_provider == "local"
    cfg = rev._cfg("surface_both", "surface_both")
    assert cfg == {
        "namespace": "n",
        "embedding_provider": "local",
        "skip_extraction": True,
        "evolution_tier": "structural",
        "retracted_behavior": "surface_both",
        "supersession_behavior": "surface_both",
        "fact_extractor": "none",
    }
    # Key ORDER is also load-bearing for byte-identical back-compat
    # (== is order-insensitive for dicts; this locks the emission order).
    assert list(cfg.keys()) == [
        "namespace",
        "embedding_provider",
        "skip_extraction",
        "evolution_tier",
        "retracted_behavior",
        "supersession_behavior",
        "fact_extractor",
    ]
    # No remote-embedding keys leak onto the default path.
    assert "embedding_model" not in cfg
    assert "embedding_dim" not in cfg
    assert "llm_base_url" not in cfg
    assert "llm_api_key" not in cfg


def test_override_carries_provider_and_real_pgrg_keys() -> None:
    """provider='openai' + model/dim/base_url/api_key -> cfg carries the
    provider plus pg-raggraph's REAL kwarg names (embedding_model /
    embedding_dim, and llm_base_url / llm_api_key for the remote endpoint).
    """
    rev = _rev(
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_base_url="http://embed.svc/v1",
        embedding_api_key="sk-test",
    )
    cfg = rev._cfg("surface_both", "surface_both")
    assert cfg["embedding_provider"] == "openai"
    assert cfg["embedding_model"] == "text-embedding-3-small"
    assert cfg["embedding_dim"] == 1536
    # pg-raggraph 0.3.0a3 has no embedding_base_url/embedding_api_key
    # fields; remote embedding reads llm_base_url / llm_api_key.
    assert cfg["llm_base_url"] == "http://embed.svc/v1"
    assert cfg["llm_api_key"] == "sk-test"
    assert "embedding_base_url" not in cfg
    assert "embedding_api_key" not in cfg


def test_override_does_not_clobber_llm_extraction_endpoint() -> None:
    """When LLM extraction owns llm_base_url/llm_api_key, an embedding
    base_url/api_key must not overwrite the extraction endpoint."""
    rev = _rev(
        fact_extractor="llm",
        llm_base_url="http://llm.svc/v1",
        llm_api_key="sk-llm",
        embedding_provider="ollama",
        embedding_base_url="http://embed.svc/v1",
        embedding_api_key="sk-embed",
    )
    cfg = rev._cfg("surface_both", "surface_both")
    assert cfg["embedding_provider"] == "ollama"
    # LLM-extraction endpoint wins (it's the one already threaded).
    assert cfg["llm_base_url"] == "http://llm.svc/v1"
    assert cfg["llm_api_key"] == "sk-llm"


def test_stash_wiring_threads_graph_embedding_into_revisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The REAL stash.revisor property (postgres + graph.enabled) threads
    graph.embedding_* into PgRaggraphRevisor. Postgres store is stubbed so
    __init__ does not connect; the revisor property itself is DB-free.
    """
    import stele.core.stash as stash_mod

    class _StubStorage:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...
        def initialize(self) -> None: ...
        def close(self) -> None: ...

    class _StubRetrieval:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

    monkeypatch.setattr(stash_mod, "PostgresStorageBackend", _StubStorage)
    monkeypatch.setattr(stash_mod, "PostgresRetrievalBackend", _StubRetrieval)

    cfg = StashConfig.load(
        {
            "backend": {"type": "postgres", "dsn": _DSN},
            "indexing": {"mode": "skip"},
            "graph": GraphConfig(
                enabled=True,
                embedding_provider="openai",
                embedding_model="text-embedding-3-small",
                embedding_dim=1536,
                embedding_base_url="http://embed.svc/v1",
                embedding_api_key="sk-test",
            ),
        }
    )
    s = stash_mod.Stele(cfg)
    rev = s.revisor
    assert isinstance(rev, PgRaggraphRevisor)
    assert rev._embedding_provider == "openai"
    out = rev._cfg("surface_both", "surface_both")
    assert out["embedding_provider"] == "openai"
    assert out["embedding_model"] == "text-embedding-3-small"
    assert out["embedding_dim"] == 1536
    assert out["llm_base_url"] == "http://embed.svc/v1"
    assert out["llm_api_key"] == "sk-test"


# --- WS2: core EmbeddingConfig is the global default both paths read ---


def test_resolver_default_both_local_is_unchanged() -> None:
    """Default GraphConfig + default EmbeddingConfig -> local, no remote
    keys (back-compat lock)."""
    out = _resolve_graph_embedding(GraphConfig(), EmbeddingConfig())
    assert out == {
        "embedding_provider": "local",
        "embedding_model": None,
        "embedding_dim": None,
        "embedding_base_url": None,
        "embedding_api_key": "",
    }


def test_resolver_global_drives_graph_when_graph_default() -> None:
    """When the graph-specific override is unset (provider='local'), the
    core EmbeddingConfig drives the graph path. 'openai-compatible' MUST
    map to pg-raggraph 'ollama' (caveat A: pg-raggraph 'openai' hardcodes
    api.openai.com and ignores base_url)."""
    out = _resolve_graph_embedding(
        GraphConfig(enabled=True),
        EmbeddingConfig(
            provider="openai-compatible",
            base_url="http://embed.svc/v1",
            model="bge-small",
            dim=384,
            api_key="sek",
        ),
    )
    assert out["embedding_provider"] == "ollama"
    assert out["embedding_base_url"] == "http://embed.svc/v1"
    assert out["embedding_model"] == "bge-small"
    assert out["embedding_dim"] == 384
    assert out["embedding_api_key"] == "sek"


def test_resolver_explicit_graph_override_wins_over_global() -> None:
    """An explicitly-set graph.embedding_* (WS1 graph-specific override)
    takes precedence over the global EmbeddingConfig."""
    out = _resolve_graph_embedding(
        GraphConfig(
            enabled=True,
            embedding_provider="ollama",
            embedding_base_url="http://graph.svc/v1",
            embedding_model="graph-model",
        ),
        EmbeddingConfig(
            provider="openai-compatible",
            base_url="http://global.svc/v1",
            model="global-model",
        ),
    )
    assert out["embedding_provider"] == "ollama"
    assert out["embedding_base_url"] == "http://graph.svc/v1"
    assert out["embedding_model"] == "graph-model"


def test_stash_wiring_global_embedding_reaches_revisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: StashConfig.embedding (no graph-specific override)
    reaches the real Revisor as 'ollama' + base_url on llm_base_url."""
    import stele.core.stash as stash_mod

    class _StubStorage:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...
        def initialize(self) -> None: ...
        def close(self) -> None: ...

    class _StubRetrieval:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

    monkeypatch.setattr(stash_mod, "PostgresStorageBackend", _StubStorage)
    monkeypatch.setattr(stash_mod, "PostgresRetrievalBackend", _StubRetrieval)

    cfg = StashConfig.load(
        {
            "backend": {"type": "postgres", "dsn": _DSN},
            "indexing": {"mode": "skip"},
            "graph": {"enabled": True},
            "embedding": {
                "provider": "openai-compatible",
                "base_url": "http://embed.svc/v1",
                "model": "bge-small",
                "api_key": "sek",
            },
        }
    )
    s = stash_mod.Stele(cfg)
    rev = s.revisor
    assert isinstance(rev, PgRaggraphRevisor)
    assert rev._embedding_provider == "ollama"
    out = rev._cfg("surface_both", "surface_both")
    assert out["embedding_provider"] == "ollama"
    assert out["llm_base_url"] == "http://embed.svc/v1"
    assert out["llm_api_key"] == "sek"
