# Session Handoff — Stele Rebuild

**Last updated:** 2026-05-15
**Repo:** `/home/yonk/yonk-tools/stele` (main) + worktree `/home/yonk/yonk-tools/stele-phase3`
**Remote:** `git@github.com:yonk-labs/stele.git`
**main HEAD:** `0f017d3` — in sync with `origin/main`

## Where things stand

| Phase | Status | Evidence |
|---|---|---|
| 1 — Memory supersession + `as_of` | ✅ complete, merged to main | tag `phase1-memory-supersession` |
| 2 — Deterministic extraction | ✅ complete, merged to main | tag `phase2-deterministic-extraction` |
| 3 — Policy-driven recall | ✅ complete, merged to main | tag `phase3-policy-driven-recall`; branch + worktree `stele-phase3` |
| 4 — Chunkshop indexing | 📋 planned, NOT started | `docs/superpowers/plans/2026-05-14-phase4-chunkshop-indexing.md` (34 tasks) |
| 5 — pg-raggraph + Living Knowledge | 📋 planned, blocked on Phase 4 | `docs/superpowers/plans/2026-05-14-phase5-pg-raggraph-living-knowledge.md` (38 tasks) |

Test baseline on main with `STELE_PG_DSN` set: **267 passed, 2 skipped**;
`ruff` clean; `mypy src tests benchmarks` clean (122 files).

## What was done this session (already committed + pushed)

- Phases 1–3 executed via `superpowers:subagent-driven-development` and merged
  to main (linear history; each phase rebased onto the prior).
- Fixed a real FTS5 crash: `Memory.search` / `search_with_score` raised
  `fts5: syntax error` on natural-language queries (e.g. ending in `?`),
  making `stele.recall` unusable on SQLite. Fixed by reusing the artifact
  retrieval layer's `_fts_query` sanitizer; regression tests added. (`b137cdc`)
- Refreshed `docs/current-status.md`, `README.md`, `CLAUDE.md`; added
  `docs/tutorial-memory.md` (every snippet verified runnable). (`8eb476d`)
- Pre-merge secret scan: PASS (no secrets/PII). Hardened `.gitignore` with
  `.env`/key/credential patterns. (`abcae3d`)
- Reconciled Phase 4 docs + `pyproject.toml` to the real Chunkshop pin. (`0f017d3`)

## Chunkshop pin (load-bearing for Phase 4 — do not regress)

```
chunkshop[all-backends] @ git+https://github.com/yonk-labs/chunkshop.git@v0.4.1#subdirectory=python
```

- Immutable **git tag v0.4.1** — chunkshop 0.4.x is GitHub-tag/release-only,
  **NOT on PyPI** (PyPI serves 0.3.2 = no modular backends). A `>=` PyPI pin
  silently falls back and breaks.
- `[all-backends]` == `sqlite,mariadb,clickhouse`. **Postgres is core**
  (`psycopg[binary]`) — there is NO `[postgres]` extra.
- Python package is in the `python/` subdir of the monorepo.
- In-flight chunkshop `merge/v4-into-main` → v0.4.2 is **Rust-only** — does
  not change the Python package. Stay on v0.4.1 Python; do not wait for 0.4.2.
- Migrate to `chunkshop[all-backends]>=0.4.1,<0.5` only once 0.4.x hits PyPI.

## Environment / conventions

- Venvs are **uv-managed** per worktree: `uv sync --extra all-backends --extra dev`.
  Commands run as `.venv/bin/{python,pytest,ruff,mypy}`.
- Backend-gated tests need `export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele`
  (local docker Postgres already running on :55432).
- Before-commit trio: `.venv/bin/ruff check .` / `.venv/bin/mypy src tests benchmarks` / `.venv/bin/pytest`.
- Plans live at `docs/superpowers/plans/`, specs at `docs/superpowers/specs/`,
  SC→test maps at `docs/superpowers/specs/*-sc-coverage.txt`.
- Execution method: `superpowers:subagent-driven-development`, **batched for
  speed**. One implementer subagent per **batch of 5 plan tasks** (Tasks 1–5,
  6–10, …); one commit per task with the plan's exact messages; the
  ruff/mypy/pytest trio runs inside each task. After each 5-task batch, ONE
  consolidated review (spec compliance + code quality together) — not
  per-task. After all tasks, ONE final comprehensive review of the whole
  `main..HEAD` diff (SC coverage, DC-FINAL, architecture, full trio). Task 0
  is a solo prereq gate run alone first. Drift checkpoints (DC-XXX) are hard
  gates run at their specified point inside the batch — never deferred to the
  batch review; a failed DC stops the batch. Continuous execution: no
  check-ins between tasks or batches.

## TODO (in order)

1. **Phase 4 — Chunkshop indexing** (`2026-05-14-phase4-chunkshop-indexing.md`, 34 tasks)
   - [ ] Task 0: verify Phase 1+2+3 prereqs + Chunkshop v0.4.1 importable
         (`pip install -e '.[chunkshop]'` resolves the git-tag pin; confirm
         `sinks/{sqlite,pg,mariadb,clickhouse}.py` import).
   - [ ] Tasks 1–33: chunk_store per backend, vector + hybrid retrieval,
         sync/async/skip indexing modes, `TaskBackend` Protocol, config
         consumption. DC-001/DC-002 + DC-FINAL are hard gates.
   - [ ] Decide branch strategy: dedicated `phase4-chunkshop-indexing`
         branch/worktree off main (consistent with prior phases).
2. **Phase 5 — pg-raggraph + Living Knowledge** (38 tasks) — start only after
   Phase 4 merges (needs Phase 4 `chunk_store` + `ChunkshopRetrievalAdapter`).
   Completes Phase 3's `graph_search` `CapabilityError` stub. Needs
   `pg_raggraph` (`[postgres-graph]` extra) — pin/availability TBD, same
   diligence as the Chunkshop pin.
3. **Housekeeping (optional, non-blocking):**
   - [ ] Phase 5 spec frontmatter still says `location: out-of-tree (/tmp/...)`
         — same stale-note cleanup already done for Phase 4 spec.
   - [ ] Tag/branch name `phase3-policy-driven-recall` is ambiguous (tag ==
         branch). Rename tag to e.g. `v-phase3` if it bothers you.
   - [ ] `stele-phase3` worktree can be removed once you're sure nothing else
         needs it (`git worktree remove`).

## Risks / gotchas for the next session

- **Chunkshop install is an external blocker.** Phase 4 Task 0 will halt if
  the git-tag pin can't resolve (needs network + access to
  `github.com/yonk-labs/chunkshop` tag `v0.4.1`). Verify before deep work.
- SQLite memory store is a **separate db file** (`memory_<name>.db` next to
  the artifact db). Deleting only the artifact db leaves stale memories →
  dedup rejects "new" extractions. Clean both when resetting fixtures.
- `Memory.search` now uses OR term semantics (FTS5 sanitizer side effect,
  matches the artifact retrieval convention). Intentional, all tests green.
- Phase plans were authored before the code shipped — expect plan-vs-reality
  drift (attribute/column names, `store(content=...)` not `data=`,
  `Stele.search` needs a reference / `Stele.query` for global). Subagents
  should fix minimally and report deviations, not follow plan text blindly.
