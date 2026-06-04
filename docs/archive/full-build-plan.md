# Stele Full Build Plan

## TL;DR

Build `stele` as a Python 3.12+ package that structurally intercepts large tool outputs, stores exact artifacts by reference, summarizes them with `lede`, scrubs PII from model-visible surfaces, and retrieves relevant chunks through backend-native retrieval adapters. The core product is the interception/reference/retrieval facade; memory, SQLite, MariaDB, Postgres, and ClickHouse are storage/retrieval backends; `chunkshop` provides cross-database chunking/embedding/vector tables; `pg-raggraph` is an optional richer Postgres retrieval plugin, not the global retrieval layer.

This plan is ordered to keep every milestone shippable. Start with exact artifact storage and structural interception. Add SQL stores. Add backend-native keyword retrieval. Add Chunkshop vector retrieval. Add pg-raggraph only after the generic retrieval contract is already working.

## Build-Ready Spec Package

The implementation handoff lives in [`docs/specs/`](./specs/README.md). Use those files as the authoritative build checklist:

- [`product-api-spec.md`](./specs/product-api-spec.md): public API, object models, PII policy, reference rules, integration behavior, and observability.
- [`backend-retrieval-spec.md`](./specs/backend-retrieval-spec.md): backend schemas, capability matrix, retrieval semantics, Chunkshop mapping, and pg-raggraph isolation.
- [`testing-benchmark-spec.md`](./specs/testing-benchmark-spec.md): required test layers, contract suites, benchmark suites, CI gates, and report formats.
- [`implementation-execution-plan.md`](./specs/implementation-execution-plan.md): milestone order, target files, tasks, and exit criteria from scaffold through release hardening.
- [`build-backlog.md`](./specs/build-backlog.md): ticket-sized implementation tasks for the first build wave.

## Goals

- Preserve the core product behavior: large tool output becomes `summary + reference`, full output remains fetchable.
- Make retrieval backend-agnostic at the facade level.
- Support memory, SQLite, MariaDB, Postgres, and ClickHouse without pretending they have identical semantics.
- Use `lede` for deterministic hot-path summaries.
- Use `chunkshop` for chunking, embeddings, vector table writes, and baseline vector top-k across SQL backends.
- Use `pg-raggraph` only for Postgres graph/time-aware retrieval when explicitly enabled.
- Keep core install light and optional dependencies explicit.
- Make every integration test prove the same public contract against every backend it supports.
- Prove four product goals with benchmarks: token reduction, long-term recall, PII scrubbing, and overall performance.

## Non-Goals

- Do not rebuild a general-purpose RAG framework.
- Do not port V1 custom embedding providers, LLM summarizers, or Postgres hybrid search.
- Do not require pg-raggraph for non-Postgres users.
- Do not make ClickHouse behave like an OLTP database.
- Do not expose Chunkshop or pg-raggraph native result objects from the public API.

## Package Shape

```text
src/stele/
  __init__.py
  py.typed

  core/
    artifact.py
    reference.py
    reference_auth.py
    lifecycle.py
    session.py
    stash.py
    config.py
    exceptions.py
    capabilities.py

  summary/
    base.py
    lede_adapter.py

  storage/
    base.py
    memory.py
    sqlite.py
    mariadb.py
    postgres.py
    clickhouse.py
    migrations/

  retrieval/
    base.py
    results.py
    rank.py
    memory.py
    sqlite.py
    mariadb.py
    postgres.py
    clickhouse.py
    pg_raggraph.py

  indexing/
    queue.py
    job.py
    chunkshop_adapter.py
    chunkshop_direct.py

  pii/
    base.py
    regex.py
    presidio.py
    scrubber.py

  interception/
    detector.py
    thresholds.py
    response.py
    wrapper.py

  integrations/
    langchain/
      middleware.py
      tools.py
    mcp/
      server.py
      tools.py

  cli/
    main.py
    migrate.py
    inspect.py
    reap.py

tests/
  unit/
  contract/
  integration/
  perf/
```

## Dependency Extras

Core dependencies:

```text
pydantic>=2,<3
pyyaml>=6,<7
lede>=0.3,<0.4
```

Optional extras:

| Extra | Dependencies | Purpose |
|---|---|---|
| `sqlite` | none beyond stdlib | SQLite artifact store + FTS5 |
| `sqlite-vec` | `sqlite-vec`, `chunkshop[sqlite]` | SQLite vector retrieval |
| `mariadb` | `pymysql`, `chunkshop[mariadb]` | MariaDB artifact store + vector retrieval |
| `postgres` | `psycopg[binary]`, `pgvector`, `chunkshop` | Postgres artifact store + baseline vector retrieval |
| `pg-raggraph` | `pg-raggraph` | optional Postgres graph/time-aware retrieval |
| `clickhouse` | `clickhouse-connect`, `chunkshop[clickhouse]` | ClickHouse artifact store + vector retrieval |
| `chunkshop` | `chunkshop>=0.4,<0.5` | shared chunking/vector indexing |
| `langchain` | `langchain`, `langchain-core` | structural LangChain middleware and tools |
| `mcp` | `mcp` | advisory MCP tools |
| `pii` | optional `presidio-analyzer`, `presidio-anonymizer`, `spacy` | stronger PII detection/scrubbing |
| `dev` | pytest, ruff, mypy, testcontainers | tests and CI |
| `all-backends` | sqlite-vec, mariadb, postgres, clickhouse | backend integration work |
| `full` | all-backends, pg-raggraph, langchain, mcp | complete local dev install |

Version reality check: local `chunkshop-v4` and `pg-raggraph` require Python 3.12+. The rebuild should not support Python 3.10 unless those projects add compatible releases.

## Core Contracts

### Artifact

```python
class Artifact(BaseModel):
    id: str
    reference: str
    namespace: str
    session_id: str | None
    content: str
    content_type: Literal["text", "json", "table", "code_diff", "blob"]
    metadata: dict[str, Any]
    summary: str
    lifecycle: Literal["session", "ttl", "manual"]
    expires_at: datetime | None
    created_at: datetime
```

### StorageBackend

Exact artifact CRUD. This is not semantic retrieval.

```python
class StorageBackend(Protocol):
    def store(self, artifact: Artifact) -> Artifact: ...
    def fetch(self, reference: str) -> Artifact: ...
    def try_fetch(self, reference: str) -> Artifact | None: ...
    def delete(self, reference: str) -> bool: ...
    def list(self, *, namespace: str | None = None, session_id: str | None = None, limit: int = 100) -> list[Artifact]: ...
    def cleanup_expired(self, *, limit: int = 1000) -> int: ...
    def close(self) -> None: ...
```

### RetrievalBackend

Backend-native search over stored artifacts/chunks.

```python
class RetrievalBackend(Protocol):
    def search_artifact(self, reference: str, query: str, *, limit: int = 10, mode: str | None = None) -> list[SearchHit]: ...
    def query_namespace(self, namespace: str, query: str, *, limit: int = 10, mode: str | None = None) -> list[SearchHit]: ...
    def capabilities(self) -> RetrievalCapabilities: ...
```

### SearchHit

```python
class SearchHit(BaseModel):
    artifact_id: str
    reference: str
    chunk_id: str | None = None
    text: str
    score: float
    retrieval_mode: Literal["keyword", "vector", "hybrid", "graph"]
    metadata: dict[str, Any] = {}
```

### Indexer

Background work that turns artifacts into retrievable chunks. The store path must not wait on embedding/model downloads by default.

```python
class Indexer(Protocol):
    def submit(self, artifact: Artifact) -> IndexJob: ...
    def index_now(self, artifact: Artifact) -> IndexResult: ...
    def status(self, artifact_id: str) -> IndexStatus: ...
```

### PIIScrubber

All model-visible surfaces route through this when PII scrubbing is enabled.

```python
class PIIScrubber(Protocol):
    def scrub(self, text: str, *, context: dict[str, Any] | None = None) -> ScrubResult: ...
```

Default provider is lightweight regex. Presidio is optional.

## Public API

```python
stash = Stele.from_config("memory-stash.yaml")

stored = stash.store(
    content,
    namespace="tools/sql",
    content_type="json",
    metadata={"tool": "query_customers"},
    lifecycle="ttl",
    ttl_seconds=3600,
)

stored.reference
stored.summary

artifact = stash.fetch(stored.reference)
hits = stash.search(stored.reference, "Q4 enterprise churn")
hits = stash.query("what changed this week?", namespace="tools/sql")
stash.delete(stored.reference)
```

`store()` returns a small `StoredArtifact` view, not the full raw content:

```python
class StoredArtifact(BaseModel):
    reference: str
    summary: str
    content_type: str
    byte_size: int
    token_estimate: int
    indexed: Literal["queued", "ready", "unsupported"]
```

## Backend Semantics

| Backend | Exact store/fetch | Keyword | Vector | Hybrid | Graph/time-aware | Notes |
|---|---:|---:|---:|---:|---:|---|
| Memory | yes | scan | no | no | no | no persistence |
| SQLite | yes | FTS5 | sqlite-vec via chunkshop | RRF | no | single-user/local |
| MariaDB | yes | FULLTEXT/LIKE | chunkshop/MariaDB vector | RRF | no | MariaDB 11.7+ for vector |
| Postgres | yes | FTS | pgvector via chunkshop | RRF | pg-raggraph optional | richest backend |
| ClickHouse | yes | limited/filter | chunkshop/CH vector | optional | no | append-heavy; delete semantics differ |

Default retrieval mode:

- Memory: `keyword`
- SQLite: `hybrid` if vector enabled, else `keyword`
- MariaDB: `hybrid` if vector enabled, else `keyword`
- Postgres: `graph` if pg-raggraph enabled, else `hybrid`
- ClickHouse: `vector` if vector enabled, else `keyword`

## Data Model

### Shared Artifact Table

Every SQL backend gets the same logical artifact table:

```text
memory_stash_artifacts
  artifact_id       text primary key
  reference_uri     text unique not null
  namespace         text not null
  session_id        text null
  content           text not null
  content_type      text not null
  metadata          backend JSON type
  summary           text not null
  lifecycle         text not null
  expires_at        timestamp null
  created_at        timestamp not null
```

### Shared Chunk Metadata Table

Use this to map Chunkshop rows back to artifacts regardless of backend.

```text
memory_stash_chunks
  chunk_id          text primary key
  artifact_id       text not null
  reference_uri     text not null
  namespace         text not null
  seq_num           int not null
  text              text not null
  embedded_text     text not null
  metadata          backend JSON type
  created_at        timestamp not null
```

Chunkshop sink tables may duplicate some of this shape. That is acceptable if the adapter has a deterministic mapping from Chunkshop `(doc_id, seq_num)` to `memory_stash_chunks.chunk_id`.

## Milestone Plan

### M0: Repository Scaffold

Goal: create the package skeleton and quality gates before feature work.

Deliverables:

- `pyproject.toml`
- `src/stele/`
- `tests/`
- CI-equivalent local commands documented
- import smoke test

Tasks:

- Create hatchling or setuptools build config.
- Set Python requirement to `>=3.12`.
- Add core dependencies only: pydantic, pyyaml, lede.
- Add optional extras listed above.
- Configure ruff, mypy strict, pytest.
- Add `py.typed`.
- Add `tests/unit/test_import.py`.

Acceptance:

- `python -c "import stele"` passes with only core deps.
- `ruff check`, `mypy src`, and `pytest tests/unit/test_import.py` pass.

### M1: Core Artifact, Reference, Config

Goal: establish stable internal types and reference parsing.

Tasks:

- Implement `Artifact`, `StoredArtifact`, `SearchHit`, `RetrievalCapabilities`.
- Implement `make_reference(namespace, artifact_id)` and `parse_reference(uri)`.
- Support `stele://<namespace>/<uuid>` parsing.
- Define exception taxonomy:
  - `SteleError`
  - `ConfigurationError`
  - `MissingDependencyError`
  - `InvalidReferenceError`
  - `ArtifactNotFoundError`
  - `ContentTooLargeError`
  - `CapabilityError`
  - `StorageError`
  - `RetrievalError`
- Implement config models:
  - storage backend
  - retrieval provider
  - thresholds
  - lifecycle defaults
  - indexing mode
  - signing mode
- Implement size limit default: 10 MB.

Acceptance:

- Reference parser handles nested namespaces and signed query params.
- Invalid refs raise `InvalidReferenceError`.
- Content over size limit raises `ContentTooLargeError`.
- Config validates every supported backend name.

### M2: Lede Summary Adapter

Goal: make hot-path summaries deterministic and fast.

Tasks:

- Implement `SummaryProvider` protocol.
- Implement `LedeSummaryProvider`.
- Map summary modes:
  - `fast` -> `default`
  - `balanced` -> `default`
  - `coverage` -> `coverage`
  - `manual` -> `manual`
- Return plain string summary plus optional structured metadata.
- Add content-type-specific summary wrappers for JSON/table/code-diff preview text.

Acceptance:

- Summary never exceeds configured max chars.
- Summary call works with only core deps.
- Perf test p95 under 10 ms for representative 1 KB, 10 KB, and 100 KB inputs on local runner.

### M3: Memory Backend + Facade

Goal: first complete `store -> summary/ref -> fetch` loop.

Tasks:

- Implement `MemoryBackend` with RLock.
- Implement `MemoryRetrievalBackend` with simple scoring over summary/content.
- Implement `Stele` facade:
  - `store`
  - `fetch`
  - `try_fetch`
  - `delete`
  - `list`
  - `summarize`
  - `search`
  - `query`
  - `cleanup_expired`
  - `close`
- Add session/lifecycle handling.
- Add lazy expired-artifact deletion on fetch.

Acceptance:

- Full round trip works in memory.
- TTL artifacts disappear after expiration.
- Session filtering works.
- `search(reference, query)` returns summary/content hits.
- No optional extras required.

### M4: Interception Core

Goal: make the product's main value real before adding databases.

Tasks:

- Implement content detection:
  - text
  - JSON object/array
  - tabular text/CSV-ish
  - SQL result-ish
  - unified diff/code diff
  - blob fallback
- Implement threshold policy:
  - text: 5,000 chars
  - JSON array: 20,000 chars
  - table: 10,000 chars
  - code diff: 5,000 chars
  - configurable overrides
- Implement `intercept_output(content, metadata) -> str`.
- Output format includes:
  - reference
  - byte size
  - summary
  - available retrieval commands
- Implement Python wrapper/decorator for plain functions.

Acceptance:

- Below-threshold outputs pass through.
- Above-threshold outputs are stored and replaced.
- Replacement never includes full raw content.
- Fail-open behavior: storage failure can pass through original output if configured.

### M5: LangChain Structural Middleware

Goal: preserve the structural-vs-advisory distinction from V1.

Tasks:

- Implement LangChain middleware around tool calls.
- Ensure interception happens before model-visible tool output.
- Add advisory LangChain tools:
  - `stash_fetch`
  - `stash_summarize`
  - `stash_search`
  - `stash_query`
  - `stash_delete`
- Keep middleware and tools separate.

Acceptance:

- Unit test with fake tool proves model receives replacement, not raw output.
- Tool tests prove advisory retrieval works.
- Missing LangChain extra gives friendly `MissingDependencyError`.

### M6: MCP Advisory Server

Goal: expose retrieval and storage tools for hosts that support MCP.

Tasks:

- Implement MCP server with tools:
  - `memory_stash_store`
  - `memory_stash_fetch`
  - `memory_stash_summarize`
  - `memory_stash_search`
  - `memory_stash_query`
  - `memory_stash_list`
  - `memory_stash_delete`
- Add config loading.
- Add JSON-safe errors.
- Document advisory limitation: MCP does not structurally prevent oversized tool outputs.

Acceptance:

- MCP tool calls work against memory backend.
- Malformed references return structured errors.
- Missing MCP extra gives friendly error.

### M7: SQLite Artifact Store + FTS Retrieval

Goal: first persistent backend.

Tasks:

- Implement SQLite artifact table migrations.
- Enable WAL mode.
- Add FTS5 virtual table over content/summary/chunk text.
- Implement `SQLiteBackend`.
- Implement `SQLiteRetrievalBackend` keyword search.
- Implement path safety:
  - reject symlink DB path if configured
  - optional data-dir boundary
- Add transaction boundaries for store/delete.

Acceptance:

- Storage contract tests pass against SQLite.
- Retrieval contract keyword tests pass.
- FTS query returns correct artifact/chunk.
- TTL cleanup works.

### M8: SQL Artifact Stores for MariaDB, Postgres, ClickHouse

Goal: exact artifact CRUD across all target SQL engines before vector work.

Tasks:

- Implement MariaDB artifact table and backend.
- Implement Postgres artifact table and backend.
- Implement ClickHouse artifact table and backend.
- Normalize JSON metadata handling per backend.
- Implement migrations/init:
  - SQLite: local migration ledger
  - MariaDB: migration ledger table
  - Postgres: migration ledger table
  - ClickHouse: idempotent DDL
- Add backend config models.
- Add storage contract test matrix.

Acceptance:

- Same storage contract passes for memory, SQLite, MariaDB, Postgres, ClickHouse.
- Exact `fetch(reference)` never depends on retrieval engine.
- ClickHouse delete/TTL limitations are tested and documented.

### M9: Baseline Keyword Retrieval for SQL Backends

Goal: every backend can answer `search/query` without vector dependencies.

Tasks:

- SQLite: FTS5.
- MariaDB: FULLTEXT where enabled; `LIKE` fallback for small/dev configs.
- Postgres: tsvector/FTS.
- ClickHouse: text search or metadata-filtered scan, clearly capability-flagged.
- Implement shared result normalization.
- Implement explicit mode handling:
  - `mode="keyword"`
  - unsupported modes raise `CapabilityError`
  - default mode falls back to keyword

Acceptance:

- Retrieval contract tests pass for every backend.
- `stash.search(reference, q)` searches within one artifact.
- `stash.query(namespace, q)` searches across namespace.
- Scores are normalized enough for stable tests.

### M10: Chunkshop Indexing Adapter

Goal: chunk and embed artifacts once, in a way every vector-capable backend can reuse.

Tasks:

- Implement `ChunkshopIndexingAdapter`.
- Resolve API approach:
  - preferred: call Chunkshop stage loaders directly and write through configured sink
  - fallback: use `Pipeline.ingest_text()` for backend-owned vector tables
  - future: upstream `prepare_text()` returning chunks + embeddings
- Build `CellConfig` from memory-stash config.
- Validate embedding dimension before writes.
- Map artifact ID to Chunkshop `doc_id`.
- Map Chunkshop `(doc_id, seq_num)` to `memory_stash_chunks`.
- Add indexing modes:
  - `off`
  - `background`
  - `sync`
- Add index status:
  - `queued`
  - `indexing`
  - `ready`
  - `failed`
  - `unsupported`

Acceptance:

- One artifact indexes into each enabled Chunkshop sink.
- Index status is queryable.
- Failed model download or embedding error does not break exact fetch.
- Chunk metadata maps back to artifact references.

### M11: Vector Retrieval via Chunkshop Sinks

Goal: baseline vector retrieval for SQLite, MariaDB, Postgres, and ClickHouse.

Tasks:

- Use Chunkshop sink `query_top_k(query_vec, k)`.
- Add query embedding path through Chunkshop embedder.
- Implement backend-specific vector adapters:
  - `SQLiteVectorRetrieval`
  - `MariaDBVectorRetrieval`
  - `PostgresVectorRetrieval`
  - `ClickHouseVectorRetrieval`
- Implement hybrid ranking with RRF:
  - keyword hits
  - vector hits
  - merged `SearchHit`
- Add capability flags:
  - `keyword`
  - `vector`
  - `hybrid`
  - `graph`

Acceptance:

- Vector retrieval works on each backend with testcontainers or local services.
- Hybrid returns keyword-only when vector unavailable and no explicit vector mode requested.
- Explicit `mode="vector"` raises `CapabilityError` if vector not configured.
- Query results include artifact reference and chunk text.

### M12: Postgres pg-raggraph Retrieval Plugin

Goal: add rich Postgres retrieval without infecting other backends.

Tasks:

- Implement `PgRaggraphRetrievalAdapter`.
- Support config:
  - `retrieval.provider: pg-raggraph`
  - `retrieval.mode: smart | naive | naive_boost | local | global | hybrid`
  - `retrieval.as_of`
  - `retrieval.version_filter`
- Connect to GraphRAG lazily or at startup based on config.
- Index records into pg-raggraph using `ingest_records`.
- Store memory-stash reference metadata in pg-raggraph records.
- Use direct SQL only inside adapter for exact artifact mapping if needed.
- Keep baseline Postgres retrieval available as rollback.

Acceptance:

- Postgres baseline retrieval works without pg-raggraph installed.
- pg-raggraph mode works when extra is installed and DB is configured.
- Non-Postgres backends never import pg-raggraph.
- Time/version query params are rejected with `CapabilityError` outside pg-raggraph.

### M13: PII Scrubbing

Goal: make privacy a first-class product goal rather than a benchmark side feature.

Tasks:

- Implement `PIIScrubber` protocol.
- Implement regex scrubber for core/no-heavy-deps path.
- Implement Presidio scrubber behind `[pii]` extra.
- Route every model-visible surface through scrubber when enabled:
  - interception replacement
  - summary
  - search/query hits
  - LangChain tools
  - MCP tools
  - default fetch
- Add trusted raw fetch mode for explicitly privileged callers.
- Add PII audit metadata without logging raw PII values.

Acceptance:

- Known fixture PII does not appear in model-visible outputs.
- Exact raw content remains stored and can be fetched only through trusted/raw path.
- PII benchmark reports precision, recall, F1, false positives, false negatives, leakage count, utility preservation, and scrubbing latency.

### M14: Benchmark Harness

Goal: prove the four product goals with reproducible reports.

Tasks:

- Port showcase workload generators.
- Add token reduction reports.
- Add long-term recall reports:
  - internal cross-session suite
  - external benchmark adapter for at least one of LongMemEval, LoCoMo, or PerLTQA
- Add PII reports:
  - local deterministic fixtures
  - optional PIIBench / DocPII loaders
- Add performance reports:
  - intercept/fetch/search/index latency
  - throughput
  - net latency benefit
- Emit Markdown and JSON reports.

Acceptance:

- Reports exist for token reduction, recall, PII, and performance.
- Public claims link to commands and JSON outputs.

### M15: Reference Signing and Security

Goal: make references safe enough to appear in model/tool logs.

Tasks:

- Implement HMAC signing:
  - disabled
  - optional
  - required
- Support expiry in signed refs.
- Enforce minimum key length.
- Add key rotation structure:
  - active key ID
  - accepted config keys
- Add namespace/session checks.
- Add fuzz tests for parser/signature handling.

Acceptance:

- Required signing rejects unsigned refs.
- Tampered refs fail.
- Expired refs fail.
- Optional mode accepts unsigned but verifies signed refs.

### M16: TTL Reaper and Lifecycle

Goal: lifecycle semantics work across backends.

Tasks:

- Implement `cleanup_expired()` on every backend.
- Implement CLI `memory-stash reap`.
- Implement optional background reaper thread.
- Backend-specific behavior:
  - memory: in-process delete
  - SQLite/MariaDB/Postgres: SQL delete
  - ClickHouse: documented delete/TTL strategy
  - pg-raggraph: delete indexed records or mark stale if needed
- Add session cleanup.

Acceptance:

- TTL contract tests pass per backend.
- Reaper is idempotent.
- ClickHouse behavior is explicit and test-covered.

### M17: JSONL import and export

Goal: support portable artifact import/export without magic.

Tasks:

- Export artifacts to neutral JSONL.
- Import JSONL into new backend.
- Preserve references where possible.
- Generate migration report:
  - artifacts imported
  - artifacts skipped
  - unsupported metadata
  - broken refs
- Add config migration helper:
  - alternate extras -> configured extras
  - alternate backend names -> configured backend names
  - summarization provider -> lede
  - embeddings provider -> chunkshop

Acceptance:

- Import works for memory export fixture.
- Import works for SQLite fixture.
- Postgres migration has a dry-run mode.
- Report is deterministic and human-readable.

### M18: Observability and Operations

Goal: make production behavior debuggable.

Tasks:

- Add structured logging.
- Add metrics hooks:
  - stores
  - fetches
  - interceptions
  - summaries
  - indexing jobs
  - retrieval latency
  - failures by backend
- Add audit events:
  - store
  - fetch
  - delete
  - failed signature
  - cleanup
- Add `memory-stash inspect` CLI:
  - backend status
  - capabilities
  - index queue
  - recent failures

Acceptance:

- Metrics can be disabled.
- Logs do not include raw artifact content by default.
- Inspect CLI works against memory and SQLite without services.

### M19: Documentation and Examples

Goal: make the package understandable and demoable.

Docs:

- README quickstart.
- Backend matrix.
- Structural vs advisory guide.
- Config reference.
- Retrieval modes.
- LangChain example.
- MCP example.
- Migration guide.
- Operations guide.

Examples:

- Plain Python wrapper.
- LangChain SQL tool interception.
- SQLite local app.
- MariaDB vector retrieval.
- Postgres baseline retrieval.
- Postgres pg-raggraph retrieval.
- ClickHouse archive retrieval.

Acceptance:

- Every README command is tested or has a smoke-test equivalent.
- Examples use small local fixtures.

## Test Strategy

### Unit Tests

Run on every commit:

- core models
- reference parsing/signing
- config validation
- lede adapter
- memory backend
- threshold detection
- response formatting
- rank fusion
- error taxonomy

### Contract Tests

One suite parameterized by backend:

- `store/fetch/delete/list`
- TTL cleanup
- session scoping
- namespace filtering
- keyword retrieval
- capability reporting
- unsupported explicit modes raise `CapabilityError`

Backends:

- memory always
- SQLite always
- MariaDB integration job
- Postgres integration job
- ClickHouse integration job

### Integration Tests

Use containers for:

- MariaDB 11.7+
- Postgres + pgvector
- ClickHouse 24.10+

SQLite runs in normal CI.

Tests:

- SQL DDL/migrations
- chunkshop indexing
- vector retrieval
- hybrid retrieval
- pg-raggraph plugin
- LangChain middleware
- MCP server

### Performance Tests

Initial gates:

- `store()` memory p95 under 10 ms for 10 KB.
- `store()` SQLite p95 under 30 ms for 10 KB.
- Summary p95 under 10 ms for representative samples.
- Interception replacement generation p95 under 50 ms excluding background indexing.
- Exact fetch p95 under 20 ms memory/SQLite local.
- Net latency benefit is calculated as estimated LLM input latency saved minus stash overhead.

Run perf tests separately from normal unit CI, but keep them visible.

### Quality Tests

Fixed retrieval fixtures:

- prose document
- JSON API response
- SQL result table
- code diff
- noisy tool log

For each backend:

- Store fixture.
- Index if supported.
- Query known terms.
- Assert expected artifact appears in top K.
- For hybrid/vector backends, assert vector result is not worse than keyword-only on the fixed fixture set.

### Recall Tests

- Synthetic cross-session recall at 1, 3, 5, 10, and 20 sessions.
- Temporal update tests for current vs stale facts.
- Abstention tests for absent memories.
- External benchmark adapter for LongMemEval, LoCoMo, or PerLTQA before public recall claims.

### PII Tests

- Local deterministic PII fixtures in CI.
- Optional PIIBench / DocPII subsets in release or nightly CI.
- Leakage assertions across replacement, summary, fetch, search/query, LangChain, and MCP outputs.
- Utility preservation assertions so scrubbing does not erase non-PII answer criteria.

## CI Matrix

### Required PR Checks

- ruff
- mypy
- unit tests
- memory contract tests
- SQLite contract tests
- import smoke test with core deps only

### Backend CI

Run on main and before release:

- MariaDB contract/integration
- Postgres baseline contract/integration
- Postgres pg-raggraph integration
- ClickHouse contract/integration
- Chunkshop vector retrieval matrix

### Optional Nightly

- perf suite
- larger retrieval quality suite
- migration fixtures
- dependency freshness check

## Configuration Shape

Example:

```yaml
storage:
  backend: sqlite
  path: .memory-stash/stele.db

summary:
  provider: lede
  max_chars: 500
  mode: default

interception:
  default_threshold_chars: 5000
  thresholds:
    json: 20000
    table: 10000
    code_diff: 5000
  fail_open: true

indexing:
  mode: background
  provider: chunkshop
  chunker: hierarchy
  embedder:
    provider: fastembed
    model_name: Xenova/bge-base-en-v1.5-int8

retrieval:
  default_mode: auto
  provider: native
  hybrid:
    rrf_k: 60

references:
  signing: optional
  key_env: MEMORY_STASH_SIGNING_KEY
```

Postgres with pg-raggraph:

```yaml
storage:
  backend: postgres
  dsn_env: MEMORY_STASH_PG_DSN

retrieval:
  provider: pg-raggraph
  default_mode: naive_boost
```

ClickHouse:

```yaml
storage:
  backend: clickhouse
  dsn_env: MEMORY_STASH_CH_DSN
  ttl_mode: engine_ttl

retrieval:
  provider: native
  default_mode: vector
```

## Release Plan

### 0.1.0: Core Preview

- Memory backend.
- Lede summaries.
- Direct Python API.
- Structural interception wrapper.
- No SQL.

### 0.2.0: Local Persistent

- SQLite artifact store.
- SQLite FTS retrieval.
- LangChain middleware.
- MCP advisory server.

### 0.3.0: SQL Stores

- MariaDB/Postgres/ClickHouse exact artifact stores.
- SQL contract tests.
- Backend capability reporting.

### 0.4.0: Vector Retrieval

- Chunkshop indexing.
- SQLite/MariaDB/Postgres/ClickHouse vector retrieval.
- Hybrid retrieval.

### 0.5.0: Postgres Rich Retrieval

- pg-raggraph plugin.
- Time/version query support on Postgres.
- Baseline Postgres rollback path.

### 0.6.0: Hardening

- signed references.
- TTL reaper.
- migration tools.
- observability.
- production docs.
- PII scrubbing release gate.
- benchmark reports for four product goals.

### 1.0.0: Stability

- API freeze.
- migration guide complete.
- all backend contract suites green.
- no known lifecycle gaps.
- public docs match behavior.

## Build Order Rationale

Do not start with pg-raggraph. That would make Postgres assumptions leak into the API and leave MariaDB/SQLite/ClickHouse as second-class retrofits.

Do not start with Chunkshop vector tables. Exact reference fetch and structural interception are the product's core. Vector retrieval is a retrieval upgrade, not the foundation.

Do start with memory + lede + exact fetch. That proves the contract. Then add structural interception. Then add SQL stores. Then retrieval.

## Open Design Decisions

1. Should the package name be `stele`, `memory-stash`?
2. Should references remain `stele://` forever, or should new refs use `memorystele://`?
3. Should ClickHouse hard delete be supported or documented as delayed/eventual?
4. Should Chunkshop get an upstream `prepare_text()` API before M10, or should this repo call internal stage loaders first?
5. Should pg-raggraph exact document-management APIs be upstreamed before M12?
6. Should `store()` default lifecycle be required, or default to `ttl`/`manual`?

## Definition of Done

The rebuild is done when all of these are true:

- A large LangChain tool output is structurally intercepted before the model sees it.
- The model gets a compact summary and reference.
- `fetch(reference)` returns exact original content.
- `search(reference, query)` works on memory, SQLite, MariaDB, Postgres, and ClickHouse with each backend's best available strategy.
- `query(namespace, query)` works across artifacts.
- Postgres can optionally use pg-raggraph without changing the public API.
- Core install imports without SQL/vector/MCP/LangChain dependencies.
- Backend contract tests pass for all five backends.
- JSONL import and export are documented and tested.
