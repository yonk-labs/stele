# Audit — pg-raggraph retrieval-profile migration (stele)

Date: 2026-05-24
Updated: 2026-05-26 — **verdict revised against the released API.** The profile
API landed in `pg-raggraph==0.4.0a1`, but reading the real source invalidated
this audit's original migration premise. The correction is below; the original
staged plan (kept further down for history) should NOT be executed as written.
Scope: audit stele's pg-raggraph usage against the new `retrieval_profile`
ladder; decide what to change now vs. stage; document per-namespace defaults.

## Verdict (revised 2026-05-26)

**Still no mechanical migration — but for a new reason.** The `profile=` API now
exists (`GraphRAG.query(..., profile: str | int | float | None)` in 0.4.0a1),
so the "API absent" blocker is gone. However, the released semantics are not
what this audit assumed:

- **`profile` shapes `result.context` only.** All ladder rungs use the same
  `top_k=25`; they differ solely in `context_strategy` — how the retrieved set
  is *packed into the LLM-facing `result.context` string* (`cheap`=
  `doc_summary_facts@3`, `balanced`=`doc_and_chunk_summary_toc_facts_plus_top5`,
  `accurate`=`full_selected_docs@10`, `stacked`=`per_doc5_chunksum_top5`,
  `raw`=`classic_chunks`). Verified in `pg_raggraph/profiles.py` +
  `__init__.py::query` (profile feeds `pack_query_context`, sets
  `result.context`).
- **`profile` is orthogonal to `mode`/`rerank`**, not a replacement. `mode`
  still selects the retrieval substrate (smart/naive/local/global/hybrid/
  summary); `rerank` still independent.
- **stele's revisor consumes `res.chunks`, never `res.context`** (see
  `pg_raggraph_revisor.py::_to_hit` over `res.chunks`). So threading `profile=`
  through as the original plan proposed would have **no effect on stele's
  output** — it would only change a `.context` field stele discards.

**Conclusion:** adopting `profile` is meaningful for stele ONLY if stele starts
consuming pg-raggraph's packed context/summary instead of building its own from
`res.chunks`. That is exactly the `digest_search` build-vs-buy decision, which
the grounding benchmark is meant to settle. Do not wire `profile` blindly.

### What IS decision-independent and worth doing (still needs the benchmark for tuning)

- **`retrieval_strategy="vector_first"`** — unlike `profile`, this changes the
  *chunk substrate* stele actually consumes (60–66× faster on broad/no-predicate
  queries on single-namespace corpora; recall caveat on selective predicates,
  with a `pgrg.vector_first.recall_shortfall` metric). stele's graph namespaces
  are single-corpus and queries are broad-recall → good fit. This is the
  correctly-targeted analog of this audit's original intent.
- **Graph-hydration latency fix + index/namespace-profile migrations** —
  inherited automatically on the pin bump; no stele code. Action: ensure the
  deploy path runs pg-raggraph's migrations.

Both still want the grounding benchmark to confirm before flipping a default.

## Evidence

- Pin at audit time: `pg-raggraph==0.3.0a3`. **Bumped 2026-05-26 to
  `==0.4.0a1`** in `pyproject.toml` extra `postgres-graph` (not yet on PyPI; the
  local repo is the release candidate).
- `GraphRAG.query` signature at original audit time (0.3.0a3):
  `query(question, mode, namespace, as_of, version_filter, evolution_aware,
  rerank)` — no `profile`.
- `GraphRAG.query` signature in 0.4.0a1 (verified in source): adds keyword-only
  `retracted_behavior`, `supersession_behavior`, `memory_tier`,
  `retrieval_strategy`, `summary_base_mode`, `profile`, `metadata_filters`,
  `trace_emit`. `profile: str | int | float | None = None` →
  `config.retrieval_profile` (default `"balanced"`). New `mode="summary"`
  returns a deterministic no-LLM lede hint-biased summary in `result.summary`.
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

## Staged migration plan — HISTORICAL, DO NOT EXECUTE AS WRITTEN

> ⚠️ Superseded 2026-05-26. This plan assumed `profile` improves the chunk
> results stele consumes. It does not — see the revised Verdict above (`profile`
> only shapes `result.context`, which stele discards). Kept for history. The
> correct decision-independent change is `retrieval_strategy="vector_first"`,
> not `profile=`. Adopting `profile`/`mode="summary"` is part of the
> `digest_search` build-vs-buy decision, gated on the grounding benchmark.

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
