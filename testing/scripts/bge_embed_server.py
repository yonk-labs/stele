# ruff: noqa: E501  -- standalone bge embeddings microserver (SYSTEM python3).
"""Minimal OpenAI-compatible /v1/embeddings server backed by fastembed bge-base-en-v1.5.

Exists so the Letta container can use the SAME embedder as stele/mem0 (bge, 768d),
removing the embedder confound (Letta natively uses openai/text-embedding-3-small).
Host 0.0.0.0:8284 -> reachable from the Letta container at http://172.17.0.1:8284/v1.

Run: python3 benchmarks/external/bge_embed_server.py
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastembed import TextEmbedding
from pydantic import BaseModel

_MODEL = TextEmbedding("BAAI/bge-base-en-v1.5")
app = FastAPI()


class EmbedReq(BaseModel):
    input: list[str] | str
    model: str = "bge-base-en-v1.5"


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/embeddings")
def embeddings(req: EmbedReq) -> dict:
    texts = [req.input] if isinstance(req.input, str) else req.input
    vecs = [e.tolist() for e in _MODEL.embed(texts)]
    return {
        "object": "list", "model": req.model,
        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8284, log_level="warning")
