# Temporal Recall — Design Notes (pre-spec)

Status: DESIGN NOTES (cross-model consensus captured; not yet a full spec/plan)
Date: 2026-06-21
Builds on: consolidation supersession chains (0.6.3), tags + fact-evolution view
(`docs/specs/memory-tags-design.md`), hybrid keyword+vector recall.

These notes capture a gemma+qwen debate (abe) adjudicated + extended by a Codex
second opinion. Turn into a full spec → plan next session.

## Idea

Two-stage temporal retrieval over memory:
- **Stage 1 (resolve):** hybrid search + tag filter → which `(canonical_subject,
  aspect)` slot(s) the query is about.
- **Stage 2 (expand), by caller-specified `temporal_mode`:**
  - `state`: each matched slot's supersession chain (current + recent states with
    date ranges). "what postgres version?" → "v15 until 2026-06-14, now v18".
  - `knowledge`: semantic neighborhood of related memories (pitfalls/decisions about
    the subject); hybrid by default, graph-related too when the graph backend is on.
    "have we had issues with the postgres version, which?"
  - `both`: union.
- Intent is **caller-specified** (LLM-free, deterministic) — not auto-classified.

## Cross-model consensus (gemma + qwen + Codex)

- **Two-stage is right**, but the resolve/expand split is INTERNAL
  (`resolve_slots()` → `expand_slots()`); a single public `recall_temporal(...)` is
  fine — just avoid a god-function that knows every expansion trick.
- **Keep caller-specified `temporal_mode`.** No LLM classifier, no intent-guessing.
  Require the field (or a dumb, documented default). Determinism needs explicit intent.
- **Replace "last N"** with `limit` (default 3) + `as_of=None` + `include_all=False`.
  No temporal query language yet (YAGNI). `limit + as_of` covers the useful cases.
- **Do not flatten return types.** Use a flat result object (simpler than a typed
  envelope): `{query, resolved_slots, states, related, warnings}`. `state` fills
  `states`; `knowledge` fills `related`; `both` fills both. Type is obvious from the
  populated section.
- **Resolution gap is THE risk** (fuzzy "the db version" not mapping to slot
  `(postgres, version)` → empty state result). Two fixes:
  1. **Do NOT silently fall back** state→knowledge (it hides the miss). Return empty
     `states` + whatever `related` + `warnings: ["no_slot_resolved"]`.
  2. **Make slots first-class searchable records** — index slot id, canonical
     subject, aspect, aliases, tags, current value. Do not rediscover slots from
     memory text.

## New idea 1 — recency-weighting

Worth it; keep it boring. `state` needs none (chain is time-ordered). `knowledge` =
relevance first, recency a MILD tie-breaker, e.g. `score = 0.85*relevance +
0.15*recency`, using `last_confirmed` (not `created_at`). Never let "newer" beat
"actually relevant." Laziest: retrieve top ~30 by relevance, then mild rerank.

## New idea 2 — memory refresh / staleness (SEPARATE axis)

**Headline blind-spot (Codex):** two different temporal concepts are being blurred:
1. **Temporal STATE of the project** ("pg 15 until June 14, now 18") → supersession
   CHAINS (already built).
2. **Temporal FRESHNESS of a memory** ("is this stored fact still valid?") → TTL /
   refresh (new).
Keep them as **separate machinery**. If blurred, a refresh/verification event gets
mistaken for a state change (spurious supersede), and historically-correct old
memories get wrongly flagged stale.

Design rules for refresh:
- **Recall must NOT secretly refresh.** Recall returns stored data + staleness
  metadata (`stale`, `staleness_reason`, `refresh_recommended`). Refresh is a
  separate, out-of-band, policy-driven path (scheduled job / explicit call /
  background queue) — never blocking deterministic recall.
- **TTL by memory type, not "every N calls"** (arbitrary → weird behavior):
  preference = no refresh; project/dependency/config = 7-30 days; external
  facts/prices = daily; archived decisions = no refresh.
- **Refresh from SOURCES, not the base model's latent knowledge.** The model can
  extract/compare; it is not the authority. (Tempers the original "let the base
  model re-derive" idea.)
- Traps: non-determinism (same query differs if refresh fired), cost (refresh =
  accidental search/extraction spam), thrash (unstable facts supersede too often),
  scope confusion (don't refresh historical-state memories), silent mutation (make
  refresh explicit/audited).

## New idea 3 — short-term vs long-term (the horizon axis)

This is the **memory-tier** axis = open issues **#10** (two-tier
provisional/consolidated + episode framing) and **#11** (per-call `memory_tier`
kwarg). stele ALSO already has a short-term substrate: **WorkGraph** ("Runtime
working memory", Phase 6, a first-class record type distinct from memory/artifacts).

- **Long-term** = durable memory store: full supersession chains, all states,
  `as_of`, evidence refs. The complete archive ("prove it / whole history").
- **Short-term** = distilled, recency-weighted, ACTIVE-only working view ("what's
  current/relevant now"). Realize either as a preset/view over durable memory
  (active + distill + recency-weight + recent window — lazy, no new storage) or via
  the existing WorkGraph substrate.

**Unifying picture — three ORTHOGONAL access axes over ONE store** (compose as
params/presets; do NOT build three subsystems):
1. **shape** — `temporal_mode`: state (chain) vs knowledge (neighborhood). *What.*
2. **horizon** — `memory_tier`: short (distilled/recent/active) vs long (full/as_of).
   *How much.*
3. **freshness** — refresh/TTL: validated vs stale. *Is it still true.*

Caution (same don't-blur lesson): horizon ≠ freshness. A long-term memory can be
fresh; a short-term one can be stale. Keep them separate knobs.

Open decision (#10/#11): is short-term a VIEW over durable memory, the WorkGraph
substrate, or both (WorkGraph = session-hot; distilled-view = recency-weighted
durable)? Reconcile with WorkGraph; don't build a parallel short-term store.

## Recommended shape + build order (lazy)

```python
resolve_slots(query, scope, tags) -> slot_candidates
get_slot_chain(slot_id, limit=3, as_of=None) -> states
get_related_memories(query, scope, tags, slot_ids=None, limit=5, recency_weight=0.15) -> memories
recall_temporal(query, scope, tags, temporal_mode) -> {resolved_slots, states, related, warnings}
# refresh lives OUT of recall:
refresh_due_memories(policy); refresh_memory(memory_id)
```

1. Ship `state` mode first: first-class slot resolution + `as_of` + `limit`.
2. Add `knowledge` mode with the mild recency rerank.
3. Add refresh LATER as a separate maintenance feature (staleness metadata in recall
   now is cheap; the refresh loop is its own project) — and design it to refresh
   from sources, not the model.

## Open decisions for the spec

- Slot index: where do first-class slot records live (a slots table/view vs derived
  index over memory metadata)? Cross-backend implications.
- `state` vs `knowledge` vs `both`: required arg or defaulted?
- Result object: typed models (`StateItem`/`RelatedItem`) vs dicts.
- Staleness metadata: which fields, computed where (recall-time vs stored).
- Refresh policy config shape + the source-of-truth question (what "a source" is for
  an agent-memory fact).
