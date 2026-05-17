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

## §0 — pg-raggraph reality (the chunkshop lesson, repeated)

| Claim in design doc | Reality (verified 2026-05-17) |
|---|---|
| `pg_raggraph >= X.Y`, extra `[postgres-graph]` | **Not pinned anywhere.** No `pg_raggraph` / `postgres-graph` extra in `pyproject.toml`. |
| (implied: a stable published dep) | On PyPI as **`pg-raggraph==0.3.0a2`** — an **alpha**. Sibling `/home/yonk/yonk-tools/pg-raggraph` at `0.3.0a2`; Rust extension in `/home/yonk/yonk-tools/pg-raggraph-extension`; `pg-raggraph-rs` also present. |
| (implied: synchronous adapter) | Real API is **async** and **`PGRGConfig`-driven**. Evolution is real: `evolution_where_clauses(cfg, as_of=...)`, `retracted_behavior` default `"flag"` (modes `hide`/`flag`/`surface_both`), **`as_of` requires a tz-aware datetime** (naive rejected), supersession via `effective_from`/`effective_to`. |

**Consequence:** Phase 5 needs a **Task-0 prereq gate identical in spirit to
Phase 4's**, run *at execution time*, not assumed now:

> **Phase 5 Task-0 (do alone first; STOP+report on failure):**
> - Decide the pg-raggraph artifact: PyPI `pg-raggraph` (alpha `0.3.0a2` — is
>   that acceptable for a shipped feature, or pin a tested commit / wait for a
>   stable release?) **vs** the Rust `pg-raggraph-extension` (DB-side) — they
>   are different things; the design doc conflates "the adapter" with "the
>   extension".
> - `uv sync` it under a new `[postgres-graph]` extra; verify the **real async
>   API** surface (config object, query entry point, the evolution kwargs
>   `as_of` / `version_filter` / `retracted_behavior`) by reading installed
>   source — produce the §1 equivalent of Phase 4's API table.
> - Stand up the pg-raggraph-enabled Postgres image (the e2e harness `graph`
>   profile) and confirm a trivial ingest→as_of→retract round-trip works
>   **for real** before writing any Stele wrapper.
> - If the API is alpha-unstable or the extension/DB story doesn't hold:
>   **STOP — external blocker**, exactly as Phase 4 Task-0 did for chunkshop
>   0.4.3.

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
