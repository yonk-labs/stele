---
title: Phase 5 SC → Test Coverage Map (DC-P5-FINAL evidence)
created: 2026-05-17
status: evidence — every SC-P5 cited to a real PASSING test; DC-P5 all green
branch: phase5-pg-raggraph-living-knowledge (off main @ e39c300)
---

# Phase 5 SC → Test Coverage Map

Verification Bar proven FOR REAL via `make -C deploy e2e-graph` → **5 passed,
0 skipped** (skipped = false pass; this is the DC-P5-FINAL exit gate).
Task-0 round-trip independently proven against the live `graph` profile.

| SC | Requirement | Proven by (file::test) | Commit |
|----|-------------|------------------------|--------|
| SC-P5-01 | New evidence supersedes old; superseded deprioritized/hidden per policy | `tests/e2e/test_living_knowledge.py::test_supersede_then_current_view_excludes_old`; `tests/unit/core/test_memory_retract.py::test_add_with_supersedes_projects_supersede` | 7de50d9, 1bca7e4 |
| SC-P5-02 | Retracted hidden/flagged/surfaced (all 3 modes) | `tests/e2e/test_living_knowledge.py::test_retract_honors_policy_hide_flag_surface_both`; `tests/integration/test_pg_raggraph_revisor.py::test_retract_hide_is_absolute_and_naive_rejected` | 7de50d9, 37752e4 |
| SC-P5-03 | `as_of` recovers the historical view | `tests/e2e/test_living_knowledge.py::test_as_of_recovers_historical_view`; `tests/e2e/test_living_knowledge.py::test_supersede_then_current_view_excludes_old` (as_of arm) | 7de50d9 |
| SC-P5-04 | `version_filter` returns one family (wired + honored, no cross-version leak via the public API; the public surface intentionally does not project version_label — see note) | `tests/e2e/test_living_knowledge.py::test_version_filter_returns_one_family` | 7de50d9 |
| SC-P5-05 | EVERY hit maps back to exact `stele://` evidence | `tests/e2e/test_living_knowledge.py::test_every_living_knowledge_hit_cites_stele_ref`; `tests/integration/test_pg_raggraph_revisor.py::test_ingest_then_search_recovers_stele_ref`; `tests/unit/recall/test_graph_search_strategy.py::test_graph_search_returns_hits_and_cites_stele_ref` | 7de50d9, 37752e4, dbf36aa |
| SC-P5-06 | `graph_search` real; 6 other strategies + locked `search`/`query`/`recall` unchanged | `tests/unit/recall/test_recall_request_optional_fields.py` (additive); full suite green (484 passed); DC-P5-3 diff (6 strategies untouched) | 6a6eb21 |
| SC-P5-07 | Non-Postgres / no-`[postgres-graph]` → `graph_search` `CapabilityError`; memory evolution still works | `tests/unit/recall/test_graph_search.py`; `tests/unit/recall/test_graph_search_strategy.py::test_graph_search_capability_error_when_revisor_inactive`; `tests/unit/core/test_stash_revisor.py` | dbf36aa, e592a34 |
| SC-P5-08 | `Memory.retract()` additive; existing memory API unchanged | `tests/unit/core/test_memory_retract.py`; `tests/unit/storage/test_memory_set_retracted.py` | 1bca7e4, beed8c7 |
| SC-P5-09 | Capabilities reports graph/living-knowledge state | `tests/unit/core/test_capabilities_graph.py`; `tests/unit/core/test_graph_config.py` | de74764, f6167c9 |

**SC-P5-04 note (recon-honest):** the corrected design's additive public
surface does not include a `version_label` projection (it was deliberately
out of scope). `version_filter` is fully wired end-to-end
(`RecallRequest` → `graph_search` → `Revisor.search_*` → pg-raggraph
`query(version_filter=)`) and is proven HONORED via the public API (a
requested version yields no cross-version leakage). A positive
"only-2025-family" assertion would require a `version_label` projection
surface, which is a scoped-out follow-up — not a Phase-5 deliverable.

## Drift Checkpoints

| DC | Gate | Evidence |
|----|------|----------|
| DC-P5-1 | no `pg_raggraph` in `retrieval/` or `recall/` | `tests/unit/test_architecture_phase5.py::test_dc_p5_1_no_pg_raggraph` (43 cases green) + existing `tests/unit/recall/test_architecture.py` (FORBIDDEN_PREFIXES still lists `pg_raggraph`). `grep -rn 'pg_raggraph' src/stele/retrieval/ src/stele/recall/` → **clean**. |
| DC-P5-2 | no `asyncio`/`threading` in `retrieval/`/`recall/` | `tests/unit/test_architecture_phase5.py::test_dc_p5_2_no_concurrency`. `grep -rn 'import asyncio\|import threading' src/stele/retrieval/ src/stele/recall/` → **clean**. The async→sync bridge lives only in `src/stele/revisor/pg_raggraph_revisor.py`. |
| DC-P5-3 | locked signatures unchanged | `git diff --stat e39c300 -- src/stele/recall/{memory_search,artifact_search,adaptive,summary_only,raw_fetch,abstain}.py` → **empty** (6 other strategies untouched). `facade.py`/`models.py` diffs are additive optional params only. Full suite green = no regression. |
| DC-P5-FINAL | Bar green for real | `make -C deploy e2e-graph` → **5 passed, 0 skipped** (graph profile, 4 fixture lanes: versioned software docs, retracted medical claim, account-state change, enterprise policy). |

## Out of scope (corrected design §9) — confirmed NOT built

PRG-5 (chain "current view"); the Rust pg-raggraph extension; evolution
re-index/migration tooling; Phases 7-9. None implemented.

## Deviations from the plan (recon-honest)

- Integration test path: `tests/integration/test_pg_raggraph_revisor.py`
  (flat) instead of `tests/integration/revisor/…` — a `revisor` package
  there collided with `tests/unit/revisor/` under mypy's duplicate-module
  rule; flat matches the repo's existing `tests/integration/` convention.
- `tests/unit/recall/test_graph_search.py` message regex updated from
  `"Phase 5"` to `"graph_search requires"`: the stub message was stale
  (Phase 5 now exists); the test's behavioral intent (graph_search →
  CapabilityError when unavailable, SC-P5-07) is unchanged and still green.
