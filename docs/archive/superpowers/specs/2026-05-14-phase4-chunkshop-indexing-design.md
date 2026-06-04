---
phase: 4
title: Chunkshop Indexing
created: 2026-05-14
status: design-approved
location: docs/superpowers/ (committed to git on main)
depends-on: |
  Phase 1 complete (memory + memory_store + as_of + supersession on memory/sqlite/postgres).
  Phase 2 complete (deterministic extraction layer with MemoryExtractor.preview).
  Phase 3 complete (recall facade with adaptive + 6 real strategies). NOTE: Phase 3
  shipped RecallConfig, not RetrievalConfig.default_mode — Phase 4 Task 1 introduces
  the RetrievalMode surface itself.
external-deps: |
  Chunkshop 0.4.1, repo github.com/yonk-labs/chunkshop, python package in the
  python/ subdir. GitHub-tagged/released only — NOT on PyPI (PyPI still serves
  0.3.2, which has no modular backends). Pinned to the immutable git tag v0.4.1:
    chunkshop[all-backends] @ git+https://github.com/yonk-labs/chunkshop.git@v0.4.1#subdirectory=python
  [all-backends] == sqlite,mariadb,clickhouse. Postgres is core (psycopg[binary]
  is a core chunkshop dependency) — there is NO [postgres] extra. MariaDB +
  ClickHouse adapters (sinks/{sqlite,pg,mariadb,clickhouse}.py + matching
  sources/) are present at v0.4.1. Migrate to chunkshop[all-backends]>=0.4.1,<0.5
  once published to PyPI.
---

# Phase 4: Chunkshop Indexing — Design

## TL;DR

Phase 4 ships production vector + hybrid retrieval across all 5 backends via
Chunkshop adapters, plus production indexing modes (sync/async/skip) with a
pluggable `TaskBackend` Protocol, plus bakeoff-generated config consumption.
The existing in-process `ChunkIndex` stays as a deterministic fallback for
chunkshop-less environments (test suites, smoke runs, the memory backend
without an embedder). Phase 3's `ArtifactSearchStrategy` automatically picks
up vector and hybrid retrieval through `RetrievalConfig.default_mode` — no
Phase 3 changes required.

## The Four Headline Proofs

1. **Vector retrieval works on every backend.** A new contract test
   parametrized across memory + sqlite + postgres + mariadb + clickhouse
   stores a fixture document, retrieves the expected top-K chunk via vector
   search, and asserts the chunk_id format `{artifact_id}:{ordinal}`
   round-trips through Chunkshop without leaking Chunkshop-native IDs.
2. **Hybrid beats vector-only and keyword-only (within a 5% floor).** A
   held-out test set (≥20 query/relevant-chunk pairs) shows
   `hybrid_recall@5 >= max(vector_recall@5, keyword_recall@5) − 0.05`.
   Failure outside the floor is a regression, not a design choice.
3. **Async indexing.** `stele.store(...)` returns immediately when
   `indexing.mode="async"`. `stele.indexing_status(artifact_id)` reports
   `"pending"` → `"indexed"` (or `"failed"`). Search against a not-yet-
   indexed artifact reports `SearchHit.metadata["indexing_status"]="pending"`
   on partially-available results rather than silently missing them.
4. **Bakeoff config consumption.** A Chunkshop bakeoff result file at
   `indexing.bakeoff_path` is loaded at `Stele(...)` construction time,
   overlaying its recommended chunker/embedder/similarity onto
   `IndexingConfig`. Applied overlay is reachable via
   `Stele.capabilities().bakeoff_summary` so users know which settings won.

## Locked Architectural Decisions

These were settled during brainstorming; they constrain the rest of the
design.

1. **Keep in-process `ChunkIndex` as deterministic fallback; add new
   backend-aware Chunkshop adapter alongside.** Existing
   `src/stele/indexing/chunk_index.py` keeps its current role for the
   in-memory + chunkshop-absent path. Phase 4 adds
   `chunkshop_adapter.py` + per-backend `chunk_store/<backend>.py`
   wrappers.
2. **Real vector retrieval on all 5 backends via Chunkshop.** Postgres
   (pgvector), memory (in-process numpy), SQLite (sqlite-vec), MariaDB
   (11.7+ VECTOR), ClickHouse (vector indexes). MariaDB + ClickHouse
   adapters ship in Chunkshop 0.4.1 (pinned to git tag v0.4.1).
3. **Hybrid retrieval included in Phase 4.** RRF default, weighted-sum
   optional. Hybrid uses score normalization + merging in
   `src/stele/retrieval/hybrid.py`. Phase 3's `ArtifactSearchStrategy`
   picks up hybrid via `RetrievalConfig.default_mode` without code changes.
4. **Sync + skip + async with pluggable `TaskBackend` Protocol.**
   `InProcessTaskBackend` (threading.Thread + queue.Queue) ships real.
   `RedisTaskBackend` and `CeleryTaskBackend` ship as `CapabilityError`
   stubs — same pattern as Phase 1's MariaDB/ClickHouse memory stubs.
5. **Bakeoff config via path in `IndexingConfig` + auto-apply at startup.**
   `indexing.bakeoff_path: str | None` points at a JSON/YAML file; Stele
   loads it at construction time. **Fallback:** when no bakeoff is
   configured, vector dimension + similarity are auto-detected at first
   chunk write via an embedder probe.
6. **Architecture: thin Approach A with Chunkshop as the engine.**
   Per-backend wrapper files (~80 lines each), lazy-importing the matching
   Chunkshop adapter. Stele owns chunk_id format, PII invariant, SearchHit
   translation.
7. **Pin Chunkshop via git ref + per-backend extras.**
   `chunkshop = ["chunkshop[all-backends] @ git+https://github.com/yonk-labs/chunkshop.git@v0.4.1#subdirectory=python"]`
   in `pyproject.toml` (0.4.1 is GitHub-tag-only, not on PyPI; Postgres is
   core, no [postgres] extra; the in-flight v0.4.2 is Rust-only and does not
   change the Python package, so stele stays on v0.4.1 Python).
   Each Stele backend's `chunk_store` lazy-imports its
   matching Chunkshop sub-package and raises `OptionalDependencyError`
   with the exact `pip install` line if missing.

## Public API

Phase 4 doesn't add a new namespace on `Stele`. It extends existing methods.

### Search — `RetrievalMode` expands

`src/stele/core/types.py` changes:

```python
# before:
RetrievalMode = Literal["keyword"]

# after:
RetrievalMode = Literal["keyword", "vector", "hybrid"]
```

`Stele.search(query, *, reference=None, limit=10, mode=None)` accepts an
explicit `mode`; when `None`, uses `RetrievalConfig.default_mode`. Returns
`list[SearchHit]` as today; `SearchHit.retrieval_mode` carries the actual
mode used.

### Store + indexing — same surface, new semantics

`Stele.store(...)` call-side is unchanged. Its **behavior** changes:

| `indexing.mode` | What happens |
|---|---|
| `"skip"` | No-op (today). `IndexResult.status="skipped"`. |
| `"sync"` | Chunk + embed inline. Talks to `ChunkStore` (new). `IndexResult.status="indexed"` on return. |
| `"async"` | Submit to the configured `TaskBackend`. `IndexResult.status="pending"`. Indexing happens on the worker. |

New method on `Stele`:

```python
def indexing_status(self, artifact_id: str) -> IndexResult: ...
```

Returns `pending` / `indexed` / `failed` / `skipped`. Callers can poll.

### `TaskBackend` Protocol

```python
class TaskBackend(Protocol):
    name: str   # "in_process" | "redis" | "celery"

    def submit(self, task: IndexTask) -> str: ...           # returns task id
    def status(self, task_id: str) -> TaskStatus: ...
    def close(self) -> None: ...


class IndexTask(BaseModel):
    artifact_id: str
    reference: str
    namespace: str
    submitted_at: datetime


class TaskStatus(BaseModel):
    task_id: str
    state: Literal["pending", "running", "succeeded", "failed"]
    message: str | None = None
```

`InProcessTaskBackend` ships real. `RedisTaskBackend` and
`CeleryTaskBackend` ship as `CapabilityError` stubs with import-hint
messages.

### Bakeoff config

```python
class BakeoffEmbedder(BaseModel):
    name: str                   # e.g., "sentence-transformers/all-MiniLM-L6-v2"
    dim: int
    revision: str | None = None


class BakeoffChunker(BaseModel):
    type: str                   # e.g., "fixed_overlap"
    params: dict[str, object]


class BakeoffConfig(BaseModel):
    chunker: BakeoffChunker
    embedder: BakeoffEmbedder
    similarity: Literal["cosine", "ip", "l2"]
    benchmark_recall_at_5: float | None = None
    notes: str | None = None
```

When `IndexingConfig.bakeoff_path` is set, `Stele.__init__` loads the
file (JSON or YAML), validates it as `BakeoffConfig`, and overlays it onto
`IndexingConfig` at construction time. The applied overlay is reachable
via `Stele.capabilities().bakeoff_summary`.

### Capabilities expansion

```python
class BakeoffSummary(BaseModel):
    source: Literal["bakeoff_file", "auto_detected", "default"]
    chunker: BakeoffChunker | None
    embedder: BakeoffEmbedder | None
    similarity: Literal["cosine", "ip", "l2"]
    file_path: str | None = None     # populated when source="bakeoff_file"


class Capabilities(BaseModel):
    # existing fields...
    chunk_store_backend: Literal["memory", "sqlite", "postgres", "mariadb", "clickhouse"] | None
    vector_enabled: bool
    hybrid_enabled: bool
    chunkshop_installed: bool
    chunkshop_version: str | None
    bakeoff_summary: BakeoffSummary | None
    task_backend: str | None
```

## Vector Dimension + Similarity Resolution

Resolved at `Stele.__init__` time in this order:

```
1. Bakeoff config (highest priority)
   - if indexing.bakeoff_path is set and the file loads cleanly:
     vector_dim ← bakeoff.embedder.dim
     similarity ← bakeoff.similarity

2. Embedder auto-detection (fallback when no bakeoff)
   - on first chunk write OR on capabilities() call:
     run a probe embedding: chunk_store.embed("__stele_probe__")
     vector_dim ← len(probe_vector)
     similarity ← config.indexing.similarity (default "cosine")
   - cache the detected values on the ChunkStore instance
   - report via Capabilities.bakeoff_summary.source = "auto_detected"

3. Hard default (last resort, memory backend without an embedder)
   - vector_dim ← 384
   - similarity ← "cosine"
   - report via Capabilities.bakeoff_summary.source = "default"
```

Resolved values surfaced in `Capabilities.bakeoff_summary` so users can
see which path won.

## File Layout

### New files

| Path | Responsibility |
|---|---|
| `src/stele/indexing/chunkshop_adapter.py` | Translates between Stele's chunk_id format and Chunkshop's row schema; lazy-imports `chunkshop` |
| `src/stele/indexing/bakeoff.py` | `BakeoffConfig` model + loader + overlay-onto-`IndexingConfig` logic |
| `src/stele/indexing/async_queue.py` | `AsyncChunkIndexer` — submits work to `TaskBackend`; provides `indexing_status` lookup |
| `src/stele/indexing/task_backend/__init__.py` | Package marker |
| `src/stele/indexing/task_backend/base.py` | `TaskBackend` Protocol + `IndexTask` + `TaskStatus` |
| `src/stele/indexing/task_backend/in_process.py` | `InProcessTaskBackend` — `threading.Thread` + `queue.Queue` |
| `src/stele/indexing/task_backend/redis.py` | `RedisTaskBackend` — `CapabilityError` stub |
| `src/stele/indexing/task_backend/celery.py` | `CeleryTaskBackend` — `CapabilityError` stub |
| `src/stele/storage/chunk_store/__init__.py` | Package marker |
| `src/stele/storage/chunk_store/base.py` | `ChunkStore` Protocol (`write`, `delete`, `vector_search`, `keyword_search`, `embed`, `dim`, `similarity`) |
| `src/stele/storage/chunk_store/memory.py` | In-process chunks + numpy embeddings + cosine; no chunkshop required |
| `src/stele/storage/chunk_store/sqlite.py` | SQLite via `chunkshop[sqlite]`; deterministic keyword fallback when chunkshop missing |
| `src/stele/storage/chunk_store/postgres.py` | Postgres via chunkshop core pg sink (pgvector); no extra — psycopg is a core chunkshop dep |
| `src/stele/storage/chunk_store/mariadb.py` | MariaDB via `chunkshop[mariadb]` (ships in 0.4.1) |
| `src/stele/storage/chunk_store/clickhouse.py` | ClickHouse via `chunkshop[clickhouse]` (ships in 0.4.1) |
| `src/stele/retrieval/vector.py` | `vector_search(chunk_store, query, *, limit)` — backend-agnostic facade |
| `src/stele/retrieval/hybrid.py` | `hybrid_search(...)` with RRF (default) + WeightedSum |
| `tests/unit/indexing/test_chunkshop_adapter.py` | chunk_id round-trip; no Chunkshop objects escape |
| `tests/unit/indexing/test_bakeoff.py` | Bakeoff file → overlay → Capabilities |
| `tests/unit/indexing/test_async_queue.py` | pending → indexed transition; failure path |
| `tests/unit/indexing/test_task_backend.py` | In-process implementation; stubs raise CapabilityError |
| `tests/unit/storage/test_chunk_store_<backend>.py` × 5 | Per-backend write + read + vector top-K |
| `tests/unit/retrieval/test_vector.py` | Vector search hits expected fixtures |
| `tests/unit/retrieval/test_hybrid.py` | RRF + weighted-sum merging |
| `tests/unit/retrieval/test_hybrid_quality.py` | **Load-bearing:** hybrid recall@5 ≥ max(components) − 0.05 |
| `tests/unit/retrieval/test_capabilities.py` | Capabilities reports chunkshop version, task_backend, bakeoff source |
| `tests/contract/test_vector_contract.py` | Parametrized across all 5 backends |
| `tests/contract/test_indexing_modes_contract.py` | sync/async/skip × memory + sqlite + postgres |
| `tests/unit/recall/test_artifact_search_vector.py` | Phase 3 integration |
| `tests/unit/indexing/test_dim_resolution.py` | Bakeoff → auto-detect → default cascade |
| `tests/fixtures/recall/hybrid_held_out_set.json` | ≥20 query/relevant-chunk pairs |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | Pin `chunkshop[all-backends] @ git+https://github.com/yonk-labs/chunkshop.git@v0.4.1#subdirectory=python` (immutable tag; not on PyPI; Postgres is core, no [postgres] extra) |
| `src/stele/core/config.py` | Extend `IndexingConfig` (`bakeoff_path`, `similarity`, `vector_dim`, `hybrid_method`, `hybrid_weights`, `hybrid_rrf_k`, `task_backend`, `task_backend_dsn`); extend `RetrievalConfig.default_mode` |
| `src/stele/core/types.py` | `RetrievalMode = Literal["keyword", "vector", "hybrid"]` |
| `src/stele/core/stash.py` | `Stele.search(mode=...)`; `Stele.indexing_status(artifact_id)`; `Stele.capabilities()` expanded; wire `_chunk_store` + `_async_indexer` + bakeoff overlay at construction |
| `src/stele/core/artifact.py` | Extend `Capabilities` model with chunkshop / bakeoff / task_backend fields |
| `src/stele/indexing/queue.py` | `SyncChunkIndexer` writes through `ChunkStore`; `NoOpIndexer` unchanged |
| `src/stele/indexing/chunk_index.py` | Keeps role as in-memory + chunkshop-absent fallback (no API change) |
| `src/stele/indexing/job.py` | Extend `IndexResult.status` to include `"pending"` |
| `src/stele/retrieval/{memory,sqlite,postgres,mariadb,clickhouse}.py` | Each grows `vector_search` and `hybrid_search` paths that delegate to the corresponding `ChunkStore` |
| `src/stele/__init__.py` | Re-export `BakeoffConfig`, `BakeoffSummary`, `TaskStatus`, expand `Capabilities` re-export |

### Untouched (locked)

| Path | Why locked |
|---|---|
| `src/stele/core/memory.py`, `memory_record.py` | Phase 1 surface; recall uses it via Phase 3, not Phase 4 |
| `src/stele/extraction/*` | Phase 2 surface |
| `src/stele/recall/*` | Phase 3 surface — Phase 4 changes `Stele.search` internals only |
| `src/stele/pii/*` | Consumed; never re-scrubbed |
| `src/stele/storage/{memory,sqlite,postgres,mariadb,clickhouse}.py` (artifact stores) | Phase 1 contract — Phase 4 adds a sibling `chunk_store/` subpackage |

## Data Flow

### Write path (indexing)

```
CALLER
   │
   │ stele.store(data="...", namespace="default")
   ▼
Stele.store(...)
   │ store artifact → existing artifact backend  (Phase 1)
   │ scrub summary → existing PII layer          (Phase 1)
   ▼
indexing dispatch (config.indexing.mode):

   ┌── "skip" ──► NoOpIndexer → IndexResult(status="skipped"). Done.
   │
   ├── "sync" ──► SyncChunkIndexer.index_now(artifact)
   │              │
   │              │ assert text is PII-scrubbed (defensive boundary check)
   │              ▼
   │              ChunkStore.write(artifact)
   │              │   ┌── memory:     in-process numpy + chunks dict
   │              │   ├── sqlite:     chunkshop[all-backends] sqlite sink
   │              │   ├── postgres:   chunkshop core pg sink (pgvector; psycopg is core)
   │              │   ├── mariadb:    chunkshop[all-backends] mariadb sink
   │              │   └── clickhouse: chunkshop[all-backends] clickhouse sink
   │              ▼
   │              IndexResult(status="indexed", chunk_count=N)
   │
   └── "async" ─► AsyncChunkIndexer.submit(artifact)
                   │
                   │ TaskBackend.submit(IndexTask(artifact_id, ...))
                   │   ┌── in_process: queue.Queue → worker Thread runs index_now
                   │   ├── redis:      CapabilityError
                   │   └── celery:     CapabilityError
                   ▼
                   IndexResult(status="pending", task_id=...)
                   (later, when worker completes:)
                   TaskStatus(task_id) → "succeeded" / "failed"
```

### Read path (retrieval)

```
CALLER
   │
   │ stele.search(query="dark mode", mode="hybrid", reference=None)
   ▼
Stele.search(...)
   │ resolve mode: explicit > RetrievalConfig.default_mode > "keyword"
   ▼
dispatch on mode:

   ┌── "keyword" ──► existing per-backend RetrievalBackend.search (Phase 1 path)
   │
   ├── "vector" ──► retrieval/vector.vector_search(chunk_store, query, *, limit, reference=None)
   │                 │ embed query: chunk_store.embed(query)
   │                 │ chunk_store.vector_search(query_vec, limit, reference_filter=reference)
   │                 │ chunks → SearchHit(kind="chunk", retrieval_mode="vector", ...)
   │                 ▼
   │                 list[SearchHit]
   │
   └── "hybrid" ──► retrieval/hybrid.hybrid_search(...)
                     │ keyword_hits = backend.search(query, limit*2)
                     │ vector_hits  = chunk_store.vector_search(query_vec, limit*2)
                     │ merge per HybridConfig.method:
                     │   ┌── "rrf":          reciprocal rank fusion, k=60 (configurable)
                     │   └── "weighted_sum": w_k * keyword + w_v * vector
                     │ retrieval_mode="hybrid"; metadata["sources"]=["keyword","vector"]
                     ▼
                     list[SearchHit] (sorted desc, deduped by (artifact_id, chunk_id))
```

### Invariants

- **PII assertion at write time, never re-scrub at read.** `ChunkStore.write`
  asserts text is already scrubbed (defensive boundary check); strategies
  do not re-scrub at search time.
- **No Chunkshop objects escape.** Translation between Chunkshop's row
  schema and Stele's `SearchHit` happens in `chunkshop_adapter.py` and
  the per-backend wrappers. No Chunkshop type appears in public Stele API.
- **Hybrid degrades-with-warning.** If vector path raises, hybrid falls
  back to keyword + `metadata["hybrid_degraded"]=True`. Symmetric for
  keyword failures.
- **Async indexing fails-loudly.** If `TaskBackend.submit` raises, that's
  a hard error — never silently fall back to sync. Async is configuration
  intent.

## Configuration

### Extensions to `core/config.py`

```python
class IndexingConfig(BaseModel):
    # existing fields kept...
    bakeoff_path: str | None = None
    similarity: Literal["cosine", "ip", "l2"] = "cosine"
    vector_dim: int | None = None                            # None = auto-detect
    hybrid_method: Literal["rrf", "weighted_sum"] = "rrf"
    hybrid_weights: dict[str, float] = Field(
        default_factory=lambda: {"keyword": 0.5, "vector": 0.5}
    )
    hybrid_rrf_k: int = 60
    task_backend: Literal["in_process", "redis", "celery"] = "in_process"
    task_backend_dsn: str | None = None


class RetrievalConfig(BaseModel):
    default_mode: RetrievalMode = "keyword"
```

Pydantic validators reject:
- `hybrid_weights` whose keys aren't `{"keyword", "vector"}` or whose sum
  is zero
- `hybrid_method="weighted_sum"` with both weights at zero
- `task_backend in {"redis", "celery"}` with no `task_backend_dsn`
- `task_backend="in_process"` with a non-None `task_backend_dsn` (warns,
  doesn't reject — ignored)
- `vector_dim` <= 0 when set explicitly

## Error Handling

| Condition | Behavior |
|---|---|
| `chunkshop` not installed AND backend ≠ `memory` AND `indexing.mode ≠ "skip"` | `OptionalDependencyError("chunkshop+<backend> required; pip install 'stele-core[chunkshop,<backend>]'")` at `Stele.__init__` |
| `chunkshop` installed but per-backend extra missing | `OptionalDependencyError` with exact pip install line, at `Stele.__init__` |
| `bakeoff_path` set but file missing | `ConfigError(f"bakeoff_path {p!r} does not exist")` at `Stele.__init__` |
| `bakeoff_path` set but parse fails | `ConfigError(f"bakeoff config invalid: {pydantic_msg}")` — fail fast |
| Embedder auto-detection fails | `BackendError("embedder probe failed: <cause>; set IndexingConfig.vector_dim or provide a bakeoff file")` |
| `mode="vector"` against memory backend without an embedder | Same as above — surface early at first chunk write |
| `mode="hybrid"` when vector path raises | Degrade to keyword-only with warning + `SearchHit.metadata["hybrid_degraded"]=True` |
| `mode="hybrid"` when keyword path raises | Symmetric — degrade to vector |
| `TaskBackend.submit` raises | `BackendError("async indexing submit failed: <cause>")` — do not silently fall back to sync |
| `task_backend in {"redis", "celery"}` at `Stele.__init__` | `CapabilityError("redis task backend not implemented; use in_process or implement TaskBackend Protocol")` — before first submit |
| Async-indexed artifact searched while pending | Search succeeds with whatever's already indexed; `SearchHit.metadata["indexing_status"]="pending"` on relevant hits; no exception |
| Vector dim mismatch (query vs chunks) | `BackendError("vector dim mismatch: query=N, chunks=M")` at first vector search after mismatch detected |

## Success Criteria

- **SC-001:** `RetrievalMode` expanded to `Literal["keyword", "vector", "hybrid"]`;
  existing `mode="keyword"` callers continue working. Verified by
  `tests/unit/core/test_types.py` (new) + existing Phase 1 retrieval tests.
- **SC-002:** `IndexingConfig` extended with `bakeoff_path`, `similarity`,
  `vector_dim`, `hybrid_method`, `hybrid_weights`, `hybrid_rrf_k`,
  `task_backend`, `task_backend_dsn`. Pydantic validators enforce the
  rules in §Configuration. Verified by `tests/unit/core/test_config.py`.
- **SC-003:** `BakeoffConfig`, `BakeoffEmbedder`, `BakeoffChunker`,
  `BakeoffSummary` models exist with the fields specified. Verified by
  `test_bakeoff.py`.
- **SC-004:** `bakeoff.load(path)` accepts JSON and YAML; missing file or
  parse failure raises `ConfigError` at `Stele.__init__`. Verified by
  `test_bakeoff.py`.
- **SC-005:** Bakeoff overlay applies at `Stele.__init__` and
  `Capabilities.bakeoff_summary.source` becomes `"bakeoff_file"`.
  Verified by `test_bakeoff.py`.
- **SC-006:** When no bakeoff is configured, the embedder probe at first
  chunk write produces a `vector_dim` and the cached value is surfaced
  via `Capabilities.bakeoff_summary.source = "auto_detected"`. Verified
  by `test_dim_resolution.py`.
- **SC-007:** When neither bakeoff nor embedder is available (memory
  backend, default config), `vector_dim=384` and `similarity="cosine"`
  are used; `Capabilities.bakeoff_summary.source = "default"`. Verified
  by `test_dim_resolution.py`.
- **SC-008:** `ChunkStore` Protocol exists with `write`, `delete`,
  `vector_search`, `keyword_search`, `embed`, `dim`, `similarity`
  methods. Verified by `test_chunk_store_<backend>.py` × 5.
- **SC-009:** `InProcessChunkStore` (memory backend) implements all
  Protocol methods using numpy + dict storage; does NOT require
  chunkshop. Verified by `test_chunk_store_memory.py`.
- **SC-010:** `SQLiteChunkStore`, `PostgresChunkStore`,
  `MariaDBChunkStore`, `ClickHouseChunkStore` lazy-import their matching
  Chunkshop adapter and raise `OptionalDependencyError` with exact pip
  hint when the matching extra is missing. Verified by per-backend tests.
- **SC-011:** `chunkshop_adapter.py` translates between Stele's
  `{artifact_id}:{ordinal}` chunk_id and Chunkshop's row schema; no
  Chunkshop-native objects appear in `SearchHit`. Verified by
  `test_chunkshop_adapter.py`.
- **SC-012:** `vector_search(chunk_store, query, *, limit, reference=None)`
  returns top-K `SearchHit` with `retrieval_mode="vector"`. Verified by
  `test_vector.py`.
- **SC-013:** `hybrid_search(...)` merges keyword + vector hits via
  RRF (default) or weighted-sum; produces `retrieval_mode="hybrid"`
  with `metadata["sources"]=["keyword","vector"]`. Verified by
  `test_hybrid.py`.
- **SC-014:** **Load-bearing.** Hybrid recall@5 on the held-out fixture
  set is at least `max(vector_recall@5, keyword_recall@5) − 0.05`.
  Verified by `test_hybrid_quality.py`. Floor configurable via env
  `STELE_HYBRID_FLOOR`.
- **SC-015:** `Stele.search(query, mode="vector")` and
  `Stele.search(query, mode="hybrid")` work end-to-end across the 5
  backends. Verified by `test_vector_contract.py` parametrized across
  memory + sqlite + postgres + mariadb (when available) + clickhouse
  (when available).
- **SC-016:** `TaskBackend` Protocol exists with `submit`, `status`,
  `close`. Verified by `test_task_backend.py`.
- **SC-017:** `InProcessTaskBackend` uses `threading.Thread` +
  `queue.Queue`; status transitions `pending → running → succeeded |
  failed` are observable via `status(task_id)`. Verified by
  `test_task_backend.py`.
- **SC-018:** `RedisTaskBackend` and `CeleryTaskBackend` raise
  `CapabilityError` with an actionable message. Verified by
  `test_task_backend.py`.
- **SC-019:** `Stele.store(...)` with `indexing.mode="async"` returns
  immediately; `IndexResult.status="pending"`; later transitions to
  `"indexed"` via the worker. Verified by `test_async_queue.py`.
- **SC-020:** `Stele.indexing_status(artifact_id)` returns the current
  `IndexResult`. Verified by `test_async_queue.py`.
- **SC-021:** Search against an artifact whose chunks are still being
  indexed succeeds; relevant hits carry
  `SearchHit.metadata["indexing_status"]="pending"`. Verified by
  `test_async_queue.py`.
- **SC-022:** `mode="hybrid"` when vector path raises returns keyword-only
  hits with `metadata["hybrid_degraded"]=True`. Symmetric for keyword.
  Verified by `test_hybrid.py`.
- **SC-023:** `Capabilities` reports `chunkshop_installed`,
  `chunkshop_version`, `chunk_store_backend`, `vector_enabled`,
  `hybrid_enabled`, `task_backend`, and `bakeoff_summary`. Verified by
  `test_capabilities.py`.
- **SC-024:** Phase 3's `ArtifactSearchStrategy` picks up
  `mode="vector"` and `mode="hybrid"` via `RetrievalConfig.default_mode`
  without code changes in `src/stele/recall/`. Verified by
  `test_artifact_search_vector.py`.
- **SC-025:** Existing keyword-only retrieval (Phase 1 tests) still
  passes — no regression. Verified by re-running existing
  `tests/contract/test_retrieval_contract.py`.
- **SC-026:** PII assertion at chunk write time fails-loud when a chunk
  text contains unscrubbed PII patterns (defensive boundary check, not
  re-scrub). Verified by `test_chunk_store_<backend>.py` PII case.

## Drift Checkpoints

- **⛔ DC-001** (after Tasks introducing the 5 chunk stores):
  ```
  grep -rn 'chunkshop\.[a-z_]*' src/stele/retrieval/ src/stele/recall/
  ```
  Expected: empty. Chunkshop imports must only appear in
  `src/stele/indexing/` and `src/stele/storage/chunk_store/`. No leak
  into retrieval or recall.

- **⛔ DC-002** (after async lands):
  ```
  grep -rn 'threading\.\|queue\.Queue\|asyncio\.' src/stele/retrieval/ src/stele/recall/
  ```
  Expected: empty. Concurrency primitives must only appear in
  `src/stele/indexing/task_backend/`.

- **⛔ DC-003** (after hybrid lands): run
  `tests/unit/retrieval/test_hybrid_quality.py`. Must pass with default
  floor (0.05). If it fails outside the floor, the implementation isn't
  ready to ship.

- **⛔ DC-004** (after bakeoff lands): start `Stele(...)` with and without
  `bakeoff_path` set.
  `Capabilities.bakeoff_summary.source` must be `"bakeoff_file"` in the
  first run and `"auto_detected"` or `"default"` in the second.

- **⛔ DC-FINAL**: every SC-001..SC-026 has a passing test cited;
  Out-of-Scope verified untouched.

## Out of Scope

- **Reranking** (cross-encoder, MMR, learned rerankers). Phase 4 ships
  hybrid via score fusion only.
- **Multi-vector / ColBERT-style late-interaction.** Single-vector per
  chunk only.
- **Streaming embedder API.** Sync per-chunk only.
- **Per-query embedder selection.** Embedder is global per Stele instance.
- **Reindex / migration tooling.** If users change embedder/dim/similarity,
  Phase 4 documents the breakage but doesn't auto-reindex.
- **Vector quantization** (PQ, scalar). Default float embeddings only.
- **GraphRAG / multi-hop retrieval.** Phase 5 (pg-raggraph).
- **Memory-row vectorization.** Phase 4 indexes artifacts only. Memory
  retrieval stays keyword-only (Phase 1's `Memory.search` + Phase 3's
  `MemorySearchStrategy`).
- **CLI `stele bakeoff run`.** Phase 4 *consumes* bakeoff results; running
  bakeoff is Chunkshop's CLI.
- **CLI `stele reindex <artifact>`.** Out of scope; follow-up.
- **Async via asyncio event loop.** `InProcessTaskBackend` uses
  `threading.Thread` only.
- **Cross-namespace vector search.** Vector search respects existing
  namespace + session_id filters; no cross-namespace federation.
- **Real Redis or Celery task backends.** Phase 4 ships
  `CapabilityError` stubs only.
- **MariaDB/ClickHouse vector retrieval before the Chunkshop branch is
  released.** Plan Task 0 verifies the installed Chunkshop version
  includes these adapters and skips MariaDB/ClickHouse tasks gracefully
  if not.

## Testing Requirements Summary

| Suite | Path | Anchors |
|---|---|---|
| Types | `tests/unit/core/test_types.py` | SC-001 |
| Config | `tests/unit/core/test_config.py` | SC-002 |
| Bakeoff | `tests/unit/indexing/test_bakeoff.py` | SC-003, SC-004, SC-005 |
| Dim resolution | `tests/unit/indexing/test_dim_resolution.py` | SC-006, SC-007 |
| Chunkshop adapter | `tests/unit/indexing/test_chunkshop_adapter.py` | SC-011 |
| Chunk store per-backend | `tests/unit/storage/test_chunk_store_<backend>.py` × 5 | SC-008, SC-009, SC-010, SC-026 |
| Vector retrieval | `tests/unit/retrieval/test_vector.py` | SC-012 |
| Hybrid retrieval | `tests/unit/retrieval/test_hybrid.py` | SC-013, SC-022 |
| Hybrid quality | `tests/unit/retrieval/test_hybrid_quality.py` | SC-014 (load-bearing) |
| Vector contract | `tests/contract/test_vector_contract.py` | SC-015 |
| Task backend | `tests/unit/indexing/test_task_backend.py` | SC-016, SC-017, SC-018 |
| Async queue | `tests/unit/indexing/test_async_queue.py` | SC-019, SC-020, SC-021 |
| Indexing modes | `tests/contract/test_indexing_modes_contract.py` | sync/async/skip × 3 backends |
| Capabilities | `tests/unit/retrieval/test_capabilities.py` | SC-023 |
| Phase 3 integration | `tests/unit/recall/test_artifact_search_vector.py` | SC-024 |
| Phase 1 regression | existing `tests/contract/test_retrieval_contract.py` | SC-025 |

## Cross-References

- Phase 1 / 2 / 3 source-of-truth files (consumed, not modified):
  - `src/stele/core/stash.py` — `Stele.store`, `Stele.search`,
    `Stele.fetch`, `Stele.memory`, `Stele.extract`, `Stele.recall`;
    Phase 4 adds `Stele.indexing_status`, extends `Stele.search` with
    `mode=`.
  - `src/stele/indexing/chunk_index.py`, `queue.py`, `job.py` — existing
    in-process indexing; Phase 4 keeps as fallback path.
  - `src/stele/retrieval/{memory,sqlite,postgres,mariadb,clickhouse}.py`
    — existing keyword retrieval; Phase 4 adds sibling vector/hybrid
    paths that delegate to `ChunkStore`.
  - `src/stele/recall/artifact_search.py` — Phase 3 strategy that picks
    up vector/hybrid via `RetrievalConfig.default_mode`.
- Strategy docs:
  - `docs/sovereign-memory-system-plan.md:629-634` — Phase 4 scope
  - `docs/prd-sovereign-stele.md:349-352` — Phase 4 summary
  - `docs/specs/implementation-execution-plan.md` M10 + M11 — original
    milestone framing
- Phase 1/2/3 plan/spec precedent (format + gate discipline):
  - `docs/superpowers/plans/2026-05-12-phase1-memory-supersession.md`
  - `docs/superpowers/plans/2026-05-13-phase2-deterministic-extraction.md`
  - `docs/superpowers/specs/2026-05-13-phase3-policy-driven-recall-design.md`
  - `/tmp/stele-phase4-planning/` — this design's local sandbox (NOT in git)

## Location Note

This spec lives at `/tmp/stele-phase4-planning/` per user instruction.
It is **not committed to git**. When the Phase 2 agent and Phase 3 plan
are done shifting branch state, the user will decide where to commit
the Phase 4 spec + plan (likely a dedicated `phase4-chunkshop-indexing`
branch off main, following the Phase 3 pattern).
