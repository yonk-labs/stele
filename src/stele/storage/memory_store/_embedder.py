"""Optional memory-store embedder, synthesized internally from config.

Mirrors the chunk store: the embedder is built from ``IndexingConfig`` (the
same fastembed model chunks use, so memory and chunk vectors share a model),
never injected by the user and never reading ``os.environ``. Postgres-only.

``EmbeddingConfig`` remains the deployment lever; today both this path and the
chunk store use the local fastembed model. Routing the ``openai-compatible``
remote endpoint here is a follow-up (the chunk store does not branch on it yet
either), so memory and chunk embedding stay consistent.
"""

from __future__ import annotations

from importlib.util import find_spec
from typing import Protocol, runtime_checkable

from stele.core.config import IndexingConfig


@runtime_checkable
class MemoryEmbedder(Protocol):
    """Minimal probe embedder: a dim and a single-text embed call."""

    dim: int

    def embed(self, text: str) -> list[float]: ...


class _FastembedMemoryEmbedder:
    """Wraps chunkshop's loaded fastembed embedder with its output dim."""

    def __init__(self, model_name: str, dim: int) -> None:
        from chunkshop.config import FastembedEmbedder
        from chunkshop.embedders import load_embedder

        self.dim = dim
        self._inner = load_embedder(
            FastembedEmbedder(type="fastembed", model_name=model_name, dim=dim)
        )

    def embed(self, text: str) -> list[float]:
        return list(self._inner.embed(text))


def build_memory_embedder(config: IndexingConfig) -> MemoryEmbedder | None:
    """Synthesize the memory embedder from config, or None when chunkshop is
    absent (caller falls back to the keyword-only path)."""
    if find_spec("chunkshop") is None:  # pragma: no cover - env-dependent
        return None
    from stele.storage.chunk_store._chunkshop_base import _resolve_embed_dim

    dim = config.vector_dim or _resolve_embed_dim(config.embed_model)
    return _FastembedMemoryEmbedder(config.embed_model, dim)


def vec_literal(vector: list[float]) -> str:
    """Format a vector for a ``%s::vector`` bind (pgvector text input)."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"
