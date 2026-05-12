# Implementation Execution Plan

## TL;DR

Build in layers. First make the core package, exact storage, summaries, PII, and memory backend work. Then add structural interception. Then SQLite. Then SQL backends. Then retrieval. Then Chunkshop vector indexing. Then pg-raggraph. Then benchmarks, migration, docs, and release hardening. Do not start with graph retrieval; it is an optional Postgres enhancement after the public retrieval contract is already stable.

## Repository Target Shape

```text
pyproject.toml
README.md
src/stele/
  __init__.py
  py.typed
  core/
  summary/
  storage/
  retrieval/
  indexing/
  pii/
  interception/
  integrations/
  cli/
benchmarks/
tests/
docs/
```

## Build Sequence

### M0: Project Scaffold

Goal:

- Create installable package with strict tooling and no optional backend dependencies.

Files:

- `pyproject.toml`
- `README.md`
- `src/stele/__init__.py`
- `src/stele/py.typed`
- `tests/unit/test_import.py`

Dependencies:

- `pydantic`
- `pyyaml`
- `lede`
- dev: `pytest`, `ruff`, `mypy`

Exit criteria:

- `python -c "import stele"` passes.
- `pytest tests/unit/test_import.py` passes.
- Ruff and mypy run.

### M1: Core Models, Config, References

Goal:

- Implement package-owned models and config loader.

Files:

- `core/artifact.py`
- `core/config.py`
- `core/reference.py`
- `core/reference_auth.py`
- `core/exceptions.py`
- `core/capabilities.py`
- `core/types.py`

Tasks:

- Add `Artifact`, `ArtifactRecord`, `StoredResult`, `FetchResult`, `SearchHit`, `Page`, `CleanupResult`.
- Add config model with backend, retrieval, indexing, pii, interception, signing sections.
- Add reference parser for `stele://` and `stele://`.
- Add optional HMAC signing.
- Add package exception hierarchy.

Exit criteria:

- Unit tests for references, config, signing, and models pass.
- Mission criteria SC-001, SC-003, SC-008 partially covered.

### M2: Summary and PII Foundation

Goal:

- Implement deterministic summaries and default PII scrubber before storage surfaces exist.

Files:

- `summary/base.py`
- `summary/lede_adapter.py`
- `pii/base.py`
- `pii/regex.py`
- `pii/scrubber.py`

Tasks:

- Wrap `lede.summarize`.
- Add summary length limits.
- Add regex PII provider.
- Add scrub result model.
- Ensure summary output is scrubbed.

Exit criteria:

- Unit tests prove summaries are generated and PII fixtures are scrubbed.
- Core install still has no heavy optional dependencies.
- Mission criteria SC-009, SC-031, SC-032 partially covered.

### M3: Storage and Retrieval Protocols

Goal:

- Define internal contracts before concrete backends.

Files:

- `storage/base.py`
- `retrieval/base.py`
- `retrieval/results.py`
- `retrieval/rank.py`
- `indexing/job.py`
- `indexing/queue.py`

Tasks:

- Add `StorageBackend`, `RetrievalBackend`, `Indexer` protocols.
- Add capability dataclasses/models.
- Add no-op indexer.
- Add rank normalization helpers.

Exit criteria:

- Type tests or mypy validate protocols.
- No concrete backend imports optional dependencies.

### M4: Memory Backend and Facade

Goal:

- First useful product slice: store, fetch, search, query in memory.

Files:

- `storage/memory.py`
- `retrieval/memory.py`
- `core/stash.py`
- `core/lifecycle.py`

Tasks:

- Implement in-memory exact store/fetch/delete/list/cleanup.
- Implement simple keyword retrieval.
- Implement `Stele` facade.
- Apply PII output policy in facade.
- Add raw fetch guard.

Exit criteria:

- Memory contract tests pass.
- PII fixture values absent from default fetch/search/query.
- Exact raw fetch works only when enabled.
- Mission criteria SC-001, SC-002 for memory, SC-010, SC-015, SC-016 partially covered.

### M5: Interception Core

Goal:

- Replace oversized tool outputs with compact stored results.

Files:

- `interception/detector.py`
- `interception/thresholds.py`
- `interception/response.py`
- `interception/wrapper.py`

Tasks:

- Detect content type.
- Estimate tokens.
- Apply thresholds.
- Serialize common Python return types.
- Build replacement payload.
- Implement fail modes.

Exit criteria:

- Oversized output is stored and replaced.
- Below-threshold output passes through.
- Replacement contains reference and scrubbed summary.
- Raw oversized content absent from replacement.
- Mission criteria SC-004, SC-005 covered.

### M6: SQLite Backend

Goal:

- Default durable backend.

Files:

- `storage/sqlite.py`
- `retrieval/sqlite.py`
- `storage/migrations/sqlite/001_artifacts.sql`
- `storage/migrations/sqlite/002_keyword_fts.sql`

Tasks:

- Implement SQLite connection handling.
- Apply migrations.
- Store exact artifacts.
- Implement list/delete/TTL cleanup.
- Implement FTS5 keyword retrieval.

Exit criteria:

- SQLite contract tests pass.
- 1 MB exact round trip passes.
- FTS search finds known needles.
- Mission criteria SC-011 covered for baseline keyword mode.

### M7: LangChain Integration

Goal:

- Prove structural interception in a real agent-oriented surface.

Files:

- `integrations/langchain/middleware.py`
- `integrations/langchain/tools.py`
- `tests/integration/test_langchain_middleware.py`

Tasks:

- Lazy-import LangChain.
- Add structural middleware/wrapper.
- Add advisory tools.
- Add fake tool integration test.

Exit criteria:

- Fake tool returns large payload.
- Model-visible output contains replacement, not raw payload.
- Advisory tools fetch/search/query/delete.
- Mission criteria SC-006, SC-007 partially covered.

### M8: MCP Integration

Goal:

- Provide advisory tool server for clients that can call memory tools.

Files:

- `integrations/mcp/server.py`
- `integrations/mcp/tools.py`

Tasks:

- Lazy-import MCP.
- Expose store/fetch/search/query/list/delete/capabilities.
- Return structured errors.

Exit criteria:

- MCP smoke tests pass.
- MCP outputs are scrubbed by default.
- Mission criteria SC-007 covered.

### M9: SQL Backends Baseline

Goal:

- Implement MariaDB, Postgres, and ClickHouse exact storage plus baseline retrieval.

Files:

- `storage/mariadb.py`
- `retrieval/mariadb.py`
- `storage/postgres.py`
- `retrieval/postgres.py`
- `storage/clickhouse.py`
- `retrieval/clickhouse.py`
- backend migrations

Tasks:

- Add optional dependency guards.
- Implement exact store/fetch/list/delete/cleanup.
- Implement MariaDB FULLTEXT or documented fallback.
- Implement Postgres FTS.
- Implement ClickHouse exact storage and documented delete semantics.

Exit criteria:

- Contract tests pass for MariaDB/Postgres/ClickHouse in release CI.
- Capability matrix is accurate.
- Mission criteria SC-012, SC-013 baseline, SC-014 baseline covered.

### M10: Chunkshop Indexing and Vector Retrieval

Goal:

- Add cross-backend vector indexing without exposing Chunkshop objects.

Files:

- `indexing/chunkshop_adapter.py`
- `indexing/chunkshop_direct.py`
- `retrieval/vector.py`

Tasks:

- Lazy-import Chunkshop.
- Convert artifacts to Chunkshop documents.
- Maintain `(artifact_id, seq_num)` to chunk text mapping.
- Implement sync and async indexing paths.
- Implement vector search adapter.
- Map vector hits to `SearchHit`.

Exit criteria:

- Vector top-k finds expected fixture artifacts.
- No Chunkshop-native objects escape public API.
- Async status is visible.
- Mission criteria SC-017, SC-024 covered.

### M11: Hybrid Retrieval

Goal:

- Merge keyword and vector results consistently.

Files:

- `retrieval/rank.py`
- backend retrieval modules

Tasks:

- Normalize keyword/vector scores.
- Merge duplicate hits.
- Preserve contribution metadata.
- Apply explicit vs implicit fallback rules.

Exit criteria:

- Hybrid tests prove improved targeted detail retrieval over summary-only on fixtures.
- Explicit missing hybrid capability raises `CapabilityError`.

### M12: pg-raggraph Adapter

Goal:

- Add optional graph/time-aware retrieval for Postgres only.

Files:

- `retrieval/pg_raggraph.py`
- `tests/integration/pg_raggraph/`

Tasks:

- Lazy-import pg-raggraph.
- Construct `GraphRAG` only for Postgres graph mode.
- Ingest artifact records into pg-raggraph namespace.
- Query through graph adapter.
- Map results to `SearchHit`.

Exit criteria:

- Postgres baseline works without pg-raggraph installed.
- Non-Postgres configs do not import pg-raggraph.
- Graph query returns package-owned hits.
- Mission criteria SC-018, SC-019, SC-020 covered.

### M13: CLI

Goal:

- Provide developer/admin commands.

Files:

- `cli/main.py`
- `cli/migrate.py`
- `cli/inspect.py`
- `cli/reap.py`

Commands:

- `stele init`
- `stele store`
- `stele fetch`
- `stele search`
- `stele query`
- `stele list`
- `stele delete`
- `stele reap`
- `stele capabilities`
- `stele import-jsonl`

Exit criteria:

- CLI works against memory and SQLite.
- CLI output defaults to scrubbed.

### M14: JSONL Import

Goal:

- Import neutral exported artifacts.

Files:

- `cli/migrate.py`
- `core/migration.py`
- `tests/fixtures/jsonl_export/`

Tasks:

- Define neutral JSONL import format.
- Create fresh `stele://` references for imported artifacts.
- Store exact content.
- Produce deterministic migration report.

Exit criteria:

- Fixture import passes.
- Old reference fetch works.
- Mission criteria SC-023 covered.

### M15: Benchmarks

Goal:

- Build benchmark harness for the four product goals.

Files:

- `benchmarks/`
- `src/stele_bench/`
- `tests/benchmarks_smoke/`

Suites:

- token reduction showcase
- long-term recall synthetic
- PII scrubbing
- overall performance
- retrieval quality

Exit criteria:

- Benchmark smoke emits `report.md` and `report.json`.
- Release suite can run against memory/SQLite and configurable SQL backends.
- Mission criteria SC-028 through SC-034 covered by evidence.

### M16: Docs and Examples

Goal:

- Make the package usable without reading source.

Files:

- `README.md`
- `docs/quickstart.md`
- `docs/backend-matrix.md`
- `docs/configuration.md`
- `docs/retrieval.md`
- `docs/pii.md`
- `docs/benchmarks.md`
- `docs/migration.md`
- `examples/`

Required examples:

- plain Python wrapper
- memory quickstart
- SQLite durable quickstart
- LangChain middleware
- MCP server
- Postgres plus pg-raggraph
- benchmark run

Exit criteria:

- Quickstart commands pass in docs smoke tests where practical.
- Public claims link to benchmark reports/commands.

### M17: Release Hardening

Goal:

- Prepare first complete release.

Tasks:

- Audit optional dependency imports.
- Audit logging for raw content leakage.
- Run full release CI.
- Run benchmark suite and attach reports.
- Confirm capability matrix.
- Confirm docs claims.
- Tag version only after mission brief criteria are checked.

Exit criteria:

- Every SC-001 through SC-034 has evidence.
- No public claim lacks benchmark support.

## Parallel Work Tracks

These can be split once M1 through M4 are stable:

- Track A: SQLite and contract tests.
- Track B: LangChain/MCP integrations.
- Track C: SQL backends.
- Track D: Benchmarks.
- Track E: PII benchmark fixtures.

Avoid parallel edits to the same backend module or shared facade until interfaces are stable.

## First Five Build Tasks

1. Create `pyproject.toml`, package scaffold, and import smoke test.
2. Implement core models, config, references, and exceptions.
3. Implement lede summary adapter and regex PII scrubber.
4. Implement memory backend plus `Stele` facade.
5. Implement interception wrapper and replacement payload.

After those five tasks, the project has a runnable local MVP that proves the core idea before SQL/vector/graph complexity enters.

## Definition of Ready For Each Milestone

A milestone is ready to start when:

- Its dependency milestones are complete.
- Public interfaces it uses are already in place.
- Required optional dependencies are listed in `pyproject.toml`.
- Tests to prove the milestone are named before implementation starts.

## Definition of Done For Each Milestone

A milestone is done when:

- Code exists.
- Unit or contract tests pass.
- Optional dependency behavior is tested.
- PII output policy is respected.
- Docs or config examples are updated if user-facing behavior changed.
- Benchmark impact is either measured or marked not applicable.
