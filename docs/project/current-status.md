# Current Status

Date: 2026-06-04 · Version: **0.6.1**

## Proposed / in design (not shipped)

**Recipe distiller + memory provenance (2026-06-05).** A `distill.recipes()` view
that composes cross-kind memories (precedents + best practices + facts) into
agent-skill-shaped recipes, plus a memory **provenance/authority** axis (human vs
agent), the **materiality judge** extended to `facts`/`precedents`, and a review-queue
governance layer (`review_state` new/accepted/rejected, `priority` low/med/high for an
external curation harness). Validated by a throwaway spike on 16 real sessions; **no
shipped code yet**. Design:
[recipe-distiller-design.md](../specs/recipe-distiller-design.md). Findings:
[recipe-distillation-spike-2026-06-05.md](../benchmarks/findings/recipe-distillation-spike-2026-06-05.md).
Key results: the old store's precedent scarcity was a corpus artifact (real agent work
yields ~1.5 `decision`/session, not 4); the shipped extractor discards turn role, so
~62% of `instruction` memories were agent self-talk; max-authority attribution lifts
instruction human-share 33% -> 55%; 52-58 coherent cross-kind recipes composed.

**Evolving-fact consolidation (2026-06-20, on `feat/evolving-fact-consolidation`).**
`from_session` groups extracted FACTS into `(scope, kind=fact, canonical_subject,
aspect)` slots and commits each slot as a supersession chain (same- and cross-session),
so recall returns an evolving fact's current state while `as_of` preserves history.
Identity = LLM-emitted `subject_label` + deterministic code canonicalization; aspect from
a seeded vocabulary; facts only; bias to false-negatives (no slot, no merge). Recall is
unchanged (already active-filtered). Designed cross-model (gemma+qwen debate + Codex
second opinion), built subagent-driven (6 TDD tasks); full suite 1053 passed. Real-
transcript spot check: slotting fires (14/21 facts slotted across 2 sessions);
supersession triggers only when the same `(subject, aspect)` recurs (proven in the
contract tests; not triggered on the small spot-check sample, as no slot collided).
Design/plan: [evolving-fact-consolidation-design.md](../specs/evolving-fact-consolidation-design.md),
[evolving-fact-consolidation-plan.md](../specs/evolving-fact-consolidation-plan.md). Pending PR/merge.

## 0.6.1 (2026-06-04)

Episodic recall, complete (issue #48, all 3 phases): an `episodic` recall
strategy (session = artifact + its back-linked memories, time-aware via
`parse_temporal` with soft-boost default), `memory.by_source_ref`, and three new
distill views: `episodes` (one summary per session), `timeline` (oldest-first
narrative), `spans` (cross-session arcs clustered by embedding similarity).
Episodic now covers the classical episodic memory category end to end (see
[memory-types.md](../reference/memory-types.md#relation-to-the-classical-taxonomy-semantic--episodic--procedural)
and the step-by-step [episodic-recall-guide.md](../guides/episodic-recall-guide.md)). Also:
`stele install` lays down the SessionEnd ingest hook (multi-hook `PlatformSpec`),
the `stele distill` CLI gained the episodic modes, and the two new embedding
thresholds were calibrated for bge (spans 0.82 to 0.65, timeline floor 0.3 to
0.55). See [`CHANGELOG.md`](../../CHANGELOG.md).

## 0.6.0 (2026-06-03)

Session reduction at the ingestion boundary + the live conversation feed.
`reduce_event` is one per-event filter shared by the live stream and the batch
`.jsonl` parser (drops thinking signatures / snapshots / metadata, truncates tool
bodies, keeps role + is_error). `stele.extraction.ingest.ingest_session` + the
new `stele-ingest` console script reduce a whole session and store ONE artifact
with a TTL; `keep_raw=True` also retains the exact bytes. Reduction is
config-driven (`ExtractionConfig.reduce_*`) with retention tiers keep120
(default), keep300, full, keep-raw. Behavior change: distillation now keeps
successful tool-result headlines (keep120) instead of dropping them (+~30%
memories; old drop is opt-in). A Claude Code SessionEnd hook template ships
(`packaging/templates/hooks/claude-code-ingest.sh.j2`); `stele install` wiring
for it is a follow-up. See [`docs/guides/memory-distillation-guide.md`](../guides/memory-distillation-guide.md)
and [`CHANGELOG.md`](../../CHANGELOG.md).

## 0.5.1 (2026-06-01)

Documentation + demo for the v0.4.0/v0.5.0 memory features (memory tutorial,
README, this status, and `scripts/demo-cq-memory.sh`). No code/API change. See
[`CHANGELOG.md`](../../CHANGELOG.md).

## 0.5.0 (2026-06-01)

Optional semantic recall over memories (stele#39). Opt-in
`retrieval.memory_vector` on a Postgres backend adds a pgvector `embedding`
column + HNSW and fuses a vector leg with the tsvector keyword leg via RRF in
`search_with_score`, so a paraphrase with no shared keywords recalls the fact.
The embedder is synthesized internally from the same fastembed model the chunk
index uses (never injected). Off by default and byte-identical to keyword
recall until enabled; advertised via `capabilities().memory_vector_search`.
Proven in `tests/contract/test_memory_vector.py`. See [`CHANGELOG.md`](../../CHANGELOG.md).

## 0.4.0 (2026-06-01)

cq/Zep-shaped memory rows (stele#37, stele#38), all additive and
backward-compatible:

- **Tripartite insight** — optional `summary` / `detail` / `action` on a
  memory, indexed for search via `indexable_text`.
- **Evidence model** — `confirmations` / `last_confirmed` / `last_queried`;
  `confidence` evolves. Re-observing a fact now *confirms* it (single row, bumped
  evidence) instead of inserting a twin; the asserted text stays immutable.
- **cq lifecycle kinds** — `pitfall` / `workaround` / `tool_recommendation` /
  `tool_gap`, CHECK constraints generated from the `MemoryKind` Literal.

Postgres migrates in-place via a guarded `DO` block (zero DDL once current);
SQLite adds columns via `PRAGMA` and recomposes its FTS triggers. Contract-tested
across memory / sqlite / postgres. Demo: `scripts/demo-cq-memory.sh`.

## 0.2.1 (2026-05-26)

Added the `digest` recall strategy (lede summary + facts + top-N chunks) and
made it the default recall strategy when chunk indexing is enabled
(`indexing.mode != "skip"`); index-off deployments and explicit
`recall.default_strategy` settings are unchanged. See [`CHANGELOG.md`](../../CHANGELOG.md).

## 0.2.0 (2026-05-26)

Released stele 0.2.0 — the Phase 5+ / lifecycle / CLI-MCP wave plus upstream
dependency integration: `lede` 0.4.5, `chunkshop` 0.6.1, `pg-raggraph` 0.4.0a1
(+ `lede-spacy` 0.4.5). All additive; the `Stele` public contract is unchanged.
Verified byte-safe (`ruff` clean, `mypy src` clean, `pytest` 771 passed) and the
graph path confirmed on pg-raggraph 0.4.0a1 (needs Postgres with `vector` +
`pg_trgm`; `deploy/images/postgres-raggraph/init.sql` provisions both).
Benchmarks now stamp the package versions that produced them, and the
answer-workflow benchmark gained a separate judge endpoint. See
[`CHANGELOG.md`](../../CHANGELOG.md).

Open follow-ups: the `digest_search` build-vs-buy decision (gated on the
grounding-benchmark spec at review), pre-existing mypy-2.x debt in test/benchmark
fixtures, and an upstream note for pg-raggraph's advisory-lock leak on a failed
schema bootstrap.

## Summary

Phases 1–7 of the sovereign-memory rebuild plus the E2E test harness
(INFRA-A) are complete and on `main`. Stele now has: an artifact-storage
foundation, a real memory layer with supersession and `as_of`, deterministic
extraction, policy-driven recall, Chunkshop vector/hybrid indexing across five
backends, **living knowledge** — a `pg-raggraph`-backed `Revisor`
projection with post-hoc supersede/retract, time-travel, and
version-filtered graph search — and Runtime Working Memory (WorkGraph core
+ Adapter SDK, Phases 6–7). Plus today's hardening wave: per-call recall
controls, namespace lifecycle primitives (purge / export / import), and a
batched-write public API delivering ~10× postgres throughput.

Authoritative sequencing lives in
[`docs/archive/superpowers/2026-05-17-order-of-operations.md`](../archive/superpowers/2026-05-17-order-of-operations.md).
This file is the human-readable snapshot; that doc wins on disputes.

Source of truth for each slice:

| Phase | Spec | Status |
| --- | --- | --- |
| 1 — Memory supersession + `as_of` | `skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md` | ✅ complete, tag `phase1-memory-supersession` |
| 2 — Deterministic extraction | `docs/archive/superpowers/specs/2026-05-13-phase2-deterministic-extraction-design.md` | ✅ complete, tag `phase2-deterministic-extraction` |
| 3 — Policy-driven recall | `docs/archive/superpowers/specs/2026-05-13-phase3-policy-driven-recall-design.md` | ✅ complete, tag `phase3-policy-driven-recall` |
| 4 — Chunkshop vector/hybrid indexing (5 backends) | `docs/archive/superpowers/specs/2026-05-14-phase4-chunkshop-indexing-design.md` | ✅ complete, tag `phase4-chunkshop-indexing` |
| INFRA-A — E2E test harness | `docs/archive/superpowers/specs/2026-05-17-e2e-test-harness-design.md` | ✅ complete (`deploy/`, `tests/e2e/`) |
| 5 — pg-raggraph living knowledge | `docs/archive/superpowers/specs/2026-05-17-phase5-pg-raggraph-living-knowledge-CORRECTED-design.md` (recon: `…-recon-correction-sheet.md`, `…-task0-pg-raggraph-api-recon.md`) | ✅ complete, tag `phase5-pg-raggraph-living-knowledge`, merged to `main` |

## What's implemented

### Phase 1 — Memory supersession + `as_of`

- `MemoryRecord` model with full evolution columns on SQLite and Postgres.
- `Stele.memory` facade: `add`, `get`, `search`, `list`, `update`, `delete`,
  and (Phase 5) `retract`.
- Supersession via `add(supersedes=[old_id])` — atomic, audit-preserving.
- `as_of=<datetime>` time-travel queries on SQLite and Postgres.
- Soft-delete; content-hash dedup; PII scrubbing; every memory cites a
  `stele://` source_ref. Demo: `scripts/demo-supersession.sh`.

### Phase 2 — Deterministic extraction

- `Stele.extract`: `from_artifact` / `from_messages` / `from_text`.
- Pure `extract_candidates` core over `lede.*`; type+regex classifier;
  `ExtractionReport` with config fingerprint. Demo: `scripts/demo-extraction.sh`.

### Phase 3 — Policy-driven recall

- `Stele.recall` callable facade + convenience shims.
- Seven strategies: `summary_only`, `memory_search`, `artifact_search`,
  `adaptive`, `raw_fetch`, `abstain`, and (Phase 5) a real `graph_search`.
- `AdaptiveStrategy` deterministic escalation with optional `sufficient`
  callback.

### Phase 4 — Chunkshop vector/hybrid indexing

- Batteries-included Chunkshop adapter across memory/sqlite/postgres/
  mariadb/clickhouse; `IndexingConfig` only (no chunkshop YAML/env).
- `vector` / `hybrid` retrieval modes. See
  [vector-indexing-setup.md](../guides/vector-indexing-setup.md).

### INFRA-A — E2E test harness

- `deploy/docker-compose.full.yml` (profiles `core` | `graph` | `all`),
  `deploy/Makefile`, `tests/e2e/`. `make -C deploy e2e` proves all five
  backends for real; `make -C deploy e2e-graph` proves living knowledge.

### Phase 5 — pg-raggraph living knowledge

- Internal `Revisor` (`src/stele/revisor/`): lazy, opt-in
  `stele-core[postgres-graph]` extra, `PGRGConfig` synthesized internally,
  async→sync bridge contained in the adapter, no native objects escape.
- Projection hooks on `Stele.store()`, `Memory.add(supersedes=)`, and the
  new `Memory.retract()`.
- Real `graph_search` strategy + optional `as_of` / `version_filter` /
  `retracted_behavior` on `RecallRequest` (additive; existing callers
  unchanged).
- Capability honesty: non-Postgres / no-extra / `graph.enabled=false` →
  `graph_search` raises `CapabilityError`; memory evolution still works.
- Exit gate met: the Living Knowledge Verification Bar
  (`tests/e2e/test_living_knowledge.py`) proven for real via
  `make -C deploy e2e-graph` across four fixture lanes. SC→test map:
  `docs/archive/superpowers/specs/2026-05-17-phase5-SC-to-test-map.md`. See
  [living-knowledge-setup.md](../guides/living-knowledge-setup.md).

### Phases 6–7 — Runtime Working Memory (2026-05-18, PR #1)

- `WorkGraph` core models — `WorkGraph` / `TaskNode` / `TaskEdge` /
  `TaskTraceEvent`, `WorkGraphStore` (memory + SQLite), Mermaid / Markdown
  / JSON renderers. Deterministic, source-backed, no pg-raggraph dependency.
- Adapter SDK + Runtime Capture (T-RAM-005..008): artifact → WorkGraph
  capture, context packer, adapter health contract, scheduling. First
  framework adapter proves the loop.

### Phase 5+ hardening & lifecycle (2026-05-20)

Seven small PRs ship on top of the core sovereign-memory stack. All
additive; no breaking signature changes.

| PR | Closes | What |
| --- | --- | --- |
| #12 | #6 | Per-call `supersession_behavior` kwarg on `Stele.recall.graph_search` (mirrors `retracted_behavior` per-call shape). Multi-tenant servers no longer need an `asyncio.Lock` around `config.graph.supersession_behavior`. |
| #13 | #7 | Vector recall-shortfall WARNING on logger `stele.retrieval` when chunkshop `vector_search` returns fewer hits than `limit`. Surfaces the silent-failure mode where the HNSW seed misses predicate-matching candidates. |
| #16 | #8a | `Stele.purge_namespace(namespace, *, dry_run) → PurgeReport` — GDPR-style lifecycle primitive. Artifact + memory deletion across the five backends + the in-process backend; mariadb / clickhouse memory stubs raise `CapabilityError` (capability honesty). |
| #18 | #8b | Extends `purge_namespace` to drop chunk-index entries and revisor-projected evidence (`PgRaggraphRevisor.purge_namespace` calls upstream `GraphRAG.delete()`). `PurgeReport` gains `chunks` + `graph_evidence` counts. |
| #19 | #8c | `Stele.export_namespace(namespace, path)` + `Stele.import_namespace(path)` — v2 mixed-record JSONL bundle (`kind: artifact | memory`). Round-trips artifact content + memory rows + supersession chain byte-identical. Chunks/revisor projections rebuild from artifacts. |
| #17 | #14 | `Stele.store_many(items: list[StoreRequest]) → list[StoredResult]` and `Memory.add_many(items: list[AddRequest]) → list[MemoryAddResult]`. Bulk-write API: postgres `executemany` in one transaction delivers **~10× speedup at N=1000** vs per-row baseline. Microbenchmark `benchmarks/bulk_write.py` (`stele-bulk-write-bench` console script). |
| #20 | #15 | `stele doctor` pre-checks the optional extras matched to the configured backend (postgres → psycopg, mariadb → pymysql, clickhouse → clickhouse_connect, graph → pg_raggraph, chunkshop → chunkshop) and prints actionable `pip install` lines. Quickstart §2 documents the stdio + CWD-relative-config runtime model. cli-guide gains a Postgres-backend-notes subsection (schema evolution, `hybrid → keyword` silent-degrade conditions, `search_path` DSN tip). |

**Gap deliberately tracked, not silently left:** the new lifecycle and
bulk-write surfaces (`purge_namespace`, `export_namespace`,
`import_namespace`, `store_many`, `add_many`) are **library-only** today
— not yet exposed via the `stele` CLI or the `stele-mcp` server.
Follow-up issues track CLI + MCP exposure.

### Packaging — Multi-platform MCP + slash-skill (2026-05-20, branch `feat/multiplatform-packaging`)

- `stele-mcp` stdio server with the full 18-tool surface (`store`/`fetch`/`search`/`query`/`list`/`delete` + `memory_*` × 7 + `extract_*` × 3 + `recall` + `stash_tool_result`). Sanitized egress + structured `McpError` codes.
- `stele` CLI: `init`, `install`, `uninstall`, `status`, `doctor`, `mcp`.
- Seven launch platforms driven by `src/stele/packaging/platforms.py:PLATFORM_CONFIG`:
  Claude Code, Codex, OpenCode, Cursor, Gemini CLI, Copilot, Aider.
- One Jinja template per content type (skill, agents-md section, mcp.json, four hook variants); per-platform render via dict lookup. No duplicated skill files.
- Idempotent shared-doc section editing (CLAUDE.md / AGENTS.md / GEMINI.md) with marker + next-H2 pattern; refuses to act on ambiguous double-marker corruption.
- Spec: `docs/archive/superpowers/specs/2026-05-20-stele-multiplatform-packaging-design.md`.
- Plan: `docs/archive/superpowers/plans/2026-05-20-stele-multiplatform-packaging.md`.
- Smoke: `docs/contributing/release-smoke-checklist.md`. Auth model: `docs/operations/mcp-auth-model.md`.

## What's next (authoritative — order-of-operations §2)

| Phase | Scope |
| --- | --- |
| 8 | Source Catalog + Universal Search ⊕ T-RAM-009 (evidence-backed Topic/Session/Profile views). |
| 9 | Plugin SDK productization (extract committed protocols once ≥3 external use cases). |
| — | Gated cross-cutting: T-RAM-011 (runtime context-compression benchmark — blocks any public compression claim); T-RAM-010 (optional LLM proposal pipeline, post-deterministic, behind validators). |
| — | CLI + MCP exposure of the library-only lifecycle and bulk-write surfaces (`purge_namespace`, `export_namespace`, `import_namespace`, `store_many`, `add_many`). Tracked as separate issues. |
| — | Open study tickets: #10 (two-tier provisional/consolidated memory; design conversation), #11 (per-call `memory_tier` kwarg, paired with #10), #9 (runtime metadata-index management; low priority, needs an admin/UI consumer). |

See [`docs/archive/superpowers/2026-05-17-order-of-operations.md`](../archive/superpowers/2026-05-17-order-of-operations.md)
for the dependency graph and the full path, and
[`docs/archive/sovereign-memory-system-plan.md`](../archive/sovereign-memory-system-plan.md) for
the canonical prose.
