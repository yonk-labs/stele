# Audit — pg-raggraph retrieval-profile migration (stele)

Date: 2026-05-24
Scope: audit stele's pg-raggraph usage against the new `retrieval_profile`
ladder; decide what to change now vs. stage; document per-namespace defaults.

## Verdict

**No code change now.** The new profile API is not in stele's pinned
`pg-raggraph==0.3.0a3`, and stele does not use the anti-patterns the migration
targets (`top_k`, `mode="hybrid"` literals in product code, manual context
concatenation). The migration is staged behind a pin bump and documented below.

## Evidence

- Pinned/installed: `pg-raggraph==0.3.0a3` (`pyproject.toml` extra
  `postgres-graph`).
- Installed `GraphRAG.query` signature (verified at audit time):
  `query(self, question, mode, namespace, as_of, version_filter,
  evolution_aware, rerank)` — **no `profile` parameter.** Passing `profile=`
  would raise; PGRGConfig also rejects unknown kwargs (see the revisor docstring
  / `core/config.py` notes).
- stele's only retrieval calls are in
  `src/stele/revisor/pg_raggraph_revisor.py`:
  - `search_current` and `search_as_of` →
    `rag.query(query, mode=self._query_mode, namespace=…, version_filter=…,
    rerank=self._rerank[, as_of=…])`, then `[:limit]` client-side.
  - non-retrieval: `ingest_records`, `supersede`, `retract`, `status`, `delete`.
- Product-code grep for `top_k`, `mode="hybrid"`, `mode="summary"`, manual
  concat: **no hits** in `src/`.
- The retrieval lever stele exposes today is `GraphConfig.query_mode`
  (`smart`/`hybrid`) + `rerank` (see `core/config.py`), surfaced via the
  `graph_search` recall strategy.

## Checklist audit (against the supplied best-practices list)

| # | Item | Status in stele |
|---|---|---|
| 1 | Search for `top_k` / `mode=` / manual concat | Done — none in product code; only `mode=`/`rerank` in the revisor |
| 2 | Replace product retrieval choices with `profile=` | **Deferred** — API absent in 0.3.0a3 |
| 3 | Keep `raw` as escape hatch, not default | Will map `profile="raw"` from today's untuned `mode="smart"` path |
| 4 | User-facing default `balanced` | Will set `GraphConfig.profile` default = `balanced` |
| 5 | Offer `accurate` for high-stakes/low-recall | Will expose via per-call + namespace profile |
| 6 | Offer `cheap`/`cheap_plus` for background | Same |
| 7 | One corpus type per namespace | Already the stele guidance (`living-knowledge-setup.md`); reinforce |
| 8 | If latency constant across profiles, profile SQL/embedding/hydration first | N/A to stele code — the fix is a pg-raggraph migration (below) |
| 9 | Ensure graph-hydration index + namespace-profile migrations applied | **Action** — verify in stele's deploy once the release lands |
| 10 | Integration tests prove `profile` passthrough + `raw` support | Will add to the migration slice |

## Latency fix (pg-raggraph-internal — stele inherits it)

The ~1.4s/query issue root cause was graph hydration, not packing:
`entity_chunks` lacked a `chunk_id` index and relationship hydration scanned too
much. Fix in pg-raggraph: `idx_entity_chunks_chunk ON entity_chunks(chunk_id)` +
relationship-ID-first hydration CTEs (→ ~280ms/query on LoCoMo hybrid smoke;
local BGE-large embedding remains the dominant cost).

stele does not own these migrations. Action on pin bump: ensure stele's graph
deploy path (`deploy/docker-compose.full.yml` graph profile, `tests/e2e`) runs
pg-raggraph's migrations so the index + namespace-profile tables exist. No stele
schema change required.

## Staged migration plan (executes when pg-raggraph releases the profile API)

Trigger: a pg-raggraph release whose `GraphRAG.query`/`ask` accept `profile=`,
and the `postgres-graph` pin is bumped to it.

1. **Config** — add `GraphConfig.profile: str = "balanced"` (accepts names,
   integer rungs, 0..1 slider floats, per the new resolver). Keep
   `query_mode`/`rerank` only if the release still honors them; otherwise mark
   deprecated. Add optional per-namespace profile overrides
   (`graph.namespace_profiles: dict[str, str]`).
2. **Revisor** — in `search_current` + `search_as_of`, replace
   `mode=self._query_mode, rerank=self._rerank` with `profile=<resolved>`.
   Resolution order (mirrors pg-raggraph): per-call profile > namespace profile
   > `GraphConfig.profile` default. This is the only retrieval-call change.
3. **Escape hatch** — `profile="raw"` preserves classic chunk behavior; expose
   it through the recall request so a caller can force legacy retrieval for
   debugging/compat. Never the default.
4. **Recall surface** — thread an optional `profile` through the `graph_search`
   recall strategy / `RecallRequest` (additive; default `None` → namespace/
   global default).
5. **Tests** — integration test asserting (a) the intended `profile` reaches
   `GraphRAG.query`, and (b) `profile="raw"` still works. Keep the architecture
   invariant: pg-raggraph is imported only inside the revisor.
6. **Docs** — update `living-knowledge-setup.md` with the profile knob + the
   per-namespace defaults table below.

Estimated blast radius: `core/config.py` (one field + resolver), the revisor
(two call sites), `recall/graph_search.py` + `recall/models.py` (one optional
param), one integration test, one doc. Well within a single thin slice.

## Chosen per-namespace / KB-type defaults (to document on migration)

stele's graph namespaces are living-knowledge / agent-memory KBs. Proposed
defaults (overridable per namespace, then per call):

| KB / namespace type | Default profile | Rationale |
|---|---|---|
| Default agent-memory KB | `balanced` | F-informed default; coverage-led packing |
| High-stakes / low-recall recall | `accurate` (`full_selected_docs@10`) | recall ceiling when coverage matters |
| Conversational / session memory | test `balanced` vs `stacked` vs `accurate` | LoCoMo showed stacked summary+raw can help; do not assume chunk-summaries-alone |
| Background / autocomplete / cheap reads | `cheap` / `cheap_plus` (`doc_summary_facts@3/5`) | cheap rungs, lede summary+facts packing |
| Debug / legacy compatibility | `raw` (`classic_chunks@25`) | escape hatch only, never default |

Reinforce: **one corpus type per namespace** — best packing is corpus-dependent,
so mixing corpora in a namespace destabilizes retrieval quality.

## lede alignment (already true in stele's direction)

The profile rungs use lede-enhanced summary/facts packing (keep facts + TOC/
headings) rather than ad-hoc prompt stuffing — the same `readable_report`
direction stele adopted for `digest_search`. No conflict; the two efforts agree.

## Relationship to in-flight stele work

- `digest_search` (sibling specs) is on stele's OWN retrieval + lede; it does not
  touch pg-raggraph. Independent of this migration.
- chunkshop 0.5.0 integration (slice 2): if/when used, verify pg-raggraph PR #40
  fix is present before relying on the benchmark path.
- pg-raggraph remains under active upstream development; this plan executes on
  release, not before.
