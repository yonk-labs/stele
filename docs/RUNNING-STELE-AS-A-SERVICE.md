# Running Stele as a Service

How to operate Stele as a durable, horizontally-scaled service with a
**shared embedding tier** instead of every worker loading its own model.
This is the service counterpart to `docs/RUNBOOK-graphrag-sweep.md` (which is
the one-shot batch counterpart).

**Read `docs/EMBEDDING-DEPLOYMENT-GAP.md` + `docs/EMBEDDING-FIX-PLAN.md`
first.** The shared-embedding architecture below is the *target*; some of it
requires the fix workstreams. The capability matrix states exactly what works
**today** vs **after** which workstream — do not skip it.

## Core principle

The embedding model is a **shared service tier**, not a per-worker library
load. Stele workers are stateless and cheap to scale; the embedding model,
the Postgres (artifact + graph), and the LLM endpoint are shared backing
services. The failure mode to design out: *N workers each initializing their
own ONNX embedding model* (the verified per-instance-load reality — see the
gap doc). One shared embedding deployment turns per-request embedding from a
~1–2 s model init into a ~ms network call.

## Target architecture

```
        ┌─────────────────────────────────────────────┐
        │              Stele workers (N, stateless)    │
        │   env-configured; scale horizontally          │
        └───────┬───────────────┬──────────────┬───────┘
                │               │              │
        embeddings (/v1)   Postgres        LLM (/v1)  [graph extraction
        SHARED service     artifact+pgrg   SHARED      / answer-judge only]
        (TEI / Infinity /  (pooled)        (OpenAI-
         vLLM / OpenAI-compat)              compatible)
```

- **Embedding service (shared):** an OpenAI-compatible `/v1/embeddings`
  server — e.g. HF Text-Embeddings-Inference, Infinity, or vLLM-embeddings.
  One deployment, sized for aggregate worker QPS. **This is the whole point.**
- **Postgres (shared):** the artifact store + pg-raggraph graph schema. Use a
  connection pool (pgbouncer or driver pool); the sweep's isolated-container
  pattern (`deploy/images/postgres-raggraph`) is the build source.
- **LLM endpoint (shared, optional):** only needed for graph entity
  extraction (`GraphConfig.fact_extractor="llm"`) or answer-judging.
  OpenAI-compatible; the sweep already uses `SWEEP_LLM_BASE_URL`.
- **Stele workers:** stateless. All state is in Postgres. Crash-safe /
  resumable semantics (the same `completed_keys`/append-flush properties the
  sweep relies on) make workers freely restartable.

## Capability matrix — today vs after the fix (honest)

| Path | Shared embedding endpoint? | Requires |
|---|---|---|
| keyword / memory recall | N/A — no embeddings at all | — works today |
| **graph** | **Yes** | **WS1** (un-hardcode Revisor; pg-raggraph already supports remote). Until WS1: per-instance local model. |
| **hybrid / vector** | **Not yet** | **WS3** (upstream chunkshop HTTP embedder). Until WS3: per-instance local model, or WS3-interim singleton (one model/process, not cross-process). |
| recall query-embedding | Follows its path's embedder | graph→WS1, vector→WS3 |
| global one-knob control | After **WS2** (`StashConfig.embedding` / `STELE_EMBED_*`) | WS2 |

**Honest consequence:** if you deploy as a service **today**, only the
graph + keyword paths can avoid per-worker model loads (graph needs the WS1
one-line passthrough; keyword needs nothing). A **hybrid/vector** service
today still loads a local embedder per worker — acceptable only if you
pin one worker-per-process and set `threads` explicitly. A fully shared
embedding tier across all paths requires WS1+WS2+WS3.

> **⚠️ Graph-path shared embedding — pg-raggraph 0.3.0a3 caveats (read
> before relying on the "shared embedding tier" for the graph path).** The
> shared-tier guidance above holds, but the graph path reaches a shared
> embedding endpoint only under two constraints inherent to pg-raggraph
> 0.3.0a3 (not Stele/WS1 bugs):
>
> 1. **Use `embedding_provider="ollama"`, NOT `"openai"`.** pg-raggraph's
>    `"openai"` provider HARDCODES `https://api.openai.com/v1` and IGNORES
>    the configured embedding base URL. A self-hosted / OpenAI-compatible
>    embedding deployment is reachable from the graph path ONLY via
>    `embedding_provider="ollama"` (it honors the configured base URL).
>    Setting `"openai"` against your own embedding service silently routes
>    embeddings to api.openai.com.
> 2. **With `fact_extractor="llm"`, the LLM and embedding endpoints must be
>    the SAME endpoint.** pg-raggraph 0.3.0a3 uses a single
>    `llm_base_url`/`llm_api_key` for BOTH entity-extraction and the
>    embedding endpoint. If you enable LLM graph extraction, the extraction
>    endpoint wins and the separate embedding endpoint is dropped — so the
>    shared embedding deployment and the shared LLM deployment must be one
>    OpenAI-compatible endpoint, or you must run graph extraction without
>    `fact_extractor="llm"`.
>
> See `docs/EMBEDDING-FIX-PLAN.md` → "Known pg-raggraph 0.3.0a3 limitations
> (WS1)". A future pg-raggraph with a dedicated embedding endpoint (or WS3's
> chunkshop HTTP embedder for the hybrid path) lifts constraint 2.

## Configuration / env reference (service mode)

Available **today** (verified env, used by the sweep harness):

| Env | Effect |
|---|---|
| `SWEEP_GRAPH_DSN` / `backend.dsn` | Postgres artifact+graph DSN (pooled in service mode) |
| `SWEEP_LLM_BASE_URL` / `SWEEP_LLM_MODEL` | shared LLM endpoint (graph extraction / judge) |
| `PGRG_EMBEDDING_PROVIDER` / `PGRG_EMBEDDING_MODEL` / `PGRG_EMBEDDING_DIM` | pg-raggraph **supports** these — but Stele's Revisor **ignores** them until **WS1** |
| `FASTEMBED_CACHE_PATH` | where local fastembed caches ONNX (set to a shared volume so workers don't each re-download) |

Available **after the fix** (the real service knobs):

| Env (WS2) | Effect |
|---|---|
| `STELE_EMBED_PROVIDER=openai-compatible` | route all embedding to the shared service |
| `STELE_EMBED_BASE_URL=http://embed.svc/v1` | the shared embedding deployment |
| `STELE_EMBED_MODEL` / `STELE_EMBED_DIM` | server-side model; **dim MUST match the index** |
| `STELE_EMBED_API_KEY` | if the embedding service authenticates |

> Until WS1/WS2 land, the only honest service-mode mitigation is:
> shared `FASTEMBED_CACHE_PATH` volume + one Stele worker per process +
> explicit fastembed `threads` (chunkshop warns auto-detect is "bad on
> shared boxes").

## Operational guidance

- **Concurrency:** size the shared embedding service for *aggregate* worker
  QPS, not per-worker. Postgres: a pool (pgbouncer) — many stateless workers
  will otherwise exhaust connections. Set fastembed/ORT `threads` explicitly
  per worker; never auto-detect on a shared host (real footgun — this is why
  the sweep box at load-avg 27 is slow).
- **Durability / restartability:** workers are stateless; all durable state
  is Postgres. A worker crash loses nothing committed; the same
  `completed_keys` + per-line append-flush properties that make the sweep
  resumable make a service worker safe to kill/restart/autoscale.
- **Dim invariant:** the embedding model's output dim must equal the index
  vector dim (default 384). Changing the shared model without reindexing
  silently corrupts similarity. WS2 adds a `ConfigError` guard; until then
  this is an operator responsibility — pin the model, version the index.
- **Health / readiness:** a worker is ready only if it can reach Postgres
  **and** (for non-keyword paths) the embedding service. Mirror the sweep's
  `run-full-sweep.sh preflight` checks as a readiness probe: venv import,
  Postgres connect, embedding `/models` (or `/v1/embeddings` ping), LLM
  `/models` if graph-LLM is enabled.
- **Failure modes:**
  - Embedding service down → vector/graph retrieval fails fast; keyword
    recall still works. Add retry/backoff (WS3.1 includes this for hybrid;
    pg-raggraph's openai/ollama providers should be configured with timeouts).
  - Postgres down → operations fail; nothing corrupted; resumable on recovery.
  - LLM endpoint down → only graph-LLM extraction / judging affected; the
    LLM-free default paths are unaffected.
- **Observability:** track per-request embedding latency (should be network-
  bound ms, not model-init seconds — if it's seconds you regressed to
  per-instance loading), Postgres pool saturation, embedding-service QPS vs
  capacity.
- **Rollout:** workers are stateless → rolling restart is safe. Embedding
  service / Postgres are the stateful tier — version and migrate those with
  care; the dim invariant makes embedding-model changes index-breaking.

## Relationship to the batch harness

- `docs/RUNBOOK-graphrag-sweep.md` + `scripts/run-full-sweep.sh` = the
  **one-shot batch** form (run the sweep once, unattended, on an isolated
  box). Same backing services, finite job.
- This guide = the **durable service** form (long-lived workers serving
  ongoing memory traffic). Same architecture; the difference is lifecycle
  (finite job vs always-on) and that the service form makes the shared
  embedding tier non-optional at scale.

## Bottom line

A correct Stele service = stateless workers + **one** shared embedding
deployment + pooled Postgres + (optional) shared LLM endpoint. The shared
embedding tier is the load-bearing decision; it is **fully available only
after WS1+WS2+WS3** (gap doc / fix plan). Deploying today is viable for
keyword + graph (graph needs the trivial WS1 patch) but **not** for a shared
hybrid tier until the chunkshop HTTP-embedder (WS3) lands — plan capacity and
host sizing for per-worker local embedders on the hybrid path until then.
