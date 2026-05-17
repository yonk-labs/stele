# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`stele` is an off-prompt memory layer for LLM agents: intercept large tool outputs, store the exact bytes behind a `stele://` reference, return scrubbed summaries and bounded retrieval snippets to the model, and serve targeted retrieval back across pluggable backends.

The project is mid-rebuild from a clean-room blueprint. The authoritative product/API/backend specs live in `docs/specs/`; `docs/current-status.md` tracks what's implemented vs. still missing. Treat the specs as the source of truth when behavior is ambiguous.

## Toolchain

- Python `>=3.12`, src/ layout, hatchling build backend
- Virtualenv at `.venv/` — most commands invoke `.venv/bin/...` directly
- Lint: `ruff` (config in `pyproject.toml`, `select = E,F,I,UP,B,SIM`)
- Type check: `mypy --strict` over `stele`
- Tests: `pytest`, with `pythonpath = ["src", "."]` so `benchmarks` is importable as a top-level package alongside `stele`

## Common commands

```bash
# Lint + types + tests (the "before-commit" trio)
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest

# Run a single test file or node
.venv/bin/pytest tests/unit/core/test_stash_facade.py
.venv/bin/pytest tests/contract/test_storage_contract.py::test_store_then_fetch -v

# Backend-gated suites (skip silently when env vars are unset)
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
export STELE_MARIADB_DSN=mariadb://yonk:yonk@localhost:53306/stele
export STELE_CLICKHOUSE_DSN=http://default:@localhost:58123/stele

# Spin up backends via Docker
scripts/postgres-up.sh        # just Postgres
docker compose -f docker-compose.backends.yml up -d --wait   # all three
scripts/test-postgres.sh      # Postgres contract + showcase
scripts/test-backends.sh      # all backends: contract + showcase + recall

# Benchmarks (all also exposed as console scripts under .venv/bin/)
.venv/bin/python -m benchmarks.showcase         # writes benchmarks/runs/<date>/Showcase.{md,json}
.venv/bin/python -m benchmarks.recall           # writes Recall.{md,json}
.venv/bin/python -m benchmarks.longrun          # deterministic long run; see scripts/run-long-benchmarks.sh
.venv/bin/python -m benchmarks.answer_workflow  # LLM-judged; see scripts/run-answer-workflow-judge.sh
```

Optional driver extras: `pip install 'stele-core[postgres|mariadb|clickhouse|chunkshop|judge|all-backends|dev]'`.

## Architecture

The public surface is one class: `Stele` in `src/stele/core/stash.py`. It wires together replaceable subsystems behind a stable contract (`store`, `fetch`, `search`, `query`, `list`, `delete`, `cleanup_expired`, `export_jsonl`, `import_jsonl`, `capabilities`) plus three lazy facade properties — `Stele.memory`, `Stele.extract`, `Stele.recall` — added by the sovereign-memory phases.

```
core/      facade (stash.py), config (Pydantic), artifact + reference + memory models, JSONL, exceptions
storage/   exact byte store per backend: memory, sqlite, postgres, mariadb, clickhouse
           storage/memory_store/  per-backend MemoryStore (Phase 1): memory, sqlite, postgres + mariadb/clickhouse stubs
retrieval/ search per backend: memory, sqlite (FTS5), postgres (tsvector), mariadb (FULLTEXT+LIKE), clickhouse
summary/   deterministic summaries via `lede` adapter
pii/       regex-based scrubber applied to summaries, fetch output, search hits, and memory text
indexing/  optional Chunkshop chunk index for targeted span retrieval (sync/async/skip)
interception/  `stash_tool_result(...)` wrapper that detects oversized tool output and swaps in a reference + summary
extraction/    Phase 2 — pure `extract_candidates` core + `MemoryExtractor` orchestrator; `Stele.extract`
recall/        Phase 3 — `Strategy` Protocol + 6 real strategies + adaptive + `Recall` callable facade; `Stele.recall`
```

The sovereign-memory subsystems (Phases 1–3) sit on top of the artifact
foundation and only consume the public facades, never storage internals:

- **`Stele.memory`** (Phase 1) — `add`/`get`/`search`/`list`/`update`/`delete`
  with supersession (`add(supersedes=[...])`) and `as_of` time-travel on
  SQLite + Postgres. Backed by `storage/memory_store/`.
- **`Stele.extract`** (Phase 2) — `from_artifact`/`from_messages`/`from_text`.
  Pure deterministic core (`extraction/candidates.py`) wrapping `lede`; thin
  I/O orchestrator commits via `Memory.add`. Never bypasses the memory facade.
- **`Stele.recall`** (Phase 3) — callable facade routing by `strategy`, plus
  seven convenience shims. Adaptive escalation is oracle-free (hit-count +
  confidence floor). `recall/` imports no LLM clients, no `pg_raggraph`, no
  `chunkshop`, no `lede` — enforced by `tests/unit/recall/test_architecture.py`.

Key invariants to preserve when changing things:

- **One public shape across backends.** Backends differ in capabilities but not in the `Stele` contract. New behavior usually means extending `StorageBackend` / `RetrievalBackend` (`*/base.py`) and implementing it in every concrete backend, then adding a contract test parameter.
- **Backend selection is config-driven** in `Stele.__init__`. Each `backend.type` resolves to a `StorageBackend` + `RetrievalBackend` pair. DSN-required backends raise `ConfigError` if `backend.dsn` is missing.
- **PII scrubbing is on by default for model-visible surfaces.** Raw fetch is gated by `pii.raw_fetch_enabled`; raising `PIIBlockedError` is the correct response when the gate is closed. Summaries are scrubbed before storage.
- **References are opaque, optionally signed.** `core/reference.py` builds `stele://<namespace>/<artifact_id>`; `core/reference_auth.py` validates signatures when `signing.mode` is `optional` or `required`. Never construct references by string concatenation outside these modules.
- **Chunk index is an optional fast path**, not a replacement for retrieval. `search`/`query` consult the chunk index first when `indexing.provider=chunkshop` and fall back to the backend's native retrieval. Both paths must return package-owned `SearchHit` objects.
- **Phase 4 vector/hybrid is batteries-included.** Users only set `IndexingConfig` (`mode` skip/sync/async) + `RetrievalConfig.default_mode`. All chunkshop config is synthesized internally in `storage/chunk_store/_chunkshop_base.py` via `TargetConfig(dsn=...)` (DSN reused from the artifact backend; never `os.environ`). One-time model prefetch: `scripts/chunkshop-setup.sh`. See [docs/vector-indexing-setup.md](docs/vector-indexing-setup.md). `search`/`query` keep their locked Phase-1 signatures; mode dispatch is internal on `mode or config.retrieval.default_mode`.
- **Interception is structural, not a hook.** Callers explicitly route tool output through `interception/wrapper.py::stash_tool_result`; thresholds in `interception/thresholds.py` decide whether to swap. If the threshold isn't crossed, the original result is returned unchanged.
- **Memory evolves, artifacts are immutable.** Memory text is never edited in place — `memory.update()` rejects text changes and redirects to `add(supersedes=[id])`. Artifacts have no evolution columns (Evolution Boundary, guarded by `tests/unit/test_architecture.py`).
- **Extraction and recall consume facades only.** Phase 2/3 code never reaches into `_store.` or `storage/memory_store/` internals — it goes through `Stele.memory` / `Stele.search` / `Stele.fetch`. PII scrubbing is inherited from those surfaces and never re-applied. Recall is oracle-free and LLM-free; the only place a caller can involve an LLM is the optional `sufficient` callback on adaptive recall.
- **Every memory cites its evidence.** `memory.add(source_refs=[])` raises `ValidationError`; refs must be `stele://` URIs. Extraction always supplies them (derived for `from_artifact`/`from_messages`, caller-supplied for `from_text`).

## Testing layout

- `tests/unit/` — pure-Python unit tests for `core`, `pii`, `summary`, `indexing`, `interception`, `extraction`, `recall`
- `tests/contract/` — parametrized across `BACKENDS` (memory + sqlite by default; postgres/mariadb/clickhouse added when the matching `*_DSN` env var is set). New backend behavior goes here. Memory, extraction, and recall each have their own contract file (`test_memory_contract.py`, `test_extraction_contract.py`, `test_recall_contract.py`).
- `tests/integration/test_showcase_e2e.py` — drives the showcase benchmark end-to-end against whichever backends are configured.
- `tests/benchmarks_smoke/` — quick correctness checks for the benchmark scripts themselves, not full runs.

The `pytest` marker `memory` is reserved for memory-backend contract tests (see `pyproject.toml`).

## Working notes

- The repo is being rebuilt clean-room. If you see what looks like a legacy module name from a prior incarnation, treat it as a regression — `docs/current-status.md` notes that a legacy-name scan must stay clean.
- Benchmark output goes under `benchmarks/runs/<date>/` (gitignored). Showcase/recall outputs are markdown + JSON pairs; don't hand-edit them, re-run the benchmark.
- `scripts/run-answer-workflow-judge.sh` expects an OpenAI-compatible endpoint (defaults to a local one). The `judge` extra installs the `openai` client; without it, only the deterministic benchmarks run.
- Claims about answer accuracy require the answer-workflow benchmark, not the showcase. The showcase only measures payload reduction, fetch correctness, latency, and PII leakage — see `README.md` for the distinction.
