---
title: pg-raggraph — Required Additions (driven by Stele Phase 5)
created: 2026-05-17
status: requirements — for the pg-raggraph project (owner-controlled)
audience: pg-raggraph maintainers (this is a feature-request spec, copy/port freely)
grounded-in: cited capability review of pg-raggraph 0.3.0a2 source, 2026-05-17
consumer: Stele Phase 5 (pg-raggraph living-knowledge adapter) — but every
          change below is product-neutral and benefits any consumer
---

# pg-raggraph — Required Additions

## Why this exists

Stele's Phase 5 builds a living-knowledge adapter on pg-raggraph. A cited
review of pg-raggraph `0.3.0a2` found the **hard engine is already built and
solid** — temporal `as_of`, `version_filter`, `retracted_behavior`
(hide/flag/surface_both), first-class evolution columns, async + direct-DSN
lifecycle, and pre-chunked/chunkshop interop. What's missing is a small
**consumer-facing surface**. This doc specifies exactly those additions.

## Governing principle: product-neutral, optional, back-compatible

**Non-negotiable for every item below:**

1. **No consumer-specific concepts in pg-raggraph.** pg-raggraph must not know
   what "Stele" or `stele://` is. The provenance round-trip is a **generic
   opaque metadata pass-through** — pg-raggraph already *stores* arbitrary
   caller metadata in `documents.metadata`; it just needs to *hand it back*.
   Stele (or any consumer) puts whatever it wants in there. pg-raggraph treats
   it as an opaque `dict`.
2. **100% optional.** A caller that ingests no metadata, or never calls the
   new methods, sees **identical behavior to today**. New result fields
   default to `None`/empty. No new required parameters anywhere.
3. **Back-compatible.** No breaking change to existing signatures, return
   shapes (additive fields only), schema (additive columns/uses-existing), or
   defaults. Existing pg-raggraph users notice nothing.
4. **Owner-controlled, so additive.** pg-raggraph is the same owner's project;
   these land as normal additive releases (an alpha bump is fine) — the
   consumer pins an exact version.

---

## PRG-1 — Return caller metadata + evolution status on query results  *(critical)*

**Problem.** `GraphRAG.ingest()` / `ingest_records()` accept and persist
arbitrary caller `metadata` (→ `documents.metadata` JSONB), but `query()` /
`ask()` results (`ChunkResult` in `models.py`) **do not return it**, and do not
return the document's evolution status. A consumer cannot recover *which
source a hit came from* or *why a hit was flagged/penalized*. For any consumer
whose contract is "every answer cites its source," this is a hard blocker —
the data exists in the DB but is invisible at read time.

**Required change.** Add to `ChunkResult` (additive, all optional):

```python
class ChunkResult(...):
    # ... existing fields unchanged ...
    metadata: dict | None = None          # the opaque caller metadata as ingested
    retracted: bool | None = None         # documents.retracted
    version_label: str | None = None      # documents.version_label
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    superseded_by_id: int | None = None   # document_versions.supersedes_document_id (inverse)
```

Populate them by `SELECT`ing the existing columns in the naive / local /
global retrieval queries (`retrieval.py`) and mapping into `ChunkResult`.

**Optionality.** If a document was ingested without metadata, `metadata` is
`None`. Evolution fields are `None` when `evolution_tier="off"`. Consumers
that ignore the new fields are unaffected.

**Why generic, not a `source_ref` field.** Deliberately a free-form `dict`,
not a typed `external_ref`/`source`. pg-raggraph stays neutral; the consumer
owns the key convention (Stele will use e.g. `metadata["stele_ref"]`, but
pg-raggraph neither defines nor validates that).

**Acceptance.**
- Ingest a doc with `metadata={"k": "v"}`; a `query()` hit for that doc
  returns `chunk.metadata == {"k": "v"}` (plus any evolution fields it merged).
- Ingest with no metadata → hit `.metadata is None`; all existing fields and
  scores byte-identical to pre-change.
- A retracted doc under `retracted_behavior="flag"` returns
  `chunk.retracted is True` so the caller can act on it.
- `evolution_tier="off"` → evolution fields `None`, zero behavior change.

---

## PRG-2 — Post-hoc `retract()` API  *(high)*

**Problem.** Retraction is **ingest-time only** (`metadata={"retracted": True,
...}`). But knowledge is retracted *after* it was stored — that is the entire
point of living knowledge. There is no way to mark an already-ingested
document retracted without re-ingesting (which hits content-hash dedup and may
skip).

**Required change.** Add an async method:

```python
async def retract(
    self,
    *,
    doc_id: int | None = None,
    source_path: str | None = None,   # one of doc_id/source_path required
    reason: str = "",
    retracted_at: datetime | None = None,   # default: now(), tz-aware
    namespace: str | None = None,
) -> dict:   # {"retracted_count": int}
    ...
```

Atomically set `documents.retracted=true` and write
`document_versions.{retracted, retracted_at, retraction_reason}` for the
matched document(s). tz-aware `retracted_at` (reject naive, consistent with
`evolution_where_clauses`).

**Optionality.** Purely additive; consumers that never retract are unaffected.

**Acceptance.**
- Ingest a normal doc; `retract(doc_id=...)`; an `as_of=<before>` query still
  returns it, an `as_of=<after>`/current query honors `retracted_behavior`.
- Idempotent: retracting an already-retracted doc is a no-op success.
- Naive `retracted_at` → `ValueError` (same rule as `as_of`).

---

## PRG-3 — Post-hoc `supersede()` API  *(high)*

**Problem.** Supersession is **ingest-time only** (`metadata=
{"supersedes_document_id": N}`). A consumer that learns "doc B replaces doc A"
*after* both exist has no API to record it.

**Required change.** Add an async method:

```python
async def supersede(
    self,
    *,
    old_doc_id: int | None = None,
    old_source_path: str | None = None,
    new_doc_id: int | None = None,
    new_source_path: str | None = None,
    reason: str | None = None,
    effective_at: datetime | None = None,   # default now(), tz-aware
    namespace: str | None = None,
) -> dict:   # {"updated": int}
    ...
```

Upsert `document_versions.supersedes_document_id` (new → old) and set the old
doc's `effective_to = effective_at` so existing temporal/`supersession_behavior`
logic applies with zero new query code.

**Optionality.** Additive; unaffected if never called.

**Acceptance.**
- Ingest A then B; `supersede(old=A, new=B)`; current query honors
  `supersession_behavior`; `as_of=<before effective_at>` still returns A.
- Reuses existing `effective_to`/`supersedes_document_id` semantics — no new
  query-path branching required.

---

## PRG-4 — Stable, always-present `chunk_id` on results  *(tiny)*

**Problem.** `ChunkResult.chunk_id` exists but is optional; consumers that
need a stable join key for audit trails / dedup back to their own chunk ids
can't rely on it.

**Required change.** Guarantee `chunk_id` is always populated and stable
across re-queries for the same stored chunk. No signature change — a
correctness/consistency guarantee + documentation.

**Acceptance.** Same chunk returned by two queries has an identical,
non-null `chunk_id`.

---

## PRG-5 — Supersession-chain "current view" query mode  *(stretch — DEFER)*

**Not required for Phase 5's verification bar.** A query mode that follows
`supersedes_document_id` transitively to return only the latest version of a
document family. `supersession_behavior` already covers hide/penalize; chain-
following is an optimization. Listed for completeness; **do not build now.**

---

## Back-compat & optionality guarantee (summary)

| Concern | Guarantee |
|---|---|
| Existing query results | Only additive optional fields; existing fields/scores unchanged |
| Existing callers | No new required params anywhere; no behavior change without opt-in |
| Schema | Uses existing columns (`documents.*`, `document_versions.*`); no destructive migration |
| `evolution_tier="off"` | New evolution fields `None`; engine behavior identical to today |
| pg-raggraph neutrality | No consumer concept (`stele://` etc.) anywhere; metadata is opaque `dict` |
| Versioning | Ships as additive alpha bump; consumer pins exact version |

## How the consumer (Stele) uses this — proves the optionality

Stele will, *on its side only*:
- ingest with `metadata={"stele_ref": "stele://ns/id", "chunk_id": "...", ...}`
  — an opaque dict to pg-raggraph;
- read it back from `chunk.metadata["stele_ref"]` (PRG-1) to satisfy its own
  "cite the evidence" rule;
- call `retract()` / `supersede()` (PRG-2/3) when its memory layer supersedes
  or retracts;
- use `chunk.retracted` / `version_label` (PRG-1) to honor its recall policy.

pg-raggraph never sees a Stele concept. Any other consumer can do the same
with its own keys. The `stele://` convention lives 100% in Stele.

## Priority & sizing

| Item | Priority | Size | Blocks Phase 5? |
|---|---|---|---|
| PRG-1 metadata + evolution round-trip | Critical | S (result schema + SELECT in 3 queries) | Yes — hard blocker |
| PRG-2 post-hoc `retract()` | High | S (one atomic UPDATE) | Yes — verification bar |
| PRG-3 post-hoc `supersede()` | High | S (one upsert) | Yes — verification bar |
| PRG-4 stable `chunk_id` | Low | XS (guarantee + doc) | No — quality |
| PRG-5 chain "current view" | Defer | M | No |

**Definition of ready for Phase 5 Task-0:** PRG-1, PRG-2, PRG-3, PRG-4 landed
in a pinned pg-raggraph version; PRG-5 explicitly deferred.
