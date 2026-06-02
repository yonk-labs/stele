# Changelog

All notable changes to `stele-core` are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once
out of `0.x`.

## [0.5.1] — 2026-06-01

### Documentation

- Documented the v0.4.0 cq/Zep memory features (tripartite insight, evidence
  model + re-observation merge, lifecycle kinds) and the v0.5.0 optional
  Postgres vector recall in the memory tutorial, README, and current-status.
- New runnable demo `scripts/demo-cq-memory.sh` (tripartite + evidence +
  lifecycle kinds; no network, SQLite).

## [0.5.0] — 2026-06-01

Optional semantic recall over memories (stele#39, corrected design). Additive,
opt-in, Postgres-only. Off by default, so recall is byte-identical to 0.4.0
until enabled. Builds on the `indexable_text` from 0.4.0.

### Added

- **`RetrievalConfig.memory_vector`** (default `False`). When `True` on a
  Postgres backend, the memory store grows a pgvector `embedding` column +
  HNSW (cosine) index, embeds each memory's `indexable_text` on write, and
  `Memory.search_with_score` fuses a semantic leg with the tsvector keyword leg
  via **RRF**. So a paraphrased query with no shared keywords can still recall
  the right fact.
- The embedder is **synthesized internally** from the same fastembed model the
  chunk store uses (`IndexingConfig.embed_model`), so memory and chunk vectors
  share a model. It is never injected and never reads `os.environ`, matching the
  Phase-4 batteries-included invariant. Requires `chunkshop`.
- **`StashCapabilities.memory_vector_search`** advertises support; SQLite and the
  other backends report `False` and keep keyword recall.

### Changed

- `search_with_score` (Postgres) now hydrates result records in one batched
  fetch instead of a per-hit `get()` (removes a pre-existing N+1). The
  keyword-only body is unchanged when no embedder is configured.

### Migration

- The `embedding` column + HNSW index are added lazily, only for a
  vector-enabled store, via the same guarded `DO` block pattern (zero DDL once
  current). A store without `memory_vector` is never touched and needs no
  pgvector extension.

## [0.4.0] — 2026-06-01

cq/Zep-shaped memory rows. Additive, backward-compatible schema evolution of
`MemoryRecord` and the memory store. Existing rows and callers behave
identically until they opt into the new fields. Minor bump because the
duplicate-write semantics change (see Changed). Implements stele#38 and both
halves of stele#37.

### Added

- **Tripartite insight (stele#37A).** `MemoryRecord` and `AddRequest` gain
  optional `summary` / `detail` / `action` fields plus an `indexable_text`
  property. `Memory.add` / `add_many` accept and PII-scrub them. Search now
  indexes the composed insight (Postgres `search_tsv`, SQLite FTS triggers,
  in-process substring) so a term living only in `detail` is findable. When the
  tripartite fields are absent, indexing reduces to the old `text`-only behavior.
- **Evidence model (stele#37B).** New `confirmations` / `last_confirmed` /
  `last_queried` columns; `confidence` may now evolve (it is no longer
  write-time immutable). A new `MemoryStore.confirm()` primitive bumps
  confirmations, stamps `last_confirmed`, and raises confidence toward a floor
  (never lowering it, never exceeding 1.0) via the `evolved_confidence` helper.
  `search_with_score` stamps `last_queried` on the rows it surfaces.
- **cq lifecycle kinds (stele#38).** `MemoryKind` gains `pitfall`,
  `workaround`, `tool_recommendation`, `tool_gap` (L1->L4). The L4 tool-gap
  *synthesis* stays a consumer concern; stele only stores the kinds. Backend
  `CHECK` constraints are generated from the `MemoryKind` Literal so schema and
  model cannot drift.

### Changed

- **Re-observing a duplicate now merges instead of inserting a twin.** When an
  `add` (or a row within `add_many`) hashes to an existing in-scope assertion
  and is not superseding anything, the existing row is `confirm()`ed (bump +
  confidence evolution) and returned, rather than inserting a second row. The
  asserted `text` is never mutated; `update()` still rejects text edits. This
  also fixes a latent wart where extraction silently inserted duplicate rows it
  then reported as rejected. `MemoryAddResult.duplicate_of` is unchanged.

### Migration

- **Postgres** migrates existing tables in-place via a fully guarded `DO`
  block (adds columns, recomposes the generated `search_tsv`, swaps the kind
  `CHECK`). Each arm is existence-checked, so an already-current table runs zero
  DDL and takes no `ACCESS EXCLUSIVE` lock on `initialize()`.
- **SQLite** adds the new columns via `PRAGMA`-guided `ALTER TABLE ADD COLUMN`
  and recreates the FTS triggers to index the composed text. SQLite cannot
  alter a `CHECK` constraint, so the new lifecycle kinds are accepted on stores
  created at or after this version; a pre-existing SQLite store keeps its
  original kind `CHECK` until rebuilt.

## [0.3.0] — 2026-06-01

Batteries-included retrieval defaults, PII opt-in, and a large cross-corpus
benchmark study (stele vs. Mem0 vs. Letta across LoCoMo / HotpotQA / CovidQA at
n≈250). The defaults below change out-of-the-box behavior — hence the minor bump.

### Changed — defaults now optimized for accuracy

- **Hybrid retrieval is the default.** `RetrievalConfig.default_mode` is now
  **`hybrid`** (RRF over vector + keyword). Pure-keyword retrieval was
  catastrophic in the study (jscore 0.05–0.35 vs 0.70–0.94 for hybrid).
- **Indexing is on and tuned by default.** `IndexingConfig` now defaults to
  `mode="sync"`, `provider="chunkshop"`, `chunker="sentence_aware"`,
  `sentence_max_chars=1000`, `neighbor_window=1` — the configuration that topped
  the accuracy/token frontier. Set `mode="skip"` for the old zero-index behavior.
- **PII scrubbing is opt-in.** `PIIConfig.enabled` now defaults to **`False`**.
  When enabled, PII in indexed content is **masked** (not rejected) per the new
  `index_on_pii: "mask" | "skip"` knob — closing the gate no longer fails the
  store. Model-visible surfaces remain scrubbed when `enabled=True`; raw fetch
  stays gated by `raw_fetch_enabled`.

### Added

- **`IndexingConfig.hnsw` knob** (default `True`). Toggles the chunk sink's
  vector index between HNSW (approximate ANN) and an exact/brute-force scan —
  useful on small reference-filtered stores where the HNSW seed can miss
  predicate-matching candidates (the vector recall-shortfall path).
- **Cross-corpus benchmark suite** under `benchmarks/external/` (stele lanes +
  Mem0 and Letta competitor lanes, no-context parametric floor, grid
  consolidation) and a self-contained study bundle under `testing/`
  (write-up + curated run data + MEGA-GRID + scripts).

### Fixed

- **FTS no longer indexes stopwords or punctuation.** Keyword/hybrid queries are
  reduced to content terms (stopwords + punctuation stripped, de-duplicated),
  fixing matches on glued tokens like `"friends,"` and noise from common words.
- **Hybrid representative-hit truncation.** Hybrid fusion returned 500-char
  snippets instead of full chunk text for the representative hit, silently
  shrinking the context fed to the model (and inflating some packing comparisons).

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
