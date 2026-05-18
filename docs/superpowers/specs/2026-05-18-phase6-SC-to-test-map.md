---
title: Phase 6 (WorkGraph core) — T-RAM → Test Coverage Map
created: 2026-05-18
status: evidence — every T-RAM-001..004 acceptance cited to a passing test
branch: phase6-7-runtime-working-memory (off main @ 01cb971)
---

# Phase 6 SC → Test Coverage Map

| T-RAM | Acceptance | Proven by (file::test) |
|---|---|---|
| 001 | Models serialize to JSON | `tests/unit/workgraph/test_models.py::test_models_serialize_round_trip` |
| 001 | Invalid refs fail validation | `…test_models.py::test_validate_refs_rejects_bad_ref` |
| 001 | Large raw content in summaries fails | `…test_models.py::test_assert_no_raw_content_threshold`, `::test_node_summary_rejects_raw_blob` |
| 001 | Every node has a path back to evidence | `…test_models.py::test_node_requires_evidence_or_derived_from` |
| 001 | Valid status transitions | `…test_models.py::test_status_transitions` |
| 002 | Contract: create/get/list/query/add-node/edge/event | `tests/contract/test_workgraph_store.py::*` (memory) |
| 002 | Query by namespace/session deterministic | `…test_workgraph_store.py::test_query_graph_deterministic`, `::test_list_graphs_filters_deterministic` |
| 002 | Unsupported `as_of` explicit | `…test_workgraph_store.py::test_as_of_capability_honesty` (memory → `CapabilityError`) |
| 003 | SQLite passes the SAME contract | `…test_workgraph_store.py::*` parametrized `sqlite` |
| 003 | Real `as_of`; session-scoped list/query; status persists | `…test_as_of_capability_honesty` (sqlite arm), `::test_list_graphs_filters_deterministic`, `::test_update_node_validates_transition` |
| 004 | Mermaid has ids + compact labels | `tests/unit/workgraph/test_renderers.py::test_mermaid_has_ids_and_compact_labels`, `::test_mermaid_label_sanitized` |
| 004 | Markdown has citations/drill-down refs | `…test_renderers.py::test_markdown_includes_citations_and_drilldown_refs` |
| 004 | JSON round-trips structured records | `…test_renderers.py::test_json_round_trips` |
| 004 | Renderers never authoritative | renderers are pure functions (no store import/write); enforced by arch gate |

| Gate | Evidence |
|---|---|
| Purity (no pg-raggraph/LLM/network/concurrency in `src/stele/workgraph/`) | `tests/unit/workgraph/test_architecture.py` (6 files clean); `grep -rn 'pg_raggraph\|openai\|anthropic' src/stele/workgraph/` empty |
| No regression | full `pytest` 476 passed/21 skipped/7 deselected; ruff + mypy clean (192 files) |

Decisions applied (recon sheet §1): WorkGraph = third first-class record
type; `as_of` capability-honest (memory raises, SQLite implements);
deterministic relational query, no pg-raggraph.

Phase 6 complete. Next: Phase 7 (T-RAM-005..008 + demo-runner loop) on the
same branch; push branch (NO merge).
