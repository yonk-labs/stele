# Changelog

All notable changes to `stele-core` are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once
out of `0.x`.

## [0.2.1] — 2026-05-26

### Added

- **`digest` recall strategy** — packs retrieved hits as a query-biased lede
  summary + extracted facts + the top-N raw chunks (the highest-accuracy
  hybrid-search packing; same shape as pg-raggraph's `balanced` profile /
  chunkshop `summarize_hits`). The lede packer lives under `summary/` and is
  injected via `_RecallDeps`, so `recall/` stays free of lede imports
  (architecture invariant preserved).

### Changed

- **Indexing-gated default recall strategy.** When `indexing.mode != "skip"`
  (chunk indexing / hybrid search is available) and the caller hasn't pinned
  `recall.default_strategy`, the default is now **`digest`** instead of
  `adaptive`. Deployments with indexing skipped (the zero-config default) are
  unchanged, and an explicit `recall.default_strategy` always wins. Rationale:
  on real third-party corpora (LongBench, LoCoMo) the digest packing matches or
  beats full-context accuracy at ~8× fewer tokens.

## [0.2.0] — 2026-05-26

This release ships the Phase 5+ hardening / lifecycle / CLI-MCP wave below and
integrates the now-feature-complete upstream dependencies. All changes are
additive — the `Stele` public contract is unchanged.

### Changed — upstream dependency integration

- **Bumped the feature-complete upstream deps**: `lede` 0.3 → **0.4.5**,
  `chunkshop` 0.4.3 → **0.6.1**, `pg-raggraph` 0.3.0a3 → **0.4.0a1**
  (+ `lede-spacy` 0.4.5). Upstream defaults are byte-identical; the new
  search/memory/code and retrieval-ladder surfaces are opt-in. Verified
  byte-safe: `ruff` clean, `mypy src` clean (126 files), `pytest` 771 passed;
  graph path verified on 0.4.0a1 (Postgres with `vector` + `pg_trgm`).

### Added — Phase 5+ hardening + lifecycle (2026-05-20)

- **Per-call `supersession_behavior` on recall** — `Stele.recall.graph_search`
  accepts `supersession_behavior="hide" | "prefer_new" | "surface_both"` as a
  keyword override, mirroring the per-call `retracted_behavior` shape.
  Multi-tenant servers no longer need an `asyncio.Lock` around
  `config.graph.supersession_behavior`. (PR #12, closes #6)
- **Vector recall-shortfall warning** — chunkshop `vector_search` emits a
  structured WARNING on logger `stele.retrieval` when fewer hits are
  returned than `limit`. Surfaces the silent-failure mode where the HNSW
  seed misses predicate-matching candidates. (PR #13, closes #7)
- **`Stele.purge_namespace(namespace, *, dry_run) → PurgeReport`** — GDPR
  lifecycle primitive. Hard-deletes artifacts + memory rows (live and
  historical) + chunk-index entries + revisor-projected evidence in one
  call. Idempotent; `dry_run=True` returns counts without mutating.
  `mariadb` / `clickhouse` memory stubs raise `CapabilityError` (capability
  honesty). (PRs #16, #18 — closes #8)
- **`Stele.export_namespace` + `Stele.import_namespace`** — portable v2
  JSONL bundle (`kind: artifact | memory`). Round-trips artifact content
  and memory rows (status + supersedes + effective_until) byte-identical.
  Chunks and revisor projections rebuild from artifacts on import. (PR #19)
- **Bulk-write API** — `Stele.store_many(items: list[StoreRequest]) →
  list[StoredResult]` and `Memory.add_many(items: list[AddRequest]) →
  list[MemoryAddResult]`. Postgres `executemany` in one transaction
  delivers ~10× speedup at N=1000 vs the per-row baseline (twice the 5×
  acceptance bar). Microbench: `stele-bulk-write-bench`. (PR #17,
  closes #14)
- **`stele doctor` pre-checks optional extras** — postgres → psycopg,
  mariadb → pymysql, clickhouse → clickhouse_connect, graph → pg_raggraph,
  chunkshop → chunkshop. Prints actionable `pip install` lines instead of
  the generic `config rejected: ...` wrapper. (PR #20, closes #15)

### Documentation

- **Quickstart §2 — Runtime Model** — explicit "stdio MCP, not HTTP;
  CWD-relative config; same config per project" callout. (PR #20)
- **cli-guide — Postgres backend notes** — `[postgres]` extra requirement,
  schema-evolution story (CREATE-IF-NOT-EXISTS patches, no migration
  system), `retrieval.default_mode: hybrid` silently degrades on Postgres
  without `indexing.provider: chunkshop`, `search_path` DSN tip for shared
  databases. (PR #20)

### Added — CLI + MCP exposure (#21, #22)

The lifecycle and bulk-write surfaces are now reachable from all three
public interfaces (Python library, `stele` CLI, `stele-mcp` server) via
the shared `bind_handlers()` engine.

- **5 new MCP tools**: `stele_purge_namespace` (refuses unless
  `confirm=true` or `dry_run=true`), `stele_export_namespace`,
  `stele_import_namespace`, `stele_store_many`, `stele_memory_add_many`.
  See `docs/mcp-tools.md` §"Lifecycle + bulk-write tools".
- **5 new CLI subcommands**: `stele purge-namespace` (refuses without
  `--yes` or `--dry-run`), `stele export-namespace`,
  `stele import-namespace`, `stele store-many`,
  `stele memory add-many`. Bulk-write subcommands read JSONL from
  `--input <file>` or stdin (`-`).

### Added — benchmark surface

- **Per-report version stamping** — showcase, recall, runtime, longrun, and
  answer-workflow now record the package set that produced them (`stele-core` +
  `lede`/`chunkshop`/`pg-raggraph`) in a `versions` block (JSON) and a header
  line (Markdown), via `benchmarks/_versions.py`.
- **Separate judge endpoint for the answer-workflow benchmark** —
  `--judge-base-url` / `--judge-api-key` let the judge model run on a different
  OpenAI-compatible server than the answerer (avoids self-grading bias). The
  report records the answer/judge model + endpoint in a `config` block.
  Defaults to the answer endpoint, so single-server runs are unchanged.

### Fixed

- **Stale graph integration tests** — the DSN-gated pg-raggraph revisor tests
  called `search_current`/`search_as_of` without the now-required
  `supersession_behavior` kwarg; fixed all four call sites.

### Documentation (0.2.0)

- Corrected the pg-raggraph retrieval-profile audit against the real 0.4.0a1
  API (`profile=` shapes `result.context` only, orthogonal to `mode`; the
  decision-independent perf lever is `retrieval_strategy="vector_first"`).
  Recorded the `digest_search` build-vs-buy collision (chunkshop
  `summarize_hits` / pg-raggraph `mode="summary"` ship the same idea).

### Known limitations

- One Phase-5 control is still Python-only: per-call
  `recall(..., supersession_behavior=...)`. Adding it to the CLI / MCP
  surface is straightforward when needed; left out of this batch because
  no consumer asked for it.

## Earlier — Phases 1–7 + INFRA-A + Multi-platform packaging

See `docs/current-status.md` for the phase-by-phase summary and the
authoritative order-of-operations doc at
`docs/superpowers/2026-05-17-order-of-operations.md`.
