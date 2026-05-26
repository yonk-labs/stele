# Current Status

Date: 2026-05-26 · Version: **0.2.0**

## 0.2.0 (2026-05-26)

Released stele 0.2.0. Integrated the feature-complete upstream deps —
`lede` 0.4.5, `chunkshop` 0.6.1, `pg-raggraph` 0.4.0a1 (+ `lede-spacy` 0.4.5);
all additive, the `Stele` public contract is unchanged. Verified byte-safe
(`ruff` clean, `mypy src` clean, `pytest` 771 passed) and the graph path
confirmed on pg-raggraph 0.4.0a1 (needs Postgres with `vector` + `pg_trgm`;
`deploy/images/postgres-raggraph/init.sql` provisions both). Benchmarks now
stamp the package versions that produced them, and the answer-workflow
benchmark gained a separate judge endpoint. See [`CHANGELOG.md`](../CHANGELOG.md).

Open follow-ups: the `digest_search` build-vs-buy decision (gated on the
grounding-benchmark spec at review), pre-existing mypy-2.x debt in test/benchmark
fixtures, and an upstream note for pg-raggraph's advisory-lock leak on a failed
schema bootstrap.

## Summary

Phases 1–5 of the sovereign-memory rebuild **plus the E2E test harness
(INFRA-A)** are complete and on `main`. Stele now has: an artifact-storage
foundation, a real memory layer with supersession and `as_of`, deterministic
extraction, policy-driven recall, Chunkshop vector/hybrid indexing across five
backends, and **living knowledge** — a `pg-raggraph`-backed `Revisor`
projection with post-hoc supersede/retract, time-travel, and
version-filtered graph search, every hit citing its `stele://` evidence.

Authoritative sequencing lives in
[`docs/superpowers/2026-05-17-order-of-operations.md`](superpowers/2026-05-17-order-of-operations.md).
This file is the human-readable snapshot; that doc wins on disputes.

Source of truth for each slice:

| Phase | Spec | Status |
| --- | --- | --- |
| 1 — Memory supersession + `as_of` | `skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md` | ✅ complete, tag `phase1-memory-supersession` |
| 2 — Deterministic extraction | `docs/superpowers/specs/2026-05-13-phase2-deterministic-extraction-design.md` | ✅ complete, tag `phase2-deterministic-extraction` |
| 3 — Policy-driven recall | `docs/superpowers/specs/2026-05-13-phase3-policy-driven-recall-design.md` | ✅ complete, tag `phase3-policy-driven-recall` |
| 4 — Chunkshop vector/hybrid indexing (5 backends) | `docs/superpowers/specs/2026-05-14-phase4-chunkshop-indexing-design.md` | ✅ complete, tag `phase4-chunkshop-indexing` |
| INFRA-A — E2E test harness | `docs/superpowers/specs/2026-05-17-e2e-test-harness-design.md` | ✅ complete (`deploy/`, `tests/e2e/`) |
| 5 — pg-raggraph living knowledge | `docs/superpowers/specs/2026-05-17-phase5-pg-raggraph-living-knowledge-CORRECTED-design.md` (recon: `…-recon-correction-sheet.md`, `…-task0-pg-raggraph-api-recon.md`) | ✅ complete, tag `phase5-pg-raggraph-living-knowledge`, merged to `main` |

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
  [vector-indexing-setup.md](vector-indexing-setup.md).

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
  `docs/superpowers/specs/2026-05-17-phase5-SC-to-test-map.md`. See
  [living-knowledge-setup.md](living-knowledge-setup.md).

### Packaging — Multi-platform MCP + slash-skill (2026-05-20, branch `feat/multiplatform-packaging`)

- `stele-mcp` stdio server with the full 18-tool surface (`store`/`fetch`/`search`/`query`/`list`/`delete` + `memory_*` × 7 + `extract_*` × 3 + `recall` + `stash_tool_result`). Sanitized egress + structured `McpError` codes.
- `stele` CLI: `init`, `install`, `uninstall`, `status`, `doctor`, `mcp`.
- Seven launch platforms driven by `src/stele/packaging/platforms.py:PLATFORM_CONFIG`:
  Claude Code, Codex, OpenCode, Cursor, Gemini CLI, Copilot, Aider.
- One Jinja template per content type (skill, agents-md section, mcp.json, four hook variants); per-platform render via dict lookup. No duplicated skill files.
- Idempotent shared-doc section editing (CLAUDE.md / AGENTS.md / GEMINI.md) with marker + next-H2 pattern; refuses to act on ambiguous double-marker corruption.
- Spec: `docs/superpowers/specs/2026-05-20-stele-multiplatform-packaging-design.md`.
- Plan: `docs/superpowers/plans/2026-05-20-stele-multiplatform-packaging.md`.
- Smoke: `docs/packaging-smoke-checklist.md`. Auth model: `docs/packaging-auth-model.md`.

## What's next (authoritative — order-of-operations §2)

| Phase | Scope |
| --- | --- |
| 6 | Runtime Working Memory — WorkGraph core (T-RAM-001..004): WorkGraph/TaskNode/TaskEdge/TaskTraceEvent models, `WorkGraphStore` (memory + SQLite), Mermaid/Markdown/JSON renderers. Deterministic, source-backed, no pg-raggraph. |
| 7 | Adapter SDK + Runtime Capture (T-RAM-005..008): artifact→WorkGraph capture, context packer, adapter health contract, scheduling; first framework adapter proves the loop. |
| 8 | Source Catalog + Universal Search ⊕ T-RAM-009 (evidence-backed Topic/Session/Profile views). |
| 9 | Plugin SDK productization (extract committed protocols once ≥3 external use cases). |
| — | Gated cross-cutting: T-RAM-011 (runtime context-compression benchmark — blocks any public compression claim); T-RAM-010 (optional LLM proposal pipeline, post-deterministic, behind validators). |

See [`docs/superpowers/2026-05-17-order-of-operations.md`](superpowers/2026-05-17-order-of-operations.md)
for the dependency graph and the full path, and
[`docs/sovereign-memory-system-plan.md`](sovereign-memory-system-plan.md) for
the canonical prose.
