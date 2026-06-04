# Embedding-Deployment Fix — Completion Plan

**Companion to:** `docs/EMBEDDING-DEPLOYMENT-GAP.md` (the findings).
This is the **executable work breakdown** to give Stele a single global
embedding-deployment override so many workers share one embedding endpoint
instead of each loading local ONNX models.
**Owner lineage:** `phase6-7` / `main` Stele dev (not the sweep branch).
**Status:** plan only — no code written. Facts below are verified file:line.

## Goal / definition of done

A Stele operator can set **one** config/env that makes **every** `Stele`
instance — across all processes/workers — send embedding work to a single
shared deployment (an OpenAI-compatible `/v1/embeddings` service), for both
the **graph** and **hybrid/vector** paths, with the **default unchanged**
(local fastembed) so nothing existing breaks.

Done when: (a) graph + hybrid + recall query-embedding all honor the shared
endpoint; (b) default config still loads local models (back-compat);
(c) a before/after benchmark shows per-cell embedding-init cost drops from
"model load each instance" to "network call"; (d) `mypy --strict` + `ruff`
clean; (e) tests prove both the local-default and the shared-endpoint paths.

## Workstreams

Ordered by value/effort. WS1 ships value alone; WS2 is the clean surface;
WS3 is gated on an upstream chunkshop change.

---

### WS1 — Graph path passthrough  *(trivial, no upstream dependency — do first)*

**Why first:** pg-raggraph **already** supports remote embedding providers
(`pg_raggraph/config.py:67` → `embedding_provider: str = "local"  # local |
openai | ollama`). Stele's Revisor simply hardcodes `"local"` and ignores it.

**Change:** `src/stele/revisor/pg_raggraph_revisor.py`
- Line ~82 in `_cfg()`: `embedding_provider="local"` is hardcoded. Replace
  with values threaded from `GraphConfig` (preferred) and/or
  `PGRG_EMBEDDING_*` env. Also pass `embedding_model` / `embedding_dim`
  (pg-raggraph reads `PGRG_EMBEDDING_MODEL` / `PGRG_EMBEDDING_DIM`).
- `src/stele/core/config.py` `GraphConfig`: add
  `embedding_provider: Literal["local","openai","ollama"] = "local"`,
  `embedding_model: str | None = None`, `embedding_dim: int | None = None`,
  `embedding_base_url: str | None = None`, `embedding_api_key: str = ""`.
  When `provider != "local"`, pass them into the GraphRAG cfg (pg-raggraph's
  `openai`/`ollama` providers use an HTTP base_url).

**Back-compat:** all new fields default to the current behavior
(`provider="local"`, no endpoint) → byte-identical cfg when unset.

**Tests (TDD):**
- unit: `_cfg()` emits `embedding_provider="local"` and NO endpoint keys when
  `GraphConfig` defaults (locks back-compat).
- unit: with `GraphConfig(embedding_provider="openai", embedding_base_url=...)`
  the cfg dict carries the provider + base_url + model + dim.
- integration (graph DB up): a graph ingest+query with `provider="openai"`
  pointed at a stub/real `/v1/embeddings` succeeds and does **not** load a
  local fastembed model (assert via no fastembed cache write / a patched
  guard).

**DoD:** graph cells in a 100-worker run make zero local embedding-model
inits; `mypy --strict`/`ruff` clean; back-compat test green.

**Known pg-raggraph 0.3.0a3 limitations (WS1):**

These are inherent pg-raggraph limitations, not WS1 bugs. WS1 wires the
passthrough correctly; the constraints live upstream.

- **(A) `embedding_provider="openai"` ignores the endpoint.**
  pg-raggraph's `embedding_provider="openai"` HARDCODES
  `https://api.openai.com/v1` and IGNORES the configured endpoint (source:
  installed `pg_raggraph/embedding.py:~115`). To reach a self-hosted /
  OpenAI-compatible embedding server you MUST use
  `embedding_provider="ollama"` (it honors `llm_base_url`). Using
  `"openai"` against a self-hosted embedding endpoint silently sends
  traffic to api.openai.com.
- **(B) One `llm_base_url`/`llm_api_key` shared by extraction + embedding.**
  pg-raggraph uses a SINGLE `llm_base_url`/`llm_api_key` pair for BOTH the
  entity-extraction LLM and the (ollama) embedding endpoint. WS1's
  no-clobber guard makes the extraction endpoint win, so when
  `fact_extractor="llm"` AND a remote embedding provider are both set, the
  extraction and embedding endpoints CANNOT differ — the separate
  embedding endpoint is silently dropped. This is correct precedence given
  the upstream single-field constraint, not a WS1 defect.

WS3 (chunkshop HTTP embedder) — or a future pg-raggraph that exposes a
dedicated embedding endpoint distinct from the extraction LLM — would lift
(B) by giving the embedding path its own endpoint.

---

### WS2 — Stele-core `EmbeddingConfig` surface  *(the real override knob)*

**Status: ✅ LANDED** (`feat/ws2-embedding-config`, whats-next #3).
`EmbeddingConfig` + `StashConfig.embedding` + `STELE_EMBED_*` env +
dim-vs-index `ConfigError` guard + `_resolve_graph_embedding` (global
default; explicit WS1 `graph.embedding_*` wins; `openai-compatible` →
pg-raggraph `ollama` per caveat A) are implemented and tested.
**Scope note — chunk-store ctor passthrough deferred to WS3:** the plan's
"fan out to (b) the chunk-store ctor" was intentionally NOT done in WS2.
That consumer is WS3, gated on an upstream chunkshop HTTP embedder that
does not exist yet (whats-next #4, parked). Wiring a dead unused param
into 5 chunk-store ctors now would be plumbing for an unknown-timeline
future; WS2 wires the one consumer that exists today (the graph path).
WS3 adds the chunk-store wiring when chunkshop gains the HTTP embedder.

**Why:** `src/stele/core/config.py` has **zero** embedding config (verified:
`grep -niE 'embed' src/stele/core/config.py` → none). Operators have no
single lever. WS1 alone leaves the knob graph-only and pg-raggraph-shaped.

**Change:** `src/stele/core/config.py`
- New model `EmbeddingConfig`:
  ```
  provider: Literal["local", "openai-compatible"] = "local"
  base_url: str | None = None        # e.g. http://embed.svc/v1
  model: str | None = None           # server-side model id
  dim: int | None = None             # must match the index
  api_key: str = ""
  ```
  Add `embedding: EmbeddingConfig = EmbeddingConfig()` to `StashConfig`.
- Env precedence: `STELE_EMBED_PROVIDER` / `STELE_EMBED_BASE_URL` /
  `STELE_EMBED_MODEL` / `STELE_EMBED_DIM` / `STELE_EMBED_API_KEY` override the
  config (mirror the `SWEEP_*` env pattern already used in the sweep).
- `Stele.__init__` fans `embedding` out to: (a) the Revisor cfg (supersedes
  WS1's GraphConfig fields — keep WS1 fields as the graph-specific override,
  but `StashConfig.embedding` is the global default both paths read), and
  (b) the chunk-store ctor (consumed by WS3).
- **Invariant to enforce:** `dim` must equal the index's vector dim
  (`IndexingConfig.vector_dim`, default 384). Changing embedding model/dim
  invalidates an existing index — validate at construction and raise
  `ConfigError` on mismatch with a clear message (this is a real footgun:
  a remote model with a different dim silently corrupts similarity).

**Tests:** default → local everywhere (back-compat); setting
`StashConfig.embedding` propagates to both Revisor cfg and chunk-store ctor;
dim/index mismatch raises `ConfigError`; env overrides config.

**DoD:** one config object / one env set controls embedding for the whole
process; default unchanged; dim-mismatch guarded; strict types/lint clean.

---

### WS3 — Hybrid/vector path  *(gated on an upstream chunkshop change)*

**Blocker:** `chunkshop/config.py:485` —
`EmbedderConfig = Annotated[Union[FastembedEmbedder], ...]`. The embedder
union has **only** the local `FastembedEmbedder`. There is no HTTP/remote
embedder type. (`HttpSource` at `config.py:138` is a data *source*, not an
embedder — do not confuse them.) Stele hardcodes
`FastembedEmbedder(model_name="sentence-transformers/all-MiniLM-L6-v2")` at
`src/stele/storage/chunk_store/_chunkshop_base.py:73-76`.

**Two-part work:**
1. **Upstream chunkshop (cross-repo):** add an HTTP embedder to chunkshop —
   a new `HttpEmbedder` config member (OpenAI-compatible `/v1/embeddings`:
   `base_url`, `model`, `dim`, `api_key`, `batch_size`), add it to the
   `EmbedderConfig` union + `load_embedder` dispatch, with retry/timeout.
   This is a chunkshop PR, owned by the chunkshop repo.
2. **Stele wiring:** in `_chunkshop_base.py`, when
   `StashConfig.embedding.provider != "local"`, construct chunkshop's new
   `HttpEmbedder` from `EmbeddingConfig` instead of the hardcoded
   `FastembedEmbedder`. Recall's query embedding (`vector_search` →
   `self._embedder.embed([query])`) then automatically uses the shared
   endpoint (same `_embedder`).

**Interim mitigation (no chunkshop change, ships before WS3.1):**
process-local **shared-embedder singleton** — cache one `FastembedEmbedder`
per `(model, dim)` per process so N `ChunkStore`s in a worker reuse one model
instead of loading per instance. Cuts the worst of the pathology for
multi-cell-per-process runs; does **not** give a cross-process shared
deployment. Also set `FastembedEmbedder.threads` explicitly (chunkshop warns
auto-detect is "bad on shared boxes", `config.py:453`) rather than None.

**Tests:** (interim) two `ChunkStore`s in one process share one embedder
object; (full) `provider="openai-compatible"` routes chunk + query embedding
to the HTTP endpoint, no local model loaded.

**DoD (full):** hybrid path uses the shared endpoint; recall query-embedding
too; back-compat default local; chunkshop PR merged + version-pinned.

---

### WS4 — Verification / perf proof  *(close the loop)*

Add a small bench: ingest+query one MHR-hybrid-shaped and one graph-shaped
cell, measure wall split between **embedding-model init**, embedding calls,
and real indexing/query — `local` vs shared-endpoint. Capture the delta.
**DoD:** documented before/after numbers proving per-instance init is
removed; this is what justifies the work (today: assumption; WS4: measured).
Pairs with the sweep's existing honesty discipline — report the real split,
don't assume.

## Sequencing & dependencies

```
WS1 (graph)  ─┐                         independent, ship now
WS2 (core)   ─┼─► enables clean WS1 + WS3 wiring (do alongside WS1)
WS3.interim  ─┘  (singleton) ships without chunkshop
WS3.1 chunkshop PR ──► WS3.2 Stele hybrid wiring  (cross-repo, slowest)
WS4 measures after WS1 (and again after WS3)
```

## Risks / honest caveats

- **Dim/model mismatch corrupts retrieval silently.** WS2's `ConfigError`
  guard is mandatory, not optional — a remote model with a different output
  dim than the existing index produces garbage similarity with no error
  otherwise.
- **Shared endpoint becomes a SPOF + throughput ceiling.** Document required
  capacity (it now serves every worker); needs retry/backoff and a health
  check (covered in the service guide).
- **WS3 is cross-repo and the long pole.** Do not block WS1/WS2 on it. The
  interim singleton is the pragmatic stopgap.
- **Back-compat is load-bearing.** Every workstream must keep `default ==
  current local behavior`; ship behind the new config, never by changing the
  default. Mirrors how the sweep's `SWEEP_*` overrides were done.
