---
title: Stele — Order of Operations (authoritative roadmap)
created: 2026-05-17
status: authoritative — supersedes the phase tables in current-status.md and
        reconciles sovereign-memory-system-plan.md with the runtime-agent-memory spec
location: docs/superpowers/ (committed on phase4-chunkshop-indexing)
inputs:
  - docs/sovereign-memory-system-plan.md (2026-05-12, canonical roadmap prose)
  - /home/yonk/yonk-tools/stele/docs/specs/runtime-agent-memory-architecture-spec.md (prior-art: TencentDB review → T-RAM-001..011)
  - docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md
  - docs/superpowers/specs/2026-05-17-e2e-test-harness-design.md
  - docs/current-status.md (STALE — see §5)
---

# Stele — Order of Operations

This is the single authoritative sequencing document. Where it disagrees with
`current-status.md` or the per-phase tables, **this wins** until those are
updated (see §5 housekeeping).

## §1 — Where we are (verified 2026-05-17)

| Phase | Status |
|---|---|
| 1 Memory core + supersession + `as_of` | ✅ complete (tag `phase1-memory-supersession`) |
| 2 Deterministic extraction | ✅ complete (tag `phase2-deterministic-extraction`) |
| 3 Policy-driven recall (6 real strategies, `graph_search` stubbed) | ✅ complete (tag `phase3-policy-driven-recall`) |
| 4 Chunkshop vector/hybrid indexing (5 backends) | ✅ **complete, verified, tagged `phase4-chunkshop-indexing`, NOT merged** |

E2E reality: memory + sqlite + postgres proven through the public API; **mariadb
+ clickhouse never exercised e2e** (DSN-gated skips); `graph_search` unverifiable
(no graph-enabled Postgres exists).

## §2 — The reconciliation (why the roadmap renumbered)

Three sources had three different forward lists. Reconciled:

- The **sovereign plan** (canonical) had: P5 pg-raggraph, P6 External Adapter
  SDK, P7 Source Catalog+Universal Search, P8 Plugin SDK.
- **current-status.md** (stale) had a *different* P6/P7/P8 — discard it (§5).
- The **runtime-agent-memory prior-art spec** adds T-RAM-001..011 (WorkGraph,
  context packer, adapter health/scheduling, evidence-backed views, runtime
  benchmark) and self-recommends placement "after Phase 5 graph foundation,
  before broad adapter SDK work" (T-RAM-001..004) / "Phase 8 adapter SDK"
  (T-RAM-005..008) / "Phase 5–6" (T-RAM-009).

Two insertions shift the numbering: a prerequisite **E2E harness** (infra) and
**WorkGraph core** as its own phase. Net authoritative sequence:

```
✅ P1  Memory core
✅ P2  Deterministic extraction
✅ P3  Policy-driven recall
✅ P4  Chunkshop indexing            (done, unmerged)
⟹  INFRA-A  E2E Test Harness         (NEXT — prerequisite, not a feature phase)
⟹  P5  pg-raggraph + Living Knowledge Verification
⟹  P6  Runtime Working Memory — WorkGraph core   (T-RAM-001..004)
   P7  Adapter SDK + Runtime Capture (old "External Adapter SDK" ⊕ T-RAM-005..008)
   P8  Source Catalog + Universal Search ( ⊕ T-RAM-009 evidence-backed views)
   P9  Plugin SDK productization (old P8)
   ──  Gated cross-cutting: T-RAM-010 (LLM proposal pipeline, post-deterministic
       only), T-RAM-011 (runtime context-compression benchmark — REQUIRED before
       any public compression claim)
```

Dependency graph:

```
P4 ──► INFRA-A ──► P5 ──► P6 ──► P7 ──► P8 ──► P9
          │         │      │      │
          │         │      │      └─ T-RAM-009 lands in P8 (needs P5+P6)
          │         │      └─ T-RAM-005..008 land in P7
          │         └─ Living-Knowledge Verification Bar = P5 exit gate
          └─ closes mariadb/clickhouse e2e gap; reused by every later phase
T-RAM-011 ─ runs continuously from P6 on; blocks any compression marketing claim
T-RAM-010 ─ only after the deterministic baseline is solid (P6+), behind validators
```

## §3 — The next 3 (laid out in detail)

### INFRA-A — E2E Test Harness  *(do first)*

**Spec:** `docs/superpowers/specs/2026-05-17-e2e-test-harness-design.md`
(design-approved). **Why first:** Phase 5's entire value claim
("living knowledge") is **unverifiable** without a pg-raggraph-enabled
Postgres; and mariadb/clickhouse e2e is an open Phase 4 gap. Small, high
leverage, de-risks everything after it.

- Deliverable: `deploy/docker-compose.full.yml` (profiles core|graph|all),
  `tests/e2e/test_full_journey.py` (5 backends, public API), `deploy/Makefile`,
  `deploy/README.md` (doubles as sample self-host), CI `e2e` job, evidence
  capture. `graph` profile + `tests/e2e/test_living_knowledge.py` reserved
  for P5 (xfail-gated — locks the acceptance bar before implementation).
- Exit: `make -C deploy e2e` proves mariadb + clickhouse e2e for real;
  default `pytest` runtime unchanged; no locked file touched.
- Next action when scheduled: `/writing-plans` on the harness spec → execute.

### P5 — pg-raggraph + Living Knowledge Verification

**Recon (ground truth):**
`docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md`. The
2026-05-14 Phase 5 design doc is fiction-vintage — **do not execute it**.

- **Task-0 gate first** (recon §0): pin/verify pg-raggraph (PyPI is alpha
  `0.3.0a2`; async, `PGRGConfig`-driven; decide adapter-vs-Rust-extension),
  stand it up on the harness `graph` profile, prove a real
  ingest→as_of→retract round-trip **before** writing any Stele wrapper.
  STOP+report if it doesn't hold (exactly like Phase 4 Task-0/chunkshop).
- Scope (recon §3): internal `Revisor` (lazy, opt-in `[postgres-graph]` extra,
  no native objects escape — reuse Phase 4 adapter templates); projection
  hooks on `store()`/`memory.add(supersedes=)`/new `memory.retract()`; fill
  the `graph_search` stub; optional `as_of`/`version_filter`/
  `retracted_behavior` on `RecallRequest` (locked-signature discipline);
  extend capabilities.
- **Exit gate = the Living Knowledge Verification Bar** (sovereign plan)
  proven for real on `tests/e2e/test_living_knowledge.py` across the 4 fixture
  lanes. No skipped graph test counts. No public living-knowledge claim before
  this passes.
- Plan written (corrected, task-level) only when P5 is scheduled — from the
  recon sheet, not the fiction doc.

### P6 — Runtime Working Memory: WorkGraph core (T-RAM-001..004)

The highest user-visible value from the prior-art review (TencentDB's headline
behavior), and **low external-dep risk** — core models/store/renderers are
deterministic + source-backed, no pg-raggraph needed. Sequenced here because
the runtime spec itself says "after Phase 5 graph foundation, before broad
adapter SDK work."

- T-RAM-001 WorkGraph/TaskNode/TaskEdge/TaskTraceEvent models + validators
  (every node source-backed; raw content forbidden; PII on summaries; valid
  status transitions).
- T-RAM-002 `WorkGraphStore` Protocol + memory backend + contract tests.
- T-RAM-003 SQLite WorkGraph store (same contract tests).
- T-RAM-004 Mermaid/Markdown/JSON renderers (views, never authoritative).
- Invariant (sovereign-plan-aligned): *derived claim → source-backed node →
  memory atom → `stele://` artifact → exact content*. Deterministic; LLM
  assist (T-RAM-010) explicitly deferred.
- Open question to resolve at its brainstorm: WorkGraph records = memory,
  artifact, or a third first-class record type (runtime spec §Open Questions).

## §4 — The rest (lighter plan — full brainstorm each when scheduled)

- **P7 — Adapter SDK + Runtime Capture.** Merge of the sovereign plan's
  "External Adapter SDK" with runtime-spec T-RAM-005 (artifact→WorkGraph
  capture), T-RAM-006 (context packer: stable/dynamic/recovery tiers, hard
  budgets), T-RAM-007 (adapter health contract — no silent degraded), T-RAM-008
  (scheduling: warm-up 1/2/4/8, idle flush w/ injectable clock, session-scoped
  flush). First adapter proves the loop: observe tool result → store artifact →
  update WorkGraph → extract → recall/pack → resume. Candidate first adapter
  (LangChain / MCP / OpenAI Agents / own demo runner) = open question.
- **P8 — Source Catalog + Universal Search ⊕ T-RAM-009.** `SourceDescriptor`/
  `SourceConnector`/`SyncReport`; local file/JSONL/SQL connectors first;
  `UniversalSearch` internal facade federating memory/artifact/chunk/graph/
  source; plus evidence-backed Topic/Session/Profile views (T-RAM-009 —
  derived, versioned, cited; needs P5+P6).
- **P9 — Plugin SDK productization.** Decide whether to extract the committed
  protocols (`StorageBackend`/`MemoryStore`/`RetrievalIndex`/`Revisor`/
  `SourceConnector`) into a publishable SDK — only once ≥3 external use cases.
- **Gated cross-cutting:**
  - **T-RAM-011** runtime context-compression benchmark — stand up from P6
    onward; **blocks any public "context compression" claim** (matches the
    benchmark bar: README claims must cite generated reports).
  - **T-RAM-010** optional LLM proposal pipeline (graph labels/summaries/
    profile claims behind validators: fabricated-ref / PII / schema rejection,
    versioned+reversible) — **only after the deterministic baseline is solid**.

## §5 — Immediate decision queue / housekeeping

1. **Merge Phase 4?** — open; you chose "don't merge yet." INFRA-A can be
   built on `phase4-chunkshop-indexing` or after merge — decide before
   starting INFRA-A.
2. **`docs/current-status.md` is stale** (says P4 is "what's next"; its
   P6–P8 list is wrong). Action item: rewrite it to match §2 after Phase 4
   merges. Not done here (out of this pass's scope; flagged).
3. **uv.lock** — already untracked + gitignored on this branch (prior step).
4. **Phase 5 Task-0 owner**: confirm whether pg-raggraph ships from PyPI
   (alpha risk) or a pinned commit / the Rust extension path — this is the
   single biggest external risk and should be answered before P5 is scheduled.
5. The runtime-agent-memory spec's own Open Questions (WorkGraph record type;
   `as_of` from day one?; graph search = pg-raggraph vs relational vs both;
   first adapter; profile views as recall inputs by default) — resolved per
   phase at each phase's brainstorm, not now.

## §6 — Operating rule (the meta-lesson)

Every future phase whose design doc predates its execution is **fiction until
proven**. Each phase starts with a Task-0 recon gate that validates external
deps + the doc against real source (Phase 4's chunkshop and Phase 5's
pg-raggraph both prove this). Detailed task plans are written **at scheduling
time**, from the recon sheet — never far ahead (they rot). Specs and recon
sheets are durable; task plans are not.
