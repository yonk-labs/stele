---
title: Phase 5 Task-0 — pg-raggraph 0.3.0a3 REAL API Recon (GROUND TRUTH)
created: 2026-05-17
status: authoritative — produced by introspecting the INSTALLED pg-raggraph 0.3.0a3
        (.venv site-packages), not the design prose. Inject into every Phase 5 task.
pinned: pg-raggraph==0.3.0a3 (PyPI; Stele [postgres-graph] extra)
verified-by: src reading + runtime introspection in stele-phase5/.venv
---

# Phase 5 Task-0 — pg-raggraph REAL API (recon-is-truth)

This is the Phase-4-equivalent API table, produced by reading the **installed**
`pg-raggraph 0.3.0a3` (PyPI) — the code Stele actually runs against. Code
against THIS, never the design doc's prose.

## PRG gate — VERIFIED in installed 0.3.0a3 source

| PRG | Status | Evidence (installed source) |
|---|---|---|
| PRG-1 opaque metadata + evolution on results | ✅ | `models.ChunkResult`: `metadata: dict\|None`, `retracted: bool\|None`, `version_label: str\|None`, `effective_from/effective_to: datetime\|None`, `superseded_by_id: int\|None` — all optional. `retrieval.py` SELECTs+maps them. |
| PRG-2 post-hoc `retract()` | ✅ | `GraphRAG.retract(*, doc_id=None, source_path=None, reason='', retracted_at=None, namespace=None) -> dict {"retracted_count": int}`. tz-aware (naive → ValueError); idempotent. |
| PRG-3 post-hoc `supersede()` | ✅ | `GraphRAG.supersede(*, old_doc_id=None, old_source_path=None, new_doc_id=None, new_source_path=None, reason=None, effective_at=None, namespace=None) -> dict`. |
| PRG-4 stable `chunk_id` | ✅ | `ChunkResult.chunk_id: int\|None` w/ stability guarantee docstring; populated by retrieval queries. |

**Gate result: PASS — PRG-1..4 are in the pinned 0.3.0a3. Not a STOP+report.**
PRG-5 (chain "current view") intentionally absent/deferred.

## Public surface

`pg_raggraph.__all__ = ['GraphRAG', 'INGEST_ALLOWED_EXTS', 'PGRGConfig', 'QueryResult', '__version__']`

## GraphRAG — real async API

```
GraphRAG(dsn: str | None = None, *, reranker=None, **kwargs)   # kwargs → PGRGConfig fields
  async with GraphRAG(dsn, **cfg) as rag: ...                  # __aenter__/__aexit__

await rag.ingest(paths: list[str], namespace=None, on_progress=None,
                 *, metadata: dict | None = None)              # FILE paths; metadata = per-batch evolution hints
await rag.ingest_records(records, namespace=None, on_progress=None)   # in-memory records (Stele path)
await rag.query(question: str, mode='smart', namespace=None, *,
                as_of: datetime | None = None,                 # tz-aware REQUIRED (naive → error)
                version_filter: str | None = None,
                evolution_aware: bool | None = None,
                rerank: bool = False) -> QueryResult
await rag.ask(...)                                             # same as query + short_answer
await rag.retract(*, doc_id=None, source_path=None, reason='',
                  retracted_at=None, namespace=None) -> dict    # {"retracted_count": int}
await rag.supersede(*, old_doc_id=None, old_source_path=None,
                    new_doc_id=None, new_source_path=None,
                    reason=None, effective_at=None, namespace=None) -> dict
await rag.delete_document(source_path: str, namespace=None) -> int
```

## ingest_records — Stele's projection entry point

Each record dict:
- `text` (str, **required**)
- `source_id` (str, **required**) — stable logical id. **Serves the same role
  as `source_path`** (`__init__.py:755`, `file_path = source_id`,
  `meta.setdefault("source_path", source_id)`). Re-ingest of same `source_id`
  with new text replaces prior version atomically (content-hash dedup).
- `metadata` (dict, optional) — **opaque** JSONB on `documents.metadata`.
  Evolution keys (`effective_from/to`, `retracted`, `version_label`,
  `supersedes_document_id`) ALSO mirrored to dedicated columns; other keys
  JSONB-only. **This is the PRG-1 round-trip — Stele rides `stele://` here.**
- `entities` / `relationships` (optional) — caller-known graph seed.
- `skip_llm` (bool, optional) — per-record skip of LLM extraction.
- `pre_chunked` (list[dict], optional) — **bypass pg-raggraph chunker AND
  embedder**. Stele owns chunking (Phase-4 chunkshop) → use this.

### THE addressing linchpin (post-hoc retract/supersede)
`source_id` → stored as `documents.source_path`. So Stele addresses
`retract(source_path=<the source_id it ingested>)` and
`supersede(old_source_path=, new_source_path=)` by the **same deterministic
string** — no need to capture pg-raggraph's integer `doc_id`. Stele's
convention: `source_id = stele://<namespace>/<memory_id>` (also rides in
`metadata["stele_ref"]` for the read-side recovery).

## ChunkResult / QueryResult fields

`ChunkResult`: `content:str`, `score:float`, `document_source:str|None`,
`entities:list[str]`, `chunk_id:int|None`, **PRG-1:** `metadata:dict|None`,
`retracted:bool|None`, `version_label:str|None`,
`effective_from/effective_to:datetime|None`, `superseded_by_id:int|None`.

`QueryResult`: `answer:str`, `chunks:list[ChunkResult]`, `entities`,
`relationships`, `query_mode:str`, `latency_ms:float`, `top_score:float`,
`avg_score:float`, `confidence:str`.

→ A hit recovers its `stele://` ref via `chunk.metadata["stele_ref"]`
(primary, PRG-1) or `chunk.document_source` (== ingested `source_id`).

## PGRGConfig — Stele synthesizes this internally (batteries-included)

Defaults that MUST be overridden for the Stele harness (no external services):

| Field | pg-raggraph default | Stele must set | Why |
|---|---|---|---|
| `dsn` | `postgresql://postgres:postgres@localhost:5434/pg_raggraph` | reuse Postgres artifact-backend DSN | no os.environ; batteries-included |
| `embedding_provider` | `local` (FastEmbedProvider, `BAAI/bge-small-en-v1.5`, dim 384) | keep `local` | **offline-capable, no API/LLM**; model cached after 1st fetch |
| `skip_extraction` | `False` (LLM at ollama `:11434`) | **`True`** | harness has no LLM; living-knowledge bar doesn't need graph extraction |
| `evolution_tier` | `off` (evolution fields → None) | **`structural`** | first non-off tier; enables `effective_from/to`/`retracted`/`version_label`/supersedes WITHOUT fact-extraction LLM |
| `retracted_behavior` | `flag` | per-request (`hide`/`flag`/`surface_both`) | SC-P5-02 (all 3 modes) |
| `supersession_behavior` | `surface_both` | per-policy | enum is **`hide` \| `prefer_new` \| `surface_both`** (NOT `flag`) |

### Recon corrections vs the CORRECTED design doc
- Supersession modes are `hide | prefer_new | surface_both` — the design's
  "supersede deprioritized/hidden" maps to `prefer_new`/`hide` (no `flag`).
- `as_of`/`retracted_at` are tz-aware-REQUIRED (naive → ValueError). Stele's
  wrapper normalizes/validates to tz-aware and raises `ValidationError` early
  (recon sheet §2.7).
- Evolution columns are inert unless `evolution_tier != 'off'`. The Revisor
  MUST synthesize `evolution_tier='structural'` (or higher) or the entire
  living-knowledge bar silently no-ops.
- Stele ingests via `ingest_records` + `pre_chunked` + `skip_llm=True`
  (owns chunking via chunkshop; no pg-raggraph chunker/embedder dup, no LLM).
- Schema is auto-migrated by pg-raggraph on first connect (`db._ensure_schema`)
  but the `vector` + `pg_trgm` EXTENSIONS must pre-exist — the harness image
  seeds both via an initdb script (`schema.sql:2`). Stele's own store
  self-creates `vector`; pg-raggraph does NOT, and ALSO needs `pg_trgm`
  (`gin_trgm_ops`) — Task-0 caught this; the "only vector" prose was wrong.

## §Task-0 PROVEN semantics (round-trip executed FOR REAL — 14/14 PASS)

Proven against the harness `graph` profile (port 55453) with the installed
0.3.0a3. These are LOAD-BEARING for the Phase 5 design/SC set — verified in
`evolution.py`, not assumed:

1. **`as_of` requires an explicit `effective_from`.** Ingest WITHOUT one →
   `documents.effective_from = NULL` → "always effective" → `as_of` does NOT
   gate it (time-travel silently no-ops). **The Revisor MUST project the
   memory's `effective_from` (tz-aware) into the per-record `metadata`.** This
   is non-optional for SC-P5-03.
2. **`retracted_behavior="hide"` is ABSOLUTE, not `as_of`-aware.**
   `evolution_where_clauses` adds a bare `NOT d.retracted` (`evolution.py:112`)
   with no `retracted_at <= as_of` term. A retracted doc vanishes from BOTH
   current AND `as_of` historical queries. "Unsay it entirely."
3. **`retracted_behavior="flag"` / `"surface_both"` keep the doc
   retrievable** with `chunk.retracted is True` and `metadata` recovered.
   This is the ONLY way to honor "every hit cites `stele://`, even retracted
   ones" historically. → SC-P5-02 must test all three modes; the "retracted
   medical/scientific claims" fixture lane uses `flag`/`surface_both` (cite +
   mark), NOT `hide` (which erases the citation).
4. **`supersede()` IS `as_of`-aware** (DEC-10): sets the old doc's
   `effective_to`; `as_of` before the supersession `effective_at` still
   returns the old version; `supersession_behavior="hide"` hides it from
   current. Supersession ≠ retraction: supersession preserves history,
   `hide`-retraction erases it.
5. Return shapes: `retract() -> {"retracted_count": int}` (idempotent),
   `supersede() -> {"updated": int}`.
6. Offline confirmed: `embedding_provider="local"` (FastEmbed) +
   `skip_extraction=True` + per-record `skip_llm=True` → ingest/query/retract/
   supersede all work with ZERO external services. `evolution_tier="structural"`
   activates the evolution columns.

**Design consequence:** the Revisor's `retracted_behavior` is policy-driven
per recall request (SC-P5-02). Stele's "cite the evidence" invariant means
the living-knowledge default leans `flag`/`surface_both` (citation survives
retraction); `hide` is opt-in "right-to-be-forgotten"-style erasure. The 4
fixture lanes each pin the mode their scenario demands.
