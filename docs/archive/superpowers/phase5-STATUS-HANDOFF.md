# Phase 5 — Status & Handoff

**Date:** 2026-05-17
**Repo:** `/home/yonk/yonk-tools/stele` — branch **`main`** @ `4943119`
(Phase 4 + e2e harness + all planning docs + prior-art spec are MERGED to main)
**Ground truth:** `docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md` (READ FIRST)
**Corrected design:** `docs/superpowers/specs/2026-05-17-phase5-pg-raggraph-living-knowledge-CORRECTED-design.md`
**Fiction (DO NOT FOLLOW):** `docs/superpowers/specs/2026-05-14-phase5-pg-raggraph-living-knowledge-design.md` (banner-marked superseded)

---

## 1. WHERE WE ARE

- **Phases 1–4 COMPLETE and merged to `main`** (`4943119`). Phase 4 =
  chunkshop vector/hybrid indexing, 5 backends, DC-FINAL verified.
- **E2E test harness COMPLETE** (`deploy/`, `tests/e2e/`): `make -C deploy
  e2e` proves all 5 backends for real (mariadb/clickhouse e2e gap CLOSED).
  Dedicated ports 55452/53316/58133/59010; `graph` profile (port 55453) +
  `tests/e2e/test_living_knowledge.py` (skip-gated on `STELE_PG_RAGGRAPH_DSN`)
  RESERVED for Phase 5 — the Verification Bar is already encoded there.
- **pg-raggraph PRG-1..PRG-4 are DONE** (owner-confirmed 2026-05-17): generic
  opaque metadata + evolution status on hits; post-hoc `retract()`/
  `supersede()`; stable `chunk_id`. Spec:
  `docs/superpowers/specs/2026-05-17-pg-raggraph-requirements.md`. PRG-5
  (chain-current-view) intentionally deferred. **Phase 5 is now UNBLOCKED.**
- pg-raggraph = owner-controlled **Python** `/home/yonk/yonk-tools/pg-raggraph`
  (Rust extension OUT). Hard engine (async `as_of`/`version_filter`/
  `retracted_behavior`/evolution columns/direct-DSN) already existed; PRG-1..4
  added the consumer surface.

## 2. WHAT'S NEXT — Phase 5 (pg-raggraph Living Knowledge)

Execute the **CORRECTED design** (not the fiction). It is design-depth, not a
task plan — the task plan is written now via `/writing-plans` against it +
the recon sheet (the Phase 4 lesson: task plans written far ahead rot).

**Phase 5 Task-0 (prereq gate — do alone first; STOP+report on failure):**
- Confirm pg-raggraph PRG-1..PRG-4 are in a **pinned** version; add a new
  Stele `[postgres-graph]` extra pinning it (independent of `[postgres]`;
  alpha is fine — owner-controlled; NEVER mutate `os.environ`).
- `uv sync` it; **read the installed pg-raggraph source** and produce the
  real async API table (the Phase-4 recon discipline — code against reality,
  never the design doc's prose).
- Build `deploy/images/postgres-raggraph/Dockerfile` (currently a fail-loud
  stub): pgvector base + pinned pg-raggraph + schema bootstrap. Bring up the
  harness `graph` profile.
- Prove for real on the `graph` profile: `ingest → as_of → post-hoc retract →
  re-query`, with the opaque Stele ref recovered on every hit (PRG-1).
- If PRG-1..4 are NOT actually in the pinned version: STOP+report (sequencing
  fix — land them first), exactly like Phase 4 Task-0/chunkshop.

**Then:** `/writing-plans` against the corrected design → execute task-by-task.

## 3. EXECUTION MODEL (the one that worked — keep it)

- **Recon sheet is GROUND TRUTH**, injected into every task. The 2026-05-14
  doc is fiction; the CORRECTED design + recon sheet override it.
- Dedicated worktree + branch (mirror Phase 4): create
  `/home/yonk/yonk-tools/stele-phase5` on `phase5-pg-raggraph-living-knowledge`
  off `main` (use the `using-git-worktrees` skill).
- TDD per task; ONE conventional commit per task `feat(scope): … (SC-P5-xx)`;
  trio green before each commit: `.venv/bin/ruff check .` ;
  `.venv/bin/mypy src tests benchmarks` ; `.venv/bin/pytest` (export
  `STELE_PG_DSN`/`STELE_PG_RAGGRAPH_DSN` as needed). No `--no-verify`.
- **Locked-signature discipline** (Phase-1/4): do NOT reshape `search`/
  `query`/`recall` or the other 6 strategies. Phase 5 is additive: fill the
  `graph_search` stub; `Memory.retract()` NEW; optional
  `as_of`/`version_filter`/`retracted_behavior` on `RecallRequest` (defaults
  preserve today's behavior).
- **Batteries-included**: users only set Stele config; `PGRGConfig`
  synthesized internally; DSN reused from the Postgres artifact backend.
- **Concurrency stays out of `retrieval/`/`recall/`** (DC-P5-2): async→sync
  bridge ONLY in the Revisor/indexing layer. Extend the architecture test's
  forbidden prefixes with `pg_raggraph` (DC-P5-1).
- **Revisor is internal-only**, lazy, `OptionalDependencyError` when the
  extra is absent, NO native objects escape — reuse Phase 4 chunkshop adapter
  templates verbatim in spirit.
- chunkshop-backed / pg-raggraph-backed tests MUST RUN (skipped = false pass).
  Only the OptionalDependencyError path is `skipif`.

## 4. DEFINITION OF DONE (Phase 5)

- SC-P5-01..09 each cited to a real PASSING test (see corrected design §7).
- DC-P5-1/2/3/FINAL green.
- **Exit gate (sovereign-plan):** the Living Knowledge Verification Bar
  proven FOR REAL on `tests/e2e/test_living_knowledge.py` via the harness
  `graph` profile across the 4 fixture lanes (versioned software docs,
  retracted medical/scientific claims, enterprise policy updates,
  account-state changes). **No public living-knowledge claim before this.**
- Full trio green; locked-files grep clean (recall/ + Phase-1/4 surfaces
  untouched); SC→test coverage map written.
- Tag `phase5-pg-raggraph-living-knowledge`; ASK before merging to main.

## 5. NON-Phase-5 FOLLOW-UPS (tracked, not blocking)

- chunkshop change: its ClickHouse sink should set
  `allow_experimental_vector_similarity_index` itself (so self-host users
  need no server config) — owner-controlled, same pattern as the pg-raggraph
  PRG asks. The harness currently sets it via `deploy/clickhouse/users.d/`.
- `docs/current-status.md` is stale (still says P4 is "next") — refresh to
  match `docs/superpowers/2026-05-17-order-of-operations.md` (the
  authoritative roadmap: INFRA-A done → P5 → P6 WorkGraph → P7 → P8 → P9).
- Roadmap also folds in the runtime-agent-memory prior-art (T-RAM-001..011,
  `docs/specs/runtime-agent-memory-architecture-spec.md`).

## 6. PASTE-READY NEW-SESSION PROMPT

```
Continue Stele. Phases 1–4 + the e2e test harness + all planning docs are
COMPLETE and merged to `main` (/home/yonk/yonk-tools/stele @ 4943119).
pg-raggraph PRG-1..PRG-4 are DONE (owner-confirmed). Phase 5 is UNBLOCKED.
START PHASE 5 (pg-raggraph Living Knowledge).

READ FIRST, in order:
1. docs/superpowers/phase5-STATUS-HANDOFF.md   (this file — where we are / next)
2. docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md  (GROUND
   TRUTH — overrides the fiction doc)
3. docs/superpowers/specs/2026-05-17-phase5-pg-raggraph-living-knowledge-CORRECTED-design.md
   (the design to execute: Revisor, projection hooks, graph_search fill,
   SC-P5/DC-P5, Verification-Bar exit gate)
4. docs/superpowers/specs/2026-05-17-pg-raggraph-requirements.md  (PRG-1..PRG-5
   — verify PRG-1..4 are actually in the pinned pg-raggraph)

Do NOT follow docs/superpowers/specs/2026-05-14-phase5-*-design.md (fiction;
banner-marked superseded).

Phase 5 Task-0 (prereq gate; do alone first; STOP+report on failure):
- Create a dedicated worktree (using-git-worktrees skill):
  /home/yonk/yonk-tools/stele-phase5 on branch
  phase5-pg-raggraph-living-knowledge off main.
- Add a Stele [postgres-graph] extra pinning the pg-raggraph version that has
  PRG-1..PRG-4 (independent of [postgres]; NEVER mutate os.environ — reuse
  Stele config / dsn from the Postgres artifact backend).
- uv sync; READ the installed pg-raggraph source and produce the real async
  API table (recon discipline — code against reality, never prose).
- Build deploy/images/postgres-raggraph/Dockerfile (currently a fail-loud
  stub); bring up the harness `graph` profile (port 55453).
- Prove for real on the graph profile: ingest -> as_of -> post-hoc retract ->
  re-query, with the opaque Stele ref recovered on every hit (PRG-1).
- If PRG-1..4 are NOT in the pinned version: STOP+report (land them first).

Then /writing-plans against the corrected design → execute task-by-task.

Execution model (the one that worked — keep it):
- Recon sheet = ground truth, injected into every task. Fiction doc overridden.
- TDD per task; ONE conventional commit per task (feat(scope): … (SC-P5-xx));
  trio green before each commit (ruff / mypy / pytest with STELE_PG_DSN +
  STELE_PG_RAGGRAPH_DSN as needed); no --no-verify.
- LOCKED Phase-1/4 signatures: do NOT reshape search/query/recall or the
  other 6 strategies. Additive only: fill the graph_search stub; new
  Memory.retract(); optional as_of/version_filter/retracted_behavior on
  RecallRequest (defaults preserve current behavior).
- Batteries-included: users only set Stele config; PGRGConfig synthesized
  internally; DSN reused from the artifact backend; no os.environ.
- Revisor internal-only, lazy, OptionalDependencyError when extra absent, no
  native objects escape — reuse Phase 4 chunkshop adapter templates.
- Concurrency (async→sync bridge) ONLY in the Revisor/indexing layer; none in
  retrieval/ or recall/ (DC-P5-2). Extend the architecture test forbidden
  prefixes with pg_raggraph (DC-P5-1).
- pg-raggraph-backed tests MUST RUN (skipped = false pass); only the
  OptionalDependencyError path is skipif.

Definition of done:
- SC-P5-01..09 each cited to a real PASSING test (corrected design §7).
- DC-P5-1/2/3/FINAL green.
- EXIT GATE: Living Knowledge Verification Bar proven FOR REAL on
  tests/e2e/test_living_knowledge.py via the harness `graph` profile across
  all 4 fixture lanes (versioned docs / retracted medical / policy updates /
  account-state). No public living-knowledge claim before this passes.
- Full trio green; locked-files grep clean (recall/ + Phase-1/4 untouched);
  SC→test coverage map written to docs/superpowers/specs/.
- Tag phase5-pg-raggraph-living-knowledge, then ASK before merging to main.
```

---

## 7. WHY THIS HANDOFF (one paragraph)

Context budget on the current session is high. Phase 4, the e2e harness, the
full planning package, and the prior-art spec are all merged to `main`. The
pg-raggraph PRG work (the only thing that gated Phase 5) is done. The clean
break is a fresh session that starts Phase 5 from the corrected design +
recon sheet, using the exact discipline that carried Phase 4 across the line
(recon-is-truth, Task-0 gate, TDD, locked signatures, real proof on the
harness — no fiction, no false green).
