# Episodic Recall (Phase 1) Implementation Plan

> **For agentic workers:** execute task-by-task with TDD. Steps use `- [ ]`.
> Spec: [docs/superpowers/specs/2026-06-04-episodic-recall-design.md](../specs/2026-06-04-episodic-recall-design.md).

**Goal:** Add an `episodic` recall strategy that retrieves a past session (its
artifact + back-linked memories), temporally aware via `parse_temporal` as a soft
boost (hard filter opt-in).

**Architecture:** Compose existing primitives. New code: a back-link memory query,
an `EpisodicStrategy`, an `EpisodeHit`, registry wiring. No new storage tables.

**Tech Stack:** Python 3.12, existing `recall/` Protocol strategies, `parse_temporal`
(`stele.retrieval.temporal`), memory stores (memory/sqlite/postgres).

**Scope:** Phase 1 only (episode = one session). Phase 2 (episode summaries) and
Phase 3 (timeline, spans) are out of scope per the spec.

---

### Task 1: `memory.by_source_ref` back-link query

**Files:**
- Modify: `src/stele/core/memory.py` (facade method)
- Modify: `src/stele/storage/memory_store/{base,memory,sqlite,postgres}.py`
- Test: `tests/contract/test_memory_contract.py`

- [ ] **Step 1: failing contract test** — store an artifact, add two memories
  citing its ref + one citing another ref; assert `memory.by_source_ref(ref)`
  returns exactly the two, active-head only.
- [ ] **Step 2: add to `MemoryStore` base** — `by_source_ref(self, scope, ref, *,
  status_filter=("active",)) -> list[MemoryRecord]`.
- [ ] **Step 3: implement per store** — memory: filter records whose
  `source_refs` contains `ref`; sqlite/postgres: `WHERE source_refs LIKE/@>`
  (JSON contains) + scope + status, reusing the existing scope/temporal SQL.
- [ ] **Step 4: facade passthrough** on `Stele.memory`.
- [ ] **Step 5: run contract test green; commit.**

### Task 2: `EpisodeHit` model + temporal helper

**Files:**
- Modify: `src/stele/recall/base.py` or `src/stele/core/recall_models.py`
- Test: `tests/unit/recall/test_episodic.py`

- [ ] **Step 1: define `EpisodeHit`** — `{session_id: str|None, when: datetime|None,
  summary: str, ref: str, score: float, memories: list[MemoryRecord]}`.
- [ ] **Step 2: temporal helper** — `_episode_when(artifact) -> datetime` (prefer
  `metadata.session_mtime`, else `created_at`); `_boost(score, when, window)` for
  the soft-boost (proximity/recency), unit-tested with a few windows.
- [ ] **Step 3: run; commit.**

### Task 3: `EpisodicStrategy` (soft-boost default)

**Files:**
- Create: `src/stele/recall/episodic.py`
- Modify: `src/stele/recall/facade.py`, `src/stele/recall/adaptive.py` (register
  `"episodic"`), add `Stele.recall.episodic(...)` shim
- Test: `tests/unit/recall/test_episodic.py`, `tests/unit/recall/test_architecture.py`

- [ ] **Step 1: failing test** — fixture of 3 dated session artifacts + back-linked
  memories; `recall(query="...", strategy="episodic")` returns `EpisodeHit`s
  newest-relevant first, each carrying its memories.
- [ ] **Step 2: implement** — `parse_temporal` -> `(cleaned, window)`; candidates =
  session-ingest artifacts in scope; rank by semantic search on `cleaned`;
  apply `_boost` (never exclude); attach `by_source_ref` memories; build
  `RecallResult` (context block) + the `EpisodeHit` list.
- [ ] **Step 3: register** in both registries; add the facade shim.
- [ ] **Step 4: architecture test** — assert `recall/episodic.py` imports no LLM
  client / pg_raggraph / chunkshop / lede (the recall invariant).
- [ ] **Step 5: run green; commit.**

### Task 4: hard-filter opt-in + empty-window fallback

**Files:**
- Modify: `src/stele/recall/episodic.py`, `src/stele/core/recall_models.py`
  (`RecallRequest.hard_temporal: bool = False`)
- Test: `tests/unit/recall/test_episodic.py`

- [ ] **Step 1: failing tests** — (a) `hard_temporal=True` excludes
  out-of-window episodes; (b) a window that matches too few candidates falls
  back to unfiltered rank rather than returning empty (anti-backfire rule).
- [ ] **Step 2: implement** the hard path + the fallback threshold.
- [ ] **Step 3: run green; commit.**

### Task 5: contract test across backends

**Files:**
- Test: `tests/contract/test_recall_contract.py`

- [ ] **Step 1: parametrize** the `episodic` strategy across `BACKENDS`
  (memory + sqlite; postgres when `STELE_PG_DSN` set), mirroring the other
  strategies: build dated episodes, assert "last week" returns the right one
  with its memories, and that a wrong window falls back.
- [ ] **Step 2: run `ruff` + `mypy` + `pytest`; commit.**

---

## Done criteria
- `Stele.recall(strategy="episodic", query=...)` returns episodes (artifact +
  back-linked memories), temporally soft-boosted, hard-filter opt-in, with the
  empty-window fallback.
- Recall invariant intact (no LLM/graph imports in `episodic.py`).
- ruff + mypy clean; new unit + contract tests green; no change to existing
  strategies.

## Deferred (not this plan)
- Phase 2: distilled episode summaries (`Stele.distill.episodes`).
- Phase 3: `timeline()` ordered view + cross-session span linking via the graph.
