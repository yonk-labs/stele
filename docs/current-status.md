# Current Status

Date: 2026-05-15

## Summary

Phases 1–3 of the sovereign-memory rebuild are complete and on `main` (Phase 1
and Phase 2) plus the `phase3-policy-driven-recall` branch (Phase 3, tagged
`phase3-policy-driven-recall`). The artifact-storage foundation now has a real
memory layer with supersession, deterministic extraction, and policy-driven
recall on top of it.

Source of truth for each slice:

| Phase | Spec | Plan | Status |
| --- | --- | --- | --- |
| 1 — Memory supersession + `as_of` | `skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md` | `docs/superpowers/plans/2026-05-12-phase1-memory-supersession.md` | ✅ complete, tag `phase1-memory-supersession` |
| 2 — Deterministic extraction | `docs/superpowers/specs/2026-05-13-phase2-deterministic-extraction-design.md` | `docs/superpowers/plans/2026-05-13-phase2-deterministic-extraction.md` | ✅ complete, tag `phase2-deterministic-extraction` |
| 3 — Policy-driven recall | `docs/superpowers/specs/2026-05-13-phase3-policy-driven-recall-design.md` | `docs/superpowers/plans/2026-05-13-phase3-policy-driven-recall.md` | ✅ complete, tag `phase3-policy-driven-recall` |

## What's implemented

### Phase 1 — Memory supersession + `as_of`

- `MemoryRecord` model with full evolution columns on SQLite and Postgres.
- `Stele.memory` facade: `add`, `get`, `search`, `list`, `update`, `delete`.
- Supersession via `add(supersedes=[old_id])` — atomic, audit-preserving.
- `as_of=<datetime>` time-travel queries on SQLite and Postgres via SQL WHERE
  filters (no `pg-raggraph` dependency).
- Soft-delete semantics; content-hash duplicate detection; PII scrubbing on
  memory text; every memory cites at least one `stele://` source_ref.
- Cross-backend contract tests parametrized over memory + sqlite + postgres.
- Demo: `scripts/demo-supersession.sh`.

### Phase 2 — Deterministic extraction

- `Stele.extract` facade with three entry points: `from_artifact`,
  `from_messages`, `from_text`.
- Pure `extract_candidates` core (no I/O, no clock) wrapping `lede.extract.*`
  + `lede.summarize`.
- Type-based classifier with regex pattern overlay for agent-loop kinds
  (preference / decision / instruction / commitment / issue).
- `ExtractionReport` with accepted/rejected candidates, PII flags, and a
  config fingerprint stamped on every accepted memory's metadata.
- Cross-backend contract tests; demo: `scripts/demo-extraction.sh`.

### Phase 3 — Policy-driven recall

- `Stele.recall` callable facade: canonical `recall(query=..., scope=...,
  strategy=...)` plus seven convenience shims.
- Six real strategies: `summary_only`, `memory_search`, `artifact_search`,
  `adaptive`, `raw_fetch`, `abstain`. `graph_search` raises `CapabilityError`
  until Phase 5.
- `AdaptiveStrategy` escalates via a deterministic hit-count + confidence-floor
  heuristic (no oracle), with an optional caller-supplied `sufficient`
  callback for LLM-in-the-loop judgment.
- `Memory.search_with_score` helper (backend-pushed source_ref filter) and
  `MemoryExtractor.preview` added as small additive surfaces.
- Benchmark migration: `benchmarks/answer_workflow.py::_run_strategy`
  delegates to `stele.recall(...)` with zero accuracy delta (DC-003).

## Latest verification

Run from the `phase3-policy-driven-recall` worktree with
`STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele`:

- `.venv/bin/ruff check .` — clean
- `.venv/bin/mypy src tests benchmarks` — clean (122 source files)
- `.venv/bin/pytest` — 265 passed, 2 skipped

All drift checkpoints across the three phases passed; SC coverage maps are at
`docs/superpowers/specs/2026-05-13-phase2-sc-coverage.txt` and
`docs/superpowers/specs/2026-05-13-phase3-sc-coverage.txt`.

## What's next

| Phase | Scope |
| --- | --- |
| 4 | Chunkshop vector indexing for memories + recall; embedding-based dedup |
| 5 | `pg-raggraph` Revisor adapter; real `graph_search`; relational structure |
| 6 | Recall policy productization, session-aware variants |
| 7 | Source connectors (files, JSONL, SQL, Jira, Confluence, Slack); universal search |
| 8 | Plugin SDK; framework adapters (LangChain, MCP, OpenAI Agents SDK) |

See `docs/sovereign-memory-system-plan.md` for the full path.
