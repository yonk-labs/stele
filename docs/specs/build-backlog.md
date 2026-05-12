# Build Backlog

## TL;DR

Start with the core MVP: package scaffold, models, config, reference parsing, lede summaries, regex PII scrubbing, memory backend, facade, and interception wrapper. Do not spend the first build wave on SQL, Chunkshop, pg-raggraph, MCP, or benchmark adapters. Those depend on the core contracts being stable.

## Wave 1: Runnable Core MVP

### T-001: Scaffold Package

Purpose:

- Make the repository installable and testable.

Files:

- `pyproject.toml`
- `README.md`
- `src/stele/__init__.py`
- `src/stele/py.typed`
- `tests/unit/test_import.py`

Acceptance:

- `python -c "import stele"` succeeds.
- `pytest tests/unit/test_import.py` succeeds.
- `ruff check .` and `mypy src tests` are wired, even if mypy scope is initially narrow.

Depends on:

- none

### T-002: Core Exceptions and Types

Purpose:

- Establish stable package-owned errors and enums before backend code exists.

Files:

- `src/stele/core/exceptions.py`
- `src/stele/core/types.py`
- `tests/unit/core/test_exceptions.py`

Acceptance:

- Exception hierarchy matches product spec.
- Enums/literals cover content type, lifecycle, retrieval mode, index status, and failure mode.
- No optional dependencies imported.

Depends on:

- T-001

### T-003: Artifact and Result Models

Purpose:

- Define all public return models.

Files:

- `src/stele/core/artifact.py`
- `src/stele/retrieval/results.py`
- `tests/unit/core/test_artifact_models.py`

Acceptance:

- `Artifact`, `ArtifactRecord`, `StoredResult`, `FetchResult`, `SearchHit`, `Page`, and `CleanupResult` exist.
- Digest and byte size are deterministic.
- Metadata round trips through model validation.
- Large text fixture validates without truncation.

Depends on:

- T-002

### T-004: Config Loader

Purpose:

- Load config from dict, YAML string, and file path.

Files:

- `src/stele/core/config.py`
- `tests/unit/core/test_config.py`

Acceptance:

- Minimal memory config validates.
- SQLite config validates.
- Postgres graph config validates without importing pg-raggraph.
- Invalid backend type raises `ConfigError`.
- Defaults match product spec.

Depends on:

- T-002

### T-005: Reference Parser and Signer

Purpose:

- Support `stele://` refs and optional signed refs.

Files:

- `src/stele/core/reference.py`
- `src/stele/core/reference_auth.py`
- `tests/unit/core/test_reference.py`
- `tests/unit/core/test_reference_auth.py`

Acceptance:

- Parses `stele://default/abc`.
- Parses nested namespaces.
- Parses `stele://default/abc`.
- Generates signed refs.
- Rejects tampered or expired signatures in required mode.
- Allows unsigned refs in disabled mode.

Depends on:

- T-002
- T-004

### T-006: Lede Summary Adapter

Purpose:

- Provide deterministic default summary generation.

Files:

- `src/stele/summary/base.py`
- `src/stele/summary/lede_adapter.py`
- `tests/unit/summary/test_lede_adapter.py`

Acceptance:

- Summary provider interface exists.
- `lede` adapter summarizes text.
- Max summary length is enforced.
- Summary provider failure is wrapped in package-owned exception.

Depends on:

- T-002
- T-003

### T-007: Regex PII Scrubber

Purpose:

- Provide default PII protection with no heavy deps.

Files:

- `src/stele/pii/base.py`
- `src/stele/pii/regex.py`
- `src/stele/pii/scrubber.py`
- `tests/unit/pii/test_regex_scrubber.py`

Acceptance:

- Scrubs deterministic email, phone, SSN-like, credit-card-like, and token-like fixtures.
- Scrub result includes detection count and entity types.
- Known fixture values are absent from scrubbed text.
- Clean text remains mostly unchanged.

Depends on:

- T-002

### T-008: Storage and Retrieval Protocols

Purpose:

- Establish backend contracts before implementation.

Files:

- `src/stele/storage/base.py`
- `src/stele/retrieval/base.py`
- `src/stele/core/capabilities.py`
- `src/stele/indexing/job.py`
- `src/stele/indexing/queue.py`
- `tests/unit/test_protocol_imports.py`

Acceptance:

- Protocols match backend spec.
- Capability models exist.
- No-op indexer exists.
- Importing protocols does not import SQL/vector deps.

Depends on:

- T-003
- T-004

### T-009: Memory Storage Backend

Purpose:

- Implement exact artifact CRUD for the first backend.

Files:

- `src/stele/storage/memory.py`
- `tests/contract/test_storage_contract.py`
- `tests/contract/backends.py`

Acceptance:

- Store/fetch exact text.
- Store/fetch exact bytes or explicitly documented text-only behavior for MVP.
- Delete works.
- List by namespace/session works.
- TTL cleanup works.
- 1 MB fixture round trip works.

Depends on:

- T-003
- T-008

### T-010: Memory Retrieval Backend

Purpose:

- Implement simple keyword search/query for memory.

Files:

- `src/stele/retrieval/memory.py`
- `tests/contract/test_retrieval_contract.py`

Acceptance:

- Search within artifact finds known needle.
- Query namespace finds expected artifact.
- Namespace isolation works.
- Explicit unsupported vector/graph mode raises `CapabilityError`.
- Results are bounded snippets.

Depends on:

- T-008
- T-009

### T-011: Stele Facade

Purpose:

- Provide the main public API over memory storage/retrieval.

Files:

- `src/stele/core/stash.py`
- `src/stele/__init__.py`
- `tests/unit/core/test_stash_facade.py`
- `tests/contract/test_facade_memory.py`

Acceptance:

- `Stele.from_config({"backend": {"type": "memory"}})` works.
- `store()` returns compact `StoredResult`, not raw full content.
- `fetch()` defaults to scrubbed output when PII enabled.
- Raw fetch requires config opt-in and call opt-in.
- `search()` and `query()` return scrubbed hits by default.
- `capabilities()` reports memory backend.

Depends on:

- T-006
- T-007
- T-009
- T-010

### T-012: Interception Detector and Wrapper

Purpose:

- Convert oversized tool results into stored replacement payloads.

Files:

- `src/stele/interception/detector.py`
- `src/stele/interception/thresholds.py`
- `src/stele/interception/response.py`
- `src/stele/interception/wrapper.py`
- `tests/unit/interception/test_thresholds.py`
- `tests/unit/interception/test_wrapper.py`

Acceptance:

- Below-threshold strings pass through unchanged.
- Above-threshold strings are stored and replaced.
- JSON-like Python objects serialize predictably.
- Replacement contains reference, size metadata, and scrubbed summary.
- Replacement does not contain raw large content or known PII fixture.
- Failure modes are tested.

Depends on:

- T-011

### T-013: MVP Smoke Benchmark

Purpose:

- Produce the first evidence that the core value prop works before SQL.

Files:

- `benchmarks/mvp_smoke.py`
- `tests/benchmarks_smoke/test_mvp_smoke.py`

Acceptance:

- Stores/intercepts a large synthetic JSON payload.
- Emits JSON report with token savings, intercept latency, and PII leakage count.
- Report shows known fixture PII values absent from replacement.

Depends on:

- T-012

## Wave 1 Completion Gate

Wave 1 is complete when:

- Core import works.
- Memory backend exact storage works.
- Memory retrieval works.
- Default summary and PII scrubbing work.
- Interception replacement works.
- MVP smoke benchmark emits machine-readable evidence for token reduction, PII scrubbing, and latency.
- Showcase benchmark replication emits `benchmarks/runs/<date>/Showcase.md` and `Showcase.json` for the original five industry workloads.

Long-term recall starts in Wave 2 because it needs session fixtures and retrieval scoring, but Wave 1 must preserve namespace/session fields so recall can be built without changing core models.

## Wave 2: Durable Local Backend and Integration MVP

Planned tasks:

- T-014 SQLite migrations and exact storage.
- T-015 SQLite FTS retrieval.
- T-016 LangChain structural middleware.
- T-017 LangChain advisory tools.
- T-018 MCP advisory tools.
- T-019 Synthetic long-term recall benchmark.
- T-020 PII benchmark fixture suite.

## Wave 3: Multi-Backend and Vector

Planned tasks:

- T-021 MariaDB exact storage and keyword retrieval.
- T-022 Postgres exact storage and FTS retrieval.
- T-023 ClickHouse exact storage and documented TTL/delete behavior.
- T-024 Chunkshop adapter.
- T-025 Vector retrieval contract tests.
- T-026 Hybrid retrieval.

## Wave 4: Graph, Migration, Release Evidence

Planned tasks:

- T-027 pg-raggraph Postgres adapter.
- T-028 neutral JSONL import.
- T-029 full showcase benchmark replication.
- T-030 external long-memory benchmark adapter.
- T-031 external PII benchmark adapter.
- T-032 docs and public claim audit.
- T-033 release CI matrix.
