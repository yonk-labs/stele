# Phase 4 — Status & Handoff

**Date:** 2026-05-16
**Worktree:** `/home/yonk/yonk-tools/stele-phase4`
**Branch:** `phase4-chunkshop-indexing` (off `main`)
**Test state:** **297 passed / 2 skipped**, `ruff` clean, `mypy` clean (140 src files)
**Ground truth:** `docs/superpowers/phase4-recon-correction-sheet.md` (READ FIRST)
**Corrected plan:** `docs/superpowers/plans/2026-05-16-phase4-chunkshop-indexing-CORRECTED.md`
**Original plan:** `docs/superpowers/plans/2026-05-14-phase4-chunkshop-indexing.md` — **FICTION; do not follow its code blocks.**

---

## 1. THIS IS WHERE WE ARE

**Tasks 1–11 + Capabilities-fix + T28(0.4.2 pin) complete and verified.** All
committed on `phase4-chunkshop-indexing`. Linear history off `main` (16 commits).
**Execution resumes at Task 12.**

| Commit | What |
|---|---|
| `d6f2741` | T1: RetrievalMode test (shipped code already had vector/hybrid/graph — effectively a no-op + test) |
| `8b65714` | T2: `IndexingConfig` Phase 4 fields + validators; `RetrievalConfig.default_mode` |
| `7d16d6c` | T3: Bakeoff models |
| `8b9852b` | T4: Bakeoff JSON/YAML loader + overlay |
| `5d71c10` | T5: **(superseded)** created orphan `Capabilities` in artifact.py |
| `91b0737` | **T5 FIX:** deleted orphan; extended real `StashCapabilities`; real tests |
| `a86814a` | T6: `TaskBackend` Protocol + `IndexTask` + `TaskStatus` |
| `ece5e9f` | T7: `InProcessTaskBackend` (threading + queue) |
| `f8bace4` | T8: Redis/Celery `CapabilityError` stubs |
| `fcd2260` | T9: `AsyncChunkIndexer` (uses `"queued"`, not fictional `"pending"`); **DC-002 passed** |
| `9617330` | T10: `ChunkStore` Protocol |
| `3706aa6` | test-hygiene fixup (in-scope) |
| `b7d9110` | T28: chunkshop pin → PyPI `>=0.4.2,<0.5`; dropped hatchling `allow-direct-references` |
| `2bc3640` | **T11: `InProcessChunkStore`** — the batch that wrote it **died mid-run AFTER this clean commit** (orphaning Tasks 12/13 as broken strays, since removed). T11's commit itself is **verified-complete by evidence**: all 8 `ChunkStore` Protocol members, full write→vector→keyword→delete→close round-trip OK, not truncated, mypy-clean, 6 tests pass, `aid:0` chunk_id, dim 384, no chunkshop. SC-009. New session must re-confirm; redo only if provenance distrusted. |
| `c556205` | checkpoint docs (recon sheet, status/handoff, corrected plan) |
| `f56e50a` | baseline correction (297/2) + orphan-cleanup note |

**Drift checkpoints:** DC-002 ✅ passed (Task 9). DC-001, DC-003, DC-004,
DC-FINAL still pending (Tasks 18, 19, 22, 33).

**Environment facts:**
- venv: `uv`-managed at `.venv/`; synced with `--extra all-backends --extra dev
  --extra chunkshop`.
- `chunkshop==0.4.2` installed from PyPI (pin needs bump to `>=0.4.3,<0.5`).
- fastembed model `sentence-transformers/all-MiniLM-L6-v2` (dim 384) **is
  cached** at `~/.cache/fastembed` — chunkshop-backed tests can run for real here.
- Postgres up at `STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele`.
- `uv.lock` is now tracked on this branch (came in with `b7d9110`). **Open
  question for the human:** keep it tracked or `git rm --cached` it (it was
  untracked on `main`). Flagged, not decided.
- **Orphan cleanup:** 3 untracked stray files of unknown provenance
  (`src/stele/indexing/dim_resolution.py`,
  `tests/unit/indexing/test_{chunkshop_adapter,dim_resolution}.py` — Task
  12/13 scaffolding that imported not-yet-existing modules) were removed
  during checkpoint. They were never committed. Tree is now fully clean;
  Tasks 11–13 start fresh per the corrected plan. (This is also why the
  earlier intermediate "291" count was wrong — true clean baseline is 297/2.)

---

## 2. THIS IS WHAT IS BROKEN (the landmines)

The original plan is fiction in these specific ways. The corrected plan + recon
sheet already account for all of them; listing so nothing is forgotten:

1. **Chunkshop API in the plan is invented.** No `chunkshop.sqlite`,
   `SQLiteRetrievalIndex`, `.index()`, `.keyword_search()`, `.vector_search()`,
   or row objects. Real API: `Pipeline`/`CellConfig` + `Sink`/`load_sink`/
   `load_embedder`/`load_chunker`; **vector-only**; `query_top_k` returns bare
   `(doc_id, seq_num, distance)` tuples with **no text** → wrapper must retain
   chunk text locally. (recon §1)
2. **`os.environ[dsn_env]` connection hack** — *was* the biggest gotcha in 0.4.2.
   **chunkshop 0.4.3 fixes it** with a direct `TargetConfig(dsn=…)` field. Use
   that; never mutate `os.environ`. (recon §0)
3. **fastembed downloads ONNX on first use** — not offline-safe. Only
   `InProcessChunkStore` (hash embedder) is deterministic offline. 0.4.3 adds
   `chunkshop prefetch` for explicit setup. (recon §1)
4. **`store(data=...)`** is wrong → `store(content, ...)` positional. Pervasive
   in plan tests. (recon §2)
5. **`fetch(artifact_id).record`** is doubly wrong → `fetch(reference)`,
   `FetchResult` has no `.record`; use `self.storage.fetch(validated_ref)`.
6. **Plan Task 21 rewrites `search()` signature** — would break the locked
   Phase-1 contract + Phase 3's `ArtifactSearchStrategy`. Must add internal
   mode dispatch instead. (recon §2, §3 T21)
7. **`Capabilities` in artifact.py never existed** — real type is
   `StashCapabilities`. A subagent invented an orphan (false-green SC-023);
   **already fixed** in `91b0737`. Future tasks target `StashCapabilities`.
8. **`IndexStatus` has `"queued"`, not `"pending"`** — plan Task 9's edit is
   wrong; already handled correctly (`fcd2260`).
9. **Plan Tasks 1–4 were already satisfied by shipped code** — committed as
   test additions; do not redo.
10. **Plan's `/tmp/.../PROGRESS.log` "progress note" steps are dead** (written
    under a prior "do not commit" rule). Use real per-task conventional commits.
11. **Plan Task 0/33 "do not branch / do not commit"** — superseded; we are on
    a dedicated worktree + branch and commit per task.

---

## 3. THIS IS WHAT IS LEFT TO FINISH

Execute the **corrected plan**
(`plans/2026-05-16-phase4-chunkshop-indexing-CORRECTED.md`), **Tasks 12→33** +
the two added scope items (Task 11 is done — `2bc3640`, verified). Summary:

- **T12–13:** dim-resolution cascade, `chunkshop_adapter` (plan-as-written;
  no chunkshop import in either). (Task 11 `InProcessChunkStore` DONE.)
- **T14–17:** SQLite/Postgres/MariaDB/ClickHouse `ChunkStore` — **rewrite per
  recon §1 + 0.4.3 `dsn`**. The hard part.
- **T18:** `vector.py` + `hybrid.py` facades → **⛔ DC-001**.
- **T19:** hybrid-quality held-out fixture (≥20 pairs) → **⛔ DC-003**
  (load-bearing).
- **T20:** `SyncChunkIndexer` accepts `ChunkStore` (preserve `submit/status`).
- **T21:** `stash.py` wiring — internal mode dispatch (locked sigs), chunk
  store, async worker fix, indexer-gate fix. **Highest risk.**
- **T22:** bakeoff overlay in `__init__` → **⛔ DC-004**.
- **T23:** `capabilities()` populates the 7 fields on `StashCapabilities`.
- **T24:** Phase 3 picks up vector/hybrid via `default_mode` (0 recall changes).
- **T25–27:** vector contract (5 backends), indexing-modes contract, PII assertion.
- **T28:** **bump pin to `chunkshop[all-backends]>=0.4.3,<0.5`** + re-verify.
- **T29–30:** `__init__` exports (`StashCapabilities` not `Capabilities`),
  architecture import-layer test.
- **T31–33:** SC→test coverage map (to `docs/superpowers/specs/…-sc-coverage.txt`),
  re-run all DCs, full verification → **⛔ DC-FINAL**.
- **ADDED — Batteries-included (user req):** `scripts/chunkshop-setup.sh` using
  `chunkshop prefetch`; verify wrappers synthesize all chunkshop config
  internally (user only touches `IndexingConfig`); docs + offline behavior.
- **ADDED — "Make it Real" (user req):** chunkshop-backed contract tests RUN
  (no skips) on sqlite + postgres; run `benchmarks.showcase`, `benchmarks.recall`,
  `tests/integration/test_showcase_e2e.py`; `answer_workflow` if a judge
  endpoint is available; capture outputs as evidence.
- **Close-out:** SC-coverage map (every SC-001..SC-026 → passing test),
  DC-FINAL, tag `phase4-chunkshop-indexing`, then **ask before merging to main**.

---

## 4. PASTE-READY NEW-SESSION PROMPT

```
Continue and finish Stele Phase 4 (Chunkshop indexing) in the existing worktree
/home/yonk/yonk-tools/stele-phase4 on branch phase4-chunkshop-indexing.
Tasks 1-11 + Capabilities-fix + T28(0.4.2) are DONE & verified (17 commits,
297 passed / 2 skipped). RESUME AT TASK 12.

READ FIRST, in order:
1. docs/superpowers/phase4-STATUS-HANDOFF.md  (where we are / left / broken)
2. docs/superpowers/phase4-recon-correction-sheet.md  (GROUND TRUTH — the
   original plan is fiction; this sheet overrides it)
3. docs/superpowers/plans/2026-05-16-phase4-chunkshop-indexing-CORRECTED.md
   (the plan to execute, Tasks 12→33 + added scope; Task 11 done — verify only)

Do NOT follow docs/superpowers/plans/2026-05-14-phase4-chunkshop-indexing.md
code blocks — they reference APIs that do not exist.

Task 0 (prereq gate, do alone first; STOP+report if it fails):
  cd /home/yonk/yonk-tools/stele-phase4
  - Edit pyproject.toml: chunkshop extra -> "chunkshop[all-backends]>=0.4.3,<0.5"
  - uv sync --extra all-backends --extra dev --extra chunkshop
  - Verify chunkshop 0.4.3 Python API matches the recon sheet §1 (Pipeline,
    CellConfig, chunkshop.sinks.{sqlite,pg,mariadb,clickhouse}, load_sink/
    load_backend/load_embedder/load_chunker, Sink.query_top_k/write_document,
    Embedder.embed(list[str])->ndarray) AND that TargetConfig now has a direct
    `dsn` field (recon §0). If the API regressed, STOP — external blocker.
  - Run `chunkshop prefetch` (or fastembed download) so the embedder model is
    cached; confirm ~/.cache/fastembed populated.
  - export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
  - Baseline trio MUST be green: .venv/bin/ruff check . ;
    .venv/bin/mypy src tests benchmarks ; .venv/bin/pytest
    (expect 297 passed / 2 skipped). Commit the pin bump (Task 28):
    `feat(deps): bump chunkshop pin to >=0.4.3,<0.5 (Task 28)`.

Execution model (chosen for speed-with-correctness, the plan being fiction):
  - The recon correction sheet is GROUND TRUTH and is injected mentally into
    every task. Implement directly (no implementer/reviewer subagent ping-pong)
    unless a task is genuinely independent and parallelizable.
  - TDD per task: failing test first, implement, green. ONE conventional commit
    per task: feat(scope): summary (SC-xxx). Trio (ruff/mypy/pytest with
    STELE_PG_DSN) green before each commit. No --no-verify. Ignore the original
    plan's PROGRESS.log steps.
  - chunkshop-backed tests MUST RUN (model cached) — a skipped chunkshop test
    is a FALSE PASS and unacceptable. Only the OptionalDependencyError path is
    skipif find_spec("chunkshop") is not None.
  - Drift checkpoints are HARD GATES at their task: DC-001 (after T18),
    DC-003 (after T19, load-bearing), DC-004 (after T22), DC-FINAL (T33).
    Run them when specified; STOP+report on failure.
  - Surgical scope: touch only each task's declared files; note unrelated
    issues, don't fix them; end-of-work summary per the summary-pattern rule.

Hard constraints:
  - chunkshop[all-backends]>=0.4.3,<0.5 from PyPI (Postgres is core, NO
    [postgres] extra). Use TargetConfig(dsn=...) — never mutate os.environ.
  - Locked Phase-1 signatures: Stele.search(reference,query,*,mode) and
    Stele.query(namespace,query,*,mode) — DO NOT change. Internal mode dispatch
    only; default mode = config.retrieval.default_mode.
  - Locked untouched: memory.py, memory_record.py, extraction/*, recall/*,
    pii/*, artifact stores, chunk_index.py (kept as fallback).
  - Batteries-included: users only ever set Stele IndexingConfig; chunkshop
    config (CellConfig/TargetConfig/embedder) synthesized internally.

Definition of done (do not declare complete without all of it):
  - SC-001..SC-026 each cited to a real PASSING test (not skipped).
  - DC-001/002/003/004/FINAL all green.
  - Batteries-included setup script + docs landed; chunkshop-backed contract
    tests RUN on sqlite + postgres.
  - "Real" proof: benchmarks.showcase + benchmarks.recall +
    tests/integration/test_showcase_e2e.py executed, outputs captured.
  - Full trio green; Out-of-Scope + locked-files greps clean.
  - SC-coverage map at docs/superpowers/specs/2026-05-16-phase4-...-sc-coverage.txt
  - Tag phase4-chunkshop-indexing, then ASK before merging to main.
```

---

## 5. WHY WE RESET (one paragraph, for the record)

The original Phase 4 plan was AI-authored against assumed APIs, never validated
against the installed `chunkshop` or shipped `stele` — so it specified a
fictional Chunkshop library and a `Capabilities` model that never existed.
Blind batched execution turned one fiction into committed false-green code
(orphan `Capabilities`, fixed in `91b0737`) before recon caught the rest.
Recon (reading real source) produced the correction sheet; that, plus three
mid-flight requirement additions (PyPI switch, batteries-included, real
e2e/benchmarks) and chunkshop 0.4.3 landing, made a clean checkpoint + a
corrected plan + a fresh-session handoff the right move over continuing to
grind through a known-bad plan with a slow subagent loop.
