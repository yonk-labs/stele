# Stele Phase 4 — CORRECTED Plan (supersedes 2026-05-14)

**This replaces `plans/2026-05-14-phase4-chunkshop-indexing.md`** (that one is
fiction). Execute Tasks 11→33 + added scope. Tasks 0–10 + Capabilities-fix +
T28(0.4.2) are DONE (see `phase4-STATUS-HANDOFF.md`).

**GROUND TRUTH:** `docs/superpowers/phase4-recon-correction-sheet.md`. Every
task below assumes you have read it. Spec/SC source:
`docs/superpowers/specs/2026-05-14-phase4-chunkshop-indexing-design.md`
(SC-001..SC-026, DC-001..DC-FINAL — those IDs are still valid; only the *plan's
code* was wrong, not the success criteria).

**Conventions:** TDD; one conventional commit per task `feat(scope): … (SC-xx)`;
trio (`ruff check .` / `mypy src tests benchmarks` / `pytest` with
`STELE_PG_DSN` exported) green before each commit; surgical scope; chunkshop
tests RUN (skip = false pass). Worktree `/home/yonk/yonk-tools/stele-phase4`,
branch `phase4-chunkshop-indexing`.

---

## Task 0 (prereq gate — do alone, STOP on failure)
Bump pin → `chunkshop[all-backends]>=0.4.3,<0.5`; `uv sync --extra all-backends
--extra dev --extra chunkshop`; verify recon §1 API holds on 0.4.3 + the new
`TargetConfig.dsn` field exists (recon §0); cache the embedder
(`chunkshop prefetch` / fastembed); baseline trio green (297/2). Commit:
`feat(deps): bump chunkshop pin to >=0.4.3,<0.5 (Task 28)`.

## Task 11 — `InProcessChunkStore` — committed `2bc3640`, verified-complete (FLAGGED)
**The batch that produced this died mid-run** (it committed Task 11 clean, then
died during Tasks 12/13 — those were left as broken uncommitted strays, since
removed). **Task 11's commit itself crossed the finish line:** all 8
`ChunkStore` Protocol members implemented, full write→vector→keyword→delete→close
round-trip verified working, file not truncated, mypy-clean, 6 tests pass,
chunk_id format `aid:0` correct, numpy hash-embed dim 384, no chunkshop. SC-009
satisfied by evidence. New session: **re-run the round-trip check + 
`pytest tests/unit/storage/test_chunk_store_memory.py` to re-confirm.** Redo
from scratch ONLY if you distrust the provenance — the code is sound on the
evidence. Then proceed to Task 12. (Task 27 later appends a PII-skip test here.)

## Task 12 — dim resolution cascade
Files: `src/stele/indexing/dim_resolution.py`, `tests/unit/indexing/test_dim_resolution.py`.
`resolve_dim_and_similarity(config,*,store)→BakeoffSummary`: bakeoff_file →
auto_detect (probe `store.embed`) → default(384/cosine). SC-006, SC-007.
Commit: `feat(indexing): dim+similarity resolution cascade (SC-006,SC-007)`.

## Task 13 — `chunkshop_adapter`
Files: `src/stele/indexing/chunkshop_adapter.py`, `tests/unit/indexing/test_chunkshop_adapter.py`.
Pure string translation `stele_chunk_id(aid,ord)=="aid:ord"`; round-trip;
malformed→`BackendError`. **No chunkshop import.** SC-011.
Commit: `feat(indexing): chunkshop_adapter chunk_id<->row translation (SC-011)`.

## Tasks 14–17 — chunkshop-backed ChunkStores (the hard part — recon §1 + §0)
Files per task: `src/stele/storage/chunk_store/{sqlite,postgres,mariadb,clickhouse}.py`
+ matching `tests/unit/storage/test_chunk_store_*.py`.
Each: build `Embedder` (load_embedder, MiniLM 384), chunker (reuse
`chunk_index` pattern), `Sink` via `load_sink(TargetConfig(type=…,
**dsn=<literal path | DSN>**, database="stele", table="chunks", hnsw=True,
mode="overwrite"), embed_dim)` — **0.4.3 `dsn` field, NO os.environ**. Retain
`{f"{aid}:{seq}":(text,reference,metadata)}` at `write`; `vector_search` via
`sink.query_top_k`→ hydrate `SearchHit` (score=clamp(1-distance,0,1),
retrieval_mode="vector"); `keyword_search` Stele-local
(`stele.retrieval.rank`); PII regex assert on `write`→`BackendError`;
`embed`/`dim`/`similarity`/`delete`/`close` per Protocol. find_spec guard
targets `"chunkshop"`. Ctors: sqlite `(config,*,db_path)`, others
`(config,*,dsn)`. Tests RUN for real (model cached; pg gated on STELE_PG_DSN;
mariadb/clickhouse gated on `chunkshop.sinks.{mariadb,clickhouse}` + DSN env);
`OptionalDependencyError` test `skipif find_spec("chunkshop") is not None`.
SC-008, SC-010, SC-012, SC-015, SC-026.
Commits: `feat(storage): {SQLite,Postgres,MariaDB,ClickHouse}ChunkStore via chunkshop 0.4.3 sink (SC-008,SC-010,…)`.

## Task 18 — vector + hybrid facades  ⛔ DC-001
Files: `src/stele/retrieval/{vector,hybrid}.py`,
`tests/unit/retrieval/test_{vector,hybrid}.py`. `vector_search(chunk_store,
query,*,limit,reference)`; `hybrid_search(...)` RRF default + weighted_sum +
degrade-with-flag. **No chunkshop import in retrieval/.** Run **⛔ DC-001**:
`grep -rn 'chunkshop\.[a-z_]*' src/stele/retrieval/ src/stele/recall/` MUST be
empty — STOP+report if not. SC-012, SC-013, SC-022.
Commit: `feat(retrieval): vector + hybrid (RRF/weighted) facades (SC-012,SC-013,SC-022) [DC-001]`.

## Task 19 — hybrid quality (load-bearing)  ⛔ DC-003
Files: `tests/fixtures/recall/hybrid_held_out_set.json` (≥20 hand-built
query/relevant pairs), `tests/unit/retrieval/test_hybrid_quality.py`. Assert
`hybrid_recall@5 >= max(vector,keyword) - FLOOR` (`STELE_HYBRID_FLOOR`, default
0.05). Run **⛔ DC-003** — must pass at default floor; STOP+report if it fails
outside the floor (don't lower it in code). SC-014.
Commit: `test(retrieval): load-bearing hybrid quality held-out set (SC-014) [DC-003]`.

## Task 20 — `SyncChunkIndexer` accepts `ChunkStore`
Files: `src/stele/indexing/queue.py` (+ targeted test). Real `__init__(self,
index)` with `submit()`/`status()`/`index_now()` — PRESERVE them; only swap
the write call; branch `isinstance(self._target, ChunkIndex)` vs `ChunkStore`.
`NoOpIndexer` untouched. No regressions in `tests/unit/indexing`.
Commit: `refactor(indexing): SyncChunkIndexer writes through ChunkStore or ChunkIndex`.

## Task 21 — `stash.py` wiring (HIGHEST RISK — recon §2/§3-T21)
Files: `src/stele/core/stash.py` (+ `tests/unit/core/test_stash_facade.py`).
**Keep `search`/`query` signatures EXACTLY.** Add `effective_mode = mode or
self.config.retrieval.default_mode`; branch keyword(existing) / vector / hybrid
internally, scoped to ref (search) or namespace (query). Add `self._chunk_store`
(keep `self.indexer` + call sites); `_build_chunk_store` per backend (0.4.3
`dsn`); `_build_indexer` builds a chunk store whenever `indexing.mode!="skip"`
(NOT gated on `provider`); async worker uses `task.reference` +
`self.storage.fetch(validate_reference_signature(task.reference, signing))`;
add `indexing_status(artifact_id)->IndexResult`; extend `close()` additively
(keep `self.storage.close()`). SC-001(end-to-end), SC-019, SC-020, SC-021.
Commit: `feat(core): Stele mode dispatch + chunk store + indexing_status wiring (SC-019,SC-020,SC-021)`.

## Task 22 — bakeoff overlay in `__init__`  ⛔ DC-004
Files: `src/stele/core/stash.py`, `tests/unit/indexing/test_bakeoff.py` (+
verify/implement `overlay_onto_indexing_config` in `indexing/bakeoff.py`).
Overlay at construction; set `self._bakeoff_summary`. Run **⛔ DC-004**:
`Stele(StashConfig())` → source ∈{auto_detected,default};
`Stele(StashConfig.load({"indexing":{"bakeoff_path":…}}))` → source=="bakeoff_file".
SC-004, SC-005.
Commit: `feat(core): bakeoff overlay at Stele.__init__ (SC-004,SC-005) [DC-004]`.

## Task 23 — `capabilities()` populates `StashCapabilities`
Files: `src/stele/core/stash.py`, `tests/unit/retrieval/test_capabilities.py`.
Populate the 7 Phase 4 fields on the REAL `StashCapabilities` (keep
`storage=`/`retrieval=`); `chunkshop_version` via
`importlib.metadata.version("chunkshop")` (try/except `PackageNotFoundError`);
lazy `resolve_dim_and_similarity` for `bakeoff_summary`. SC-023.
Commit: `feat(core): capabilities() reports chunkshop/bakeoff/task_backend (SC-023)`.

## Task 24 — Phase 3 picks up vector/hybrid (0 recall changes)
Files: `tests/unit/recall/test_artifact_search_vector.py`. With
`retrieval.default_mode` in {vector,hybrid}, `stele.recall.artifact_search(...)`
runs via the internal dispatch — assert `strategy_used=="artifact_search"`.
`store(...)` positional. **Do not touch `recall/`.** SC-024.
Commit: `test(recall): ArtifactSearchStrategy honors default_mode vector/hybrid (SC-024)`.

## Task 25 — vector contract, 5 backends
Files: `tests/contract/test_vector_contract.py`. memory + sqlite (real, model
cached) + postgres (STELE_PG_DSN) + mariadb/clickhouse (gated on
`chunkshop.sinks.{mariadb,clickhouse}` + DSN env). `store(...)` positional;
assert chunk_id `aid:ordinal` round-trips, no native objects leak. SC-015.
Commit: `test(contract): vector retrieval across 5 backends (SC-015)`.

## Task 26 — indexing-modes contract
Files: `tests/contract/test_indexing_modes_contract.py`. skip/sync/async ×
{memory,sqlite,postgres}. `store(...)` positional; align `queued` vs
`pending`; rely on the Task-21 gate fix. SC-019/020/021 (contract level).
Commit: `test(contract): indexing modes skip/sync/async × backends`.

## Task 27 — PII assertion on chunk write
Files: append `tests/unit/storage/test_chunk_store_memory.py` (skip — memory
trusts upstream) + chunkshop-backed real assertion test. SC-026.
Commit: `test(storage): PII boundary assertion on chunkshop-backed write (SC-026)`.

## Task 28 — pin (DONE for 0.4.2; 0.4.3 bump folded into Task 0)
No separate commit beyond Task 0's.

## Task 29 — `__init__.py` exports
Files: `src/stele/__init__.py`. Export `StashCapabilities` (extended),
`BakeoffConfig/Embedder/Chunker/Summary`, `IndexTask`, `TaskStatus`. **Not
`Capabilities`** (deleted). Append to `__all__`; don't reorder existing.
Commit: `feat(api): export Phase 4 public types (SC-003,SC-016,SC-023)`.

## Task 30 — architecture import-layer test
Files: `tests/unit/indexing/test_architecture.py`. Assert no chunkshop import +
no `threading/asyncio` in `src/stele/retrieval/` + `src/stele/recall/`.
`parents[3]` = worktree root. Commit: `test(arch): chunkshop+concurrency stay out of retrieval/recall`.

## Tasks 31–33 — close-out  ⛔ DC-FINAL
- T31: write SC→test map to
  `docs/superpowers/specs/2026-05-16-phase4-chunkshop-indexing-sc-coverage.txt`;
  run the cited tests; every SC-001..026 → a real PASSING test.
- T32: re-run DC-001/002/003/004 (all green).
- T33: full trio; Out-of-Scope grep (`reranker|cross_encoder|MMR|asyncio.create_task`)
  empty; locked-files grep (memory/extraction/recall) empty → **⛔ DC-FINAL**.
Commits: `docs(phase4): SC-001..SC-026 → test map for DC-FINAL`; `chore(phase4): DC-FINAL — full verification`.

---

## ADDED scope (user requirements)

### A. Batteries-included
Files: `scripts/chunkshop-setup.sh` (+ README/CLAUDE/docs update). Script:
`uv`/`pip` install hint → `chunkshop prefetch` (or fastembed model download) →
verify cache → optional backend bring-up (reuse `scripts/postgres-up.sh` /
`docker-compose.backends.yml`). Document offline behavior (`HF_HUB_OFFLINE=1`).
**Verify in code review** that T14–17 synthesize ALL chunkshop config from
`IndexingConfig` (no user-facing chunkshop YAML, no env-var knowledge).
Commit: `feat(ops): chunkshop-setup.sh + batteries-included docs`.

### B. "Make it Real"
- chunkshop-backed contract tests RUN (not skip) on sqlite + postgres — proven
  in T25/T26 output.
- Run & capture: `.venv/bin/python -m benchmarks.showcase`,
  `... -m benchmarks.recall`, `.venv/bin/pytest tests/integration/test_showcase_e2e.py`;
  `benchmarks.answer_workflow` only if an OpenAI-compatible judge endpoint is
  configured (else document as N/A — deterministic benchmarks still prove
  payload reduction / fetch correctness / latency / PII).
- Attach evidence (paths to `benchmarks/runs/<date>/Showcase.{md,json}` etc.)
  in the SC-coverage doc / final report.
Commit: `test(e2e): real chunkshop-backed benchmark + showcase run`.

## Done = DC-FINAL green + SC map complete + batteries script + real
benchmark evidence + trio green → tag `phase4-chunkshop-indexing` → **ask
before merging to main.**
