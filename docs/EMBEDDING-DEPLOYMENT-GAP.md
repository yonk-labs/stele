# Stele Product Gap: No Global Embedding-Deployment Override

**Status:** Findings + recommendation. **No code changed.** Roadmap item for the
Stele dev lineage (`phase6-7` / `main`) — *not* the sweep's job.
**Date:** 2026-05-19 · **Found via:** graph-RAG benchmark sweep (this branch).
**Scope decision:** document only; the sweep harness was deliberately left
unmodified.

## Problem

Every `Stele` instance loads its **own local ONNX embedding model(s)** on
init / first query. There is **no configuration surface** to point embedding
work at a single shared/remote deployment. At scale (a benchmark sweep, or any
"many workers" deployment) this means N instances → up to **2N** independent
embedding-model initializations, none shared across instances or processes.
The user's framing: *"we don't want 1000 threads to each have their own
deployment — that would kill performance."* Confirmed real.

Observed correlate: in this sweep, MHR-hybrid cells take ~26 min each. Per-cell
embedding-model re-init is plausibly a significant contributor (not the sole
one — the host is also at load-avg ~27, and MHR-hybrid does genuine indexing
over 609 docs × 2556 queries). chunkshop's own config comments this footgun:
`FastembedEmbedder.threads` → *"None = fastembed auto-detects (bad on shared
boxes)"* (`chunkshop/config.py:453`).

## Current reality (verified, file:line)

| Path | Embeds? | What happens | Evidence |
|---|---|---|---|
| keyword / memory recall | No (pure lexical) | — | — |
| hybrid / vector | Yes | **Hardcoded** local `FastembedEmbedder(model_name="sentence-transformers/all-MiniLM-L6-v2")`, loaded per `ChunkStore` instance | `src/stele/storage/chunk_store/_chunkshop_base.py:73-76` |
| graph | Yes | Revisor **hardcodes** `embedding_provider="local"` (pg-raggraph default model `BAAI/bge-small-en-v1.5`), per `GraphRAG` | `src/stele/revisor/pg_raggraph_revisor.py:82` |
| recall (vector/graph query) | Yes | Reuses the same per-instance local embedder for the query vector | (same modules) |

- **Stele core has zero embedding config.** `grep -niE 'embed'
  src/stele/core/config.py` → no matches. `IndexingConfig` exposes only
  `vector_dim` / `similarity`; `GraphConfig` only LLM-extraction fields. There
  is no provider/endpoint/model/api-key knob anywhere in `StashConfig`.
- **pg-raggraph already supports remote embedding providers** —
  `pg_raggraph/config.py:67`: `embedding_provider: str = "local"  # local |
  openai | ollama` (env `PGRG_EMBEDDING_PROVIDER` / `PGRG_EMBEDDING_MODEL` /
  `PGRG_EMBEDDING_DIM`). **Stele's Revisor hardcodes `"local"` and ignores all
  of these.**
- **chunkshop does NOT support a remote embedder.** Its embedder union is
  `EmbedderConfig = Annotated[Union[FastembedEmbedder], ...]`
  (`chunkshop/config.py:485`) — `FastembedEmbedder` (local ONNX) is the *only*
  member. (`HttpSource` at `config.py:138` is a data *source*, unrelated to
  embedding.) A shared/remote embedder for the hybrid path therefore requires
  an **upstream chunkshop change**, not just a Stele config passthrough.

## Impact

- Sweep / many-worker deployments: per-instance model init dominates wall time
  and memory; a 1000-worker run is effectively infeasible without a shared
  deployment.
- No operator lever exists today to fix it from config or env.

## Recommendation (split by cost — for the Stele lineage to action)

### 1. Graph path — trivial, no upstream dependency (do this first)
pg-raggraph already supports `openai`/`ollama` remote providers. Stop
hardcoding in `PgRaggraphRevisor._cfg()` (`pg_raggraph_revisor.py:~82`); thread
provider/model/dim from a new `GraphConfig` field and/or `PGRG_EMBEDDING_*`
env passthrough. Sketch:

```python
embedding_provider=os.environ.get("PGRG_EMBEDDING_PROVIDER", "local"),
embedding_model=os.environ.get("PGRG_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
embedding_dim=int(os.environ.get("PGRG_EMBEDDING_DIM", "384")),
```
Effect: all graph cells/instances can point at one shared embedding endpoint.
Default `"local"` keeps current behavior; purely additive.

### 2. Hybrid path — needs upstream chunkshop work
chunkshop must add an HTTP/remote embedder to its `EmbedderConfig` union (e.g.
an OpenAI-compatible `/v1/embeddings` provider) + `load_embedder` dispatch.
Then Stele can select it. Until then, the only in-process mitigation is a
process-local shared-embedder singleton (one model per process instead of per
`ChunkStore`) — a workaround, not a shared deployment.

### 3. Stele core — the real fix (first-class surface)
Introduce an `EmbeddingConfig` on `StashConfig`:
`provider` (`local` | `openai-compatible`), `base_url`, `model`, `dim`,
`api_key`; env overrides `STELE_EMBED_*`. Semantics: **one shared deployment
for every Stele instance**. It fans out to (1) the Revisor graph cfg and
(2) the chunkshop embedder once chunkshop supports remote. This is the
single override surface the user is asking for; it belongs in Stele core,
coordinated with the chunkshop enhancement.

## If you only do one thing
Ship **#1 (graph passthrough)** — highest value/effort ratio, zero upstream
dependency, immediately enables a shared embedding deployment for the graph
arm. #2/#3 are larger and gated on chunkshop.

## Ownership / scope note
This is a Stele *product* gap, surfaced by the sweep but **not** fixed here by
deliberate decision — the sweep is a measurement tool, not the place to
redesign Stele's embedding architecture. Consequence to plan around: the
isolated-server multi-day sweep run still uses **per-instance local
embedders**; size the host accordingly (CPU/RAM headroom, and set
`FastembedEmbedder.threads` rather than letting it auto-detect on a shared
box). Pick this up on the `phase6-7`/`main` Stele lineage.
