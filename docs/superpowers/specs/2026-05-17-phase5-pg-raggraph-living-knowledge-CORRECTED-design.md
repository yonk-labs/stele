---
phase: 5
title: pg-raggraph Living Knowledge — CORRECTED Design
created: 2026-05-17
status: design (NOT scheduled — blocked on pg-raggraph PRG-1..PRG-4; see §2)
supersedes: docs/superpowers/specs/2026-05-14-phase5-pg-raggraph-living-knowledge-design.md (fiction-vintage)
grounded-in: |
  docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md (GROUND TRUTH)
  docs/superpowers/specs/2026-05-17-pg-raggraph-requirements.md (PRG-1..PRG-5)
  docs/sovereign-memory-system-plan.md (Revisor contract + Living Knowledge Verification Bar)
  Phase 4 proven templates (chunkshop adapter pattern)
---

# Phase 5 — pg-raggraph Living Knowledge (CORRECTED Design)

## §0 — Why this supersedes the 2026-05-14 doc

The `2026-05-14` Phase 5 doc is the **same fiction-vintage** as the original
Phase 4 plan: written against assumed APIs, never validated. The recon
correction sheet (read it first) is ground truth. This document is the
corrected design — durable architecture/SC/DC, **not** a bite-sized task plan
(the task plan is written when Phase 5 is scheduled, from this doc + the recon
sheet; far-ahead task plans rot — the Phase 4 lesson).

## §1 — Ground truth (recap; full detail in the recon sheet)

- `graph_search` is a `CapabilityError` stub; no `Revisor`; no
  `Memory.retract()`; `RecallRequest` has no `as_of`/`version_filter`/
  `retracted_behavior`; no `[postgres-graph]` extra. (Recon §1.)
- pg-raggraph is **owner-controlled Python** (`/home/yonk/yonk-tools/pg-raggraph`,
  PyPI `0.3.0a2`); Rust extension is OUT. The hard engine (temporal `as_of`,
  `version_filter`, `retracted_behavior` hide/flag/surface_both, evolution
  columns, async + direct-DSN lifecycle, chunkshop interop) is **already
  built**. (Recon §0.)
- The only missing pieces are **additive pg-raggraph changes PRG-1..PRG-4**
  (recon §0 / pg-raggraph requirements doc): return generic opaque caller
  metadata + evolution status on hits; post-hoc `retract()`/`supersede()`;
  stable `chunk_id`. **No `stele://` concept goes into pg-raggraph** — it
  round-trips an opaque metadata dict; Stele owns the convention.
- The e2e harness (INFRA-A, done) already has the reserved `graph` profile +
  `tests/e2e/test_living_knowledge.py` skip-gated on `STELE_PG_RAGGRAPH_DSN`,
  encoding the acceptance bar **before** implementation.

## §2 — Dependency gate (Phase 5 Task-0 — coordination, not go/no-go)

Phase 5 is **blocked** until, in pg-raggraph (owner-controlled):

- **PRG-1** generic opaque metadata + evolution status returned on results
- **PRG-2** post-hoc `retract()` API
- **PRG-3** post-hoc `supersede()` API
- **PRG-4** stable, always-returned `chunk_id`

are landed and a pg-raggraph version is **pinned** (an alpha is fine since
owner-controlled) under a new Stele `[postgres-graph]` extra. PRG-5
(chain-current-view) is deferred.

**Task-0 (do alone first; STOP+report on failure):** confirm PRG-1..PRG-4 are
in the pinned pg-raggraph; verify the real async API by reading installed
source (produce the §-equivalent of Phase 4's API table); build the harness
`graph` Postgres image; prove `ingest → as_of → post-hoc retract → re-query`
for real with the opaque ref recovered on every hit. If PRG-1..PRG-4 are not
yet landed, that is a *sequencing* fix (land them first), not a dead end.

## §3 — Architecture

**The Revisor is a projection, never a source of truth.** Memory remains
truth (Phase-1 evolution columns + `supersedes=` + `as_of`); the graph rows
mirror that state so graph queries can honor `as_of`/`retracted_behavior`.
SQLite/non-Postgres deployments keep memory evolution and skip the projection
(`graph_search` → `CapabilityError`, unchanged) — capability honesty per the
sovereign-plan `sovereign-graph` profile.

```
memory.add(supersedes=) / memory.retract() / store()   (truth)
        │  (projection hook, gated on [postgres-graph] + Postgres backend)
        ▼
Revisor (internal, lazy, OptionalDependencyError when extra absent)
        │  async pg-raggraph API  ── async→sync bridge AT THE ADAPTER EDGE ONLY
        ▼
pg-raggraph GraphRAG (PGRGConfig synthesized internally from Stele config;
        dsn reused from the artifact backend; NO os.environ)
        ▼
graph_search strategy ── package-owned SearchHit/MemoryHit (NO native objects)
```

Reuse the **Phase 4 proven templates verbatim in spirit**: lazy import +
`OptionalDependencyError` with pip hint; no native objects escape (translate
at the adapter); `TargetConfig`-style config synthesized internally
(batteries-included — users only set Stele config); capability reporting.

**Concurrency boundary (DC):** pg-raggraph is async; Stele's public API is
sync. The async→sync bridge (`asyncio.run`/runner) lives **only** in the
Revisor/indexing layer. No `asyncio`/`threading` in `retrieval/` or
`recall/` — the existing architecture test (`test_architecture.py`) enforces
this; extend its forbidden-prefix list with `pg_raggraph`.

## §4 — Public API deltas (additive; locked-signature discipline)

The Phase-1/Phase-4 locked-signature rule holds. Phase 5 only **adds**:

- **`Revisor` Protocol** (internal): `ingest_evidence`, `search_current`,
  `search_as_of`, `supersede`, `retract` — the sovereign-plan sketch,
  validated against the real pg-raggraph async API in Task-0. `NoOpRevisor`
  (default) + `PgRaggraphRevisor` (opt-in extra). Never publicly exposed.
- **`Memory.retract(memory_id, *, reason, retracted_at=None)`** — NEW public
  method (additive Phase-1 surface; confirm against the locked-files rule at
  scheduling — adding a method is allowed, changing existing ones is not).
  Sets `status="retracted"` and projects to the Revisor when configured.
- **`RecallRequest`**: add OPTIONAL `as_of: datetime | None = None`,
  `version_filter: str | None = None`,
  `retracted_behavior: Literal["hide","flag","surface_both"] | None = None`.
  Defaults preserve today's behavior exactly for every existing caller.
- **`graph_search`** strategy: fill the existing stub (do NOT reshape the
  recall facade or the other 6 strategies). Returns package-owned hits with
  the recovered opaque ref + evolution status.
- **`StashCapabilities`**: add graph/living-knowledge fields (mirror the
  Phase 4 capability-reporting task).
- **`pyproject.toml`**: new `[postgres-graph]` extra pinning the
  PRG-1..PRG-4 pg-raggraph version. Independent of `[postgres]`.
- `as_of` tz-awareness: Stele normalizes/validates to tz-aware before calling
  pg-raggraph (which rejects naive); surface `ValidationError` early, never a
  raw library error.

## §5 — Projection hooks

Gated on `[postgres-graph]` present AND Postgres backend AND a configured
Revisor (else NoOp):

- `Stele.store(...)` → `Revisor.ingest_evidence(...)` with the Stele ref +
  chunk ids + namespace/session inside the **opaque metadata dict** (PRG-1).
- `Memory.add(supersedes=[...])` → `Revisor.supersede(old, new, reason)` (PRG-3).
- `Memory.retract(...)` → `Revisor.retract(ref, reason, retracted_at)` (PRG-2).
- Read: `recall(strategy="graph_search", as_of=, version_filter=,
  retracted_behavior=)` → `Revisor.search_*` → hits hydrated with the opaque
  ref (PRG-1) so every hit cites `stele://` evidence.

## §6 — Configuration (batteries-included)

Users only ever set Stele config (e.g. a `graph`/`revisor` block under
indexing or a `sovereign-graph` profile). The `PGRGConfig` (dsn, evolution
tier, retracted_behavior default, etc.) is **synthesized internally** from
Stele's config; the DSN is reused from the Postgres artifact backend; no
user-facing pg-raggraph config, no `os.environ` (Phase-4 chunkshop pattern).

## §7 — Success Criteria (from the Living Knowledge Verification Bar)

Derived from `sovereign-memory-system-plan.md` §"Living Knowledge Base" +
the 4 fixture lanes. (IDs SC-P5-xx; finalized into the task plan at scheduling.)

- **SC-P5-01** New evidence can supersede old; superseded is
  deprioritized/hidden per `retracted_behavior`/`supersession_behavior`.
- **SC-P5-02** Retracted evidence is hidden/flagged/surfaced per policy
  (all 3 modes proven).
- **SC-P5-03** `as_of` queries recover the historical view (time-travel).
- **SC-P5-04** `version_filter` returns only the requested version family.
- **SC-P5-05** EVERY living-knowledge hit maps back to exact `stele://`
  evidence (the opaque-metadata round-trip, PRG-1).
- **SC-P5-06** `graph_search` real; the other 6 strategies + locked
  `search`/`query`/`recall` signatures **unchanged** (no regression).
- **SC-P5-07** Non-Postgres / no-`[postgres-graph]` → `graph_search`
  `CapabilityError`; memory evolution still works (capability honesty).
- **SC-P5-08** `Memory.retract()` additive; existing memory API unchanged.
- **SC-P5-09** Capabilities reports graph/living-knowledge state.
- Proven on the **4 fixture lanes**: versioned software docs, retracted
  medical/scientific claims, enterprise policy updates, account-state changes.

## §8 — Drift Checkpoints

- **DC-P5-1** `grep -rn 'pg_raggraph' src/stele/retrieval/ src/stele/recall/`
  empty; arch test forbidden-prefixes includes `pg_raggraph`.
- **DC-P5-2** no `asyncio`/`threading` in `retrieval/`/`recall/` (async→sync
  bridge only in the Revisor/indexing layer).
- **DC-P5-3** locked-signature grep: `search`/`query`/`recall` + the other 6
  strategies unchanged vs the Phase-4 baseline.
- **DC-P5-FINAL** the **Living Knowledge Verification Bar** runs **for real**
  (not skipped) on `tests/e2e/test_living_knowledge.py` via the harness
  `graph` profile across all 4 fixture lanes. **No public living-knowledge
  claim before this gate passes** (sovereign-plan exit gate).

## §9 — Out of scope

- PRG-5 (pg-raggraph supersession-chain "current view" query) — deferred.
- The Rust pg-raggraph extension — explicitly OUT.
- Re-indexing/migration tooling for evolution changes (document the breakage;
  Phase 4 precedent).
- Anything in the sovereign-plan's later phases (connectors, universal search,
  plugin SDK) — Phases 7-9 per the order-of-operations doc.

## §10 — When the task plan gets written

At Phase 5 scheduling (after pg-raggraph PRG-1..PRG-4 land + are pinned), run
`/writing-plans` against THIS doc + the recon sheet to produce the bite-sized
TDD task plan. Not before — it would rot (Phase 4 lesson). This design and the
recon sheet are durable; the task plan is not.
