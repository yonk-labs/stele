---
title: Phase 7 (Adapter SDK + Runtime Capture) — T-RAM → Test Coverage Map
created: 2026-05-18
status: evidence — T-RAM-005..008 + the demo-runner loop, each cited to a passing test
branch: phase6-7-runtime-working-memory (off main @ 01cb971) — NOT merged
---

# Phase 7 SC → Test Coverage Map

| T-RAM | Acceptance | Proven by |
|---|---|---|
| 005 | Large tool output stored as artifact before graph event; event has refs + compact summary, no raw payload | `tests/unit/runtime/test_capture.py::test_large_tool_result_stored_as_artifact_event_has_refs_only` |
| 005 | Recall usage recorded with injected refs | `…test_capture.py::test_record_recall_used_records_injected_refs` |
| 005 | Session end closes only the active graph for that session | `…test_capture.py::test_close_session_graphs_is_session_scoped` |
| 006 | Stable & dynamic separate; every packed claim carries refs | `tests/unit/runtime/test_packer.py::test_stable_and_dynamic_are_separate_and_ref_backed` |
| 006 | Inputs not mutated | `…test_packer.py::test_inputs_not_mutated` |
| 006 | Budget overflow deterministic + visible in `omitted` | `…test_packer.py::test_budget_overflow_is_deterministic_and_visible` |
| 006 | Blockers prioritized; node cap honored | `…test_packer.py::test_blockers_prioritized_and_node_cap` |
| 007 | Health reports stores/index/recall/PII/queue/degraded; missing dep explicit; degraded ≠ healthy; testable w/o LLM | `tests/unit/runtime/test_health.py::*` (5 cases) |
| 008 | Warm-up 1/2/4/8; idle flush via injectable clock; session-scoped + idempotent flush; queue depth | `tests/unit/runtime/test_scheduling.py::*` (5 cases) |
| Loop | observe→store→WorkGraph→extract→recall/pack→resume, for real | `tests/integration/test_runtime_loop.py::test_runtime_loop_end_to_end` |
| Loop | PII never reaches packed context / resume view | same test (`_PII_EMAIL not in pack.* / resume`) |
| Loop | every packed claim carries a `stele://` ref | same test (per-line `stele://` assertion + recovery_handles) |
| Loop | session-end flush idempotent | same test (`end()==1` then `==0`) |

| Gate | Evidence |
|---|---|
| Runtime SDK purity (no pg-raggraph/LLM/network/concurrency) | `tests/unit/runtime/test_architecture.py` (6 files clean) |
| WorkGraph purity (Phase 6) still green | `tests/unit/workgraph/test_architecture.py` |
| No regression | full `pytest` 506 passed/21 skipped/7 deselected; ruff + mypy clean |

Decision applied (recon Q4): first adapter = Stele's own in-process
`SteleAgentSession` demo runner (no network/LLM, CI-testable).
LangChain/MCP/OpenAI adapters remain Phase 8.

Runnable: `scripts/demo-runtime-loop.sh`.

Phase 7 complete. Branch pushed to origin; **NOT merged** (per instruction).
