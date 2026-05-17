---
title: Phase 5 Recon Correction Sheet (GROUND TRUTH)
created: 2026-05-17
status: authoritative — overrides the 2026-05-14 Phase 5 design doc where they conflict
location: docs/superpowers/specs/ (committed on phase4-chunkshop-indexing)
scope: recon + rewrite scope ONLY (no task plan — written when Phase 5 is scheduled)
---

# Phase 5 — Recon Correction Sheet (GROUND TRUTH)

**Why this exists.** Phase 4 taught the lesson the hard way: the
`2026-05-14-phase5-pg-raggraph-living-knowledge-design.md` doc is the **same
vintage and same authoring style** as the original (fictional) Phase 4 plan —
written against *assumed* APIs, never validated against the shipped `stele`
code or the real `pg-raggraph` source. This sheet was produced by reading the
real shipped `stele` code (branch `phase4-chunkshop-indexing`) and the real
`pg-raggraph` sibling. **It is ground truth; the design doc is fiction wherever
it conflicts.** A corrected Phase 5 plan is written *when Phase 5 is
scheduled*, using this sheet — not now (far-ahead task plans rot; that is
exactly how Phase 4 went wrong).

---

## §0 — pg-raggraph reality (RESOLVED — owner-controlled, reviewed 2026-05-17)

**Decision (owner):** integration target is the **Python `pg-raggraph`**
package (`/home/yonk/yonk-tools/pg-raggraph`). The Rust `pg-raggraph-extension`
/ `pg-raggraph-rs` are **OUT** — the design doc's adapter-vs-extension
conflation is closed. pg-raggraph is the user's own project, so missing pieces
are **added to pg-raggraph** (the Phase-4 chunkshop-`dsn` pattern), not worked
around.

**Capability review done (cited gap report, 2026-05-17).** The hard engine is
already built; only a small additive consumer-facing surface is missing:

| Need (Stele Revisor / Verification Bar) | pg-raggraph 0.3.0a2 reality |
|---|---|
| Time-travel `as_of` | ✅ Real — `query(..., as_of=)` → `evolution.evolution_where_clauses` rewrites the SQL WHERE on `effective_from/to`. tz-aware datetime required (naive → ValueError). |
| `version_filter` | ✅ Real — `query(..., version_filter=)`, doc-level `version_label`. |
| `retracted_behavior` hide/flag/surface_both | ✅ Real — `PGRGConfig.retracted_behavior` (default `flag`); hide filters+zeros score, flag score-penalizes, surface_both passes through. |
| Evolution data model | ✅ First-class columns (`effective_from/to`, `retracted`, `retracted_at`, `retraction_reason`, `version_label`, `supersedes_document_id`, `document_versions` table). |
| DSN-direct + async lifecycle | ✅ `GraphRAG(dsn)` async ctx-mgr, internal async pool, auto-migrate. Same shape as chunkshop `dsn`. |
| Ingest with caller metadata | ✅ stored (`documents.metadata` JSONB) — but see gap PRG-1. |
| chunkshop interop | ✅ accepts pre-chunked input + has a chunkshop cookbook pattern (Phase-4 ⇄ Phase-5 fit by design). |
| **Hit cites external `stele://` ref** | ❌ **GAP PRG-1** — metadata is stored but NOT returned in query results; `ChunkResult` has no metadata/external-ref/evolution-status fields. Breaks Stele's #1 invariant. |
| **Post-hoc `retract(ref, reason, when)`** | ❌ **GAP PRG-2** — retraction is ingest-time-only; no method to retract already-stored knowledge. |
| **Post-hoc `supersede(old, new)`** | ❌ **GAP PRG-3** — supersession is ingest-time-only; no post-hoc method. |
| Stable returned `chunk_id` | ⚠️ **GAP PRG-4** — exists but optional; make required+stable. |
| Follow-supersession-chain "latest only" query | ⚠️ **PRG-5 (stretch, defer)** — not required for the bar. |

**pg-raggraph changes required before/with Phase 5 (additive, no redesign):**

- **PRG-1** Return `metadata` + first-class `external_ref` + evolution status
  (`retracted`, `version_label`, `effective_from/to`, `superseded_by`) on
  `ChunkResult`; SELECT them in the naive/local/global retrieval queries.
- **PRG-2** `async def retract(ref|doc_id, reason, retracted_at=None,
  namespace=None)` — atomic UPDATE across `documents` + `document_versions`.
- **PRG-3** `async def supersede(old_ref|id, new_ref|id, reason=None,
  namespace=None)` — post-hoc upsert into `document_versions`.
- **PRG-4** Make returned `chunk_id` stable + always present.
- **PRG-5** (defer) supersession-chain "current view" query mode.

**Revised consequence (risk downgraded from "external blocker" to
"owner-scheduled additive work"):** Phase 5 Task-0 is no longer a *go/no-go on
an uncontrolled external dep* — it is a **coordination gate** between the
pg-raggraph PRG-1..PRG-4 changes and the Stele Revisor work.

> **Phase 5 Task-0 (do alone first; STOP+report on failure):**
> - Confirm PRG-1..PRG-4 are landed in pg-raggraph (a tagged/pinned version —
>   even an alpha is fine since it's owner-controlled; pin the exact version
>   in a new Stele `[postgres-graph]` extra, no `os.environ`).
> - Verify the real async API + the now-returned evolution/`external_ref`
>   fields by reading installed source — produce the §1-equivalent API table.
> - Stand up the pg-raggraph Postgres image (e2e harness `graph` profile);
>   prove ingest→`as_of`→post-hoc `retract`→re-query round-trip **for real**,
>   with the `stele://` ref recovered on every hit.
> - STOP+report only if PRG-1..PRG-4 are NOT yet in the pinned pg-raggraph
>   (then it's a *sequencing* fix — land them first — not a dead end).

---

## §1 — Stele code reality (what the design doc assumes vs what exists)

Verified against `phase4-chunkshop-indexing` (post-Phase-4):

| Design doc assumes | Shipped reality | Evidence |
|---|---|---|
| Phase 5 "replaces the body" of a real `graph_search` | `GraphSearchStrategy.execute()` **unconditionally raises** `CapabilityError("graph_search requires Phase 5 pg-raggraph adapter")` | `src/stele/recall/graph_search.py` |
| Internal `Revisor` Protocol exists to project memory→graph | **Zero `Revisor` code.** No protocol, no class, no `src/stele/revisor/`. Module-level `pg_raggraph` import **forbidden** by an arch test | `tests/unit/recall/test_architecture.py` FORBIDDEN_PREFIXES |
| `Stele.memory.retract()` is a new method | **Absent.** Memory has `add/get/search/list/update/delete` only. `MemoryRecord.status` *can* be `"retracted"` but **no API sets it** | `src/stele/core/memory.py` |
| `Stele.recall(strategy="graph_search", as_of=, version_filter=, retracted_behavior=)` | `RecallRequest` has **no** `as_of` / `version_filter` / `retracted_behavior` fields. `Memory.search(MemoryQuery(as_of=))` **does** work (Phase 1, SQL-level) — but that is memory-search, not recall-graph | `src/stele/recall/models.py`; `src/stele/core/memory_record.py` |
| `Stele.store()` / `memory.add()` project to the Revisor | **No projection hooks anywhere.** | `src/stele/core/stash.py`, `memory.py` |
| pg-raggraph extra independent of `[postgres]` | Extra does not exist yet | `pyproject.toml` optional-deps |

**What IS already true and usable (build on, don't rebuild):**
- Memory evolution columns + `supersedes=` + `as_of` work on SQLite/Postgres
  at the **memory** layer (Phase 1). The Revisor is a *projection of this*, not
  a new source of truth (the sovereign plan is explicit: memory is truth,
  graph rows are derived).
- The recall facade + 6 real strategies + the `graph_search` stub slot are the
  correct seam. Phase 5 fills the stub; it does **not** restructure recall.
- The Phase 4 chunk-store/`TargetConfig(dsn=...)`/no-`os.environ`/lazy-import/
  `OptionalDependencyError`/capability-reporting patterns are the **proven
  templates** for the pg-raggraph adapter. Reuse them verbatim in spirit.

---

## §2 — Per-area corrections the rewritten Phase 5 plan MUST honor

1. **`graph_search` fills the existing stub** — do not change the recall facade
   signature or the other 6 strategies (the locked-signature lesson from Phase
   4 T21). Add `as_of`/`version_filter`/`retracted_behavior` as **optional**
   `RecallRequest` fields with safe defaults so existing callers are unaffected.
2. **`Revisor` is internal-only**, lazy-imported, `OptionalDependencyError`
   when the extra is absent — mirror `_chunkshop_base`. Never expose
   pg-raggraph-native objects; translate to package-owned
   `SearchHit`/`MemoryHit` (the Phase 4 "no native object escapes" + adapter
   pattern).
3. **`Memory.retract()` is new public surface** — additive to `memory.py`
   (which IS in the locked Phase-1 set; adding a method is allowed, changing
   existing ones is not — confirm against the locked-files rule at plan time).
   It sets `status="retracted"` + projects to the Revisor when configured.
4. **Async boundary**: pg-raggraph is async; Stele's public API is sync.
   Decide the bridge (run-in-executor / `asyncio.run` at the adapter edge)
   **inside the indexing/revisor layer only** — concurrency must not leak into
   `retrieval/`/`recall/` (DC-002 still applies; the arch test enforces it).
5. **Verification Bar is the exit gate** — the
   `docs/sovereign-memory-system-plan.md` "Living Knowledge Base" bar
   (supersede / retract / `as_of` / `version_filter` / every hit cites
   `stele://`) becomes the SC set. The e2e harness `graph` profile +
   `tests/e2e/test_living_knowledge.py` (written *before* implementation) is
   where it's proven for real — no skipped graph test counts (the Phase 4
   "skipped = false pass" rule).
6. **Capability honesty**: SQLite/non-Postgres deployments keep memory
   evolution and simply skip the graph projection (`graph_search` →
   `CapabilityError`, as today). The sovereign profiles table
   (`sovereign-graph`) governs.
7. **`as_of` tz-awareness**: pg-raggraph rejects naive datetimes. Stele's
   wrapper must normalize/validate to tz-aware before calling — surface a
   `ValidationError` early, don't pass through a raw library error.

---

## §3 — Rewrite scope (what the corrected Phase 5 design doc must produce)

Not a task list — the boundaries the corrected design must nail when Phase 5
is scheduled:

- **Task-0 gate** (§0) as the first, blocking step.
- **`Revisor` Protocol** + `NoOpRevisor` + `PgRaggraphRevisor` (lazy, opt-in
  extra) — projection contract: `ingest_evidence`, `search_current`,
  `search_as_of`, `supersede`, `retract` (the sovereign-plan sketch, validated
  against the real async API in Task-0).
- **Projection hooks**: where `Stele.store()` / `memory.add(supersedes=)` /
  new `memory.retract()` call the Revisor — additive, gated on the extra.
- **Recall integration**: `graph_search` strategy real; optional
  `as_of`/`version_filter`/`retracted_behavior` on `RecallRequest`;
  default-mode behavior unchanged for non-graph callers.
- **Capabilities**: extend `StashCapabilities` with graph/living-knowledge
  fields (mirror the Phase 4 capability-reporting task).
- **SC/DC set** derived from the Verification Bar; drift checkpoints including
  the arch-test (no pg_raggraph in retrieval/recall; no concurrency leak).
- **Evidence**: the four sovereign-plan fixture lanes (versioned software docs,
  retracted medical claims, enterprise policy updates, account-state changes)
  run for real on the harness `graph` profile.

---

## §4 — Cross-cutting (inject into every Phase 5 implementer)

1. pg-raggraph is **alpha (`0.3.0a2`) + async + `PGRGConfig`-driven** — verify
   the real API in Task-0; never code against the design doc's prose.
2. Adapter, not core: lazy import, `OptionalDependencyError`, no native objects
   escape, `TargetConfig(dsn=...)`-style config — reuse Phase 4 templates.
3. Locked-signature discipline: fill the `graph_search` stub; do not reshape
   the recall facade or the other strategies. New fields are optional+defaulted.
4. Memory is truth, graph is derived projection — never invert this.
5. Concurrency stays out of `retrieval/`/`recall/` (DC-002, arch test).
6. `tests/e2e/test_living_knowledge.py` is written BEFORE the adapter and must
   RUN (not skip) on the harness `graph` profile — skipped = false pass.
7. Memory `retract()` is additive Phase-1-surface work — confirm against the
   locked-files rule before touching `memory.py`.
