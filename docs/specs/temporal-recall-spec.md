# Temporal Recall: Specification

Status: SPEC (promoted from `temporal-recall-design-notes.md`; ready for
`writing-plans`)
Date: 2026-06-21
Source: design notes (cross-model consensus gemma + qwen + Codex, plus an extra
adjudication round gemma + qwen + codex). Builds on consolidation supersession
chains (0.6.3), `identity.py` / `consolidation.py`, the memory tags + fact-evolution
design (`memory-tags-design.md`), and hybrid keyword+vector recall.
Incorporates issue #69 and external validation vs MAGMA (arXiv 2601.03236).

## TL;DR

Two-stage temporal recall over evolving memory: resolve a query to a
`(subject, aspect)` slot, then expand it by a caller-specified `temporal_mode`
(`state` = the supersession chain with date ranges, `knowledge` = the semantic
neighborhood, `both` = a plane-tagged union). The load-bearing prerequisite is a
deterministic, scoped Subject Registry that resolves entity identity BEFORE commit,
so the same real-world entity gets one stable `subject_id` across sessions even
when the LLM labels it differently. Without it, cross-session state chains do not
form and `state` recall resolves empty about 60% of the time (measured). Recall
stays deterministic and LLM-free. Refresh/TTL freshness and the short/long horizon
tier are out of scope here (separate later features); this spec surfaces staleness
metadata only.

## Problem

Memory evolves: a fact about an entity gets a new value over time (postgres v15,
then v18). Consolidation (0.6.3) records this as a supersession chain keyed on a
`(canonical_subject, aspect)` slot, recoverable via `as_of`. Two gaps remain:

1. **Cross-session identity (issue #69, the load-bearing gap).** `canonical_subject`
   is pure string normalization (`identity.py`: NFKC + casefold + alpha/digit
   split + punctuation strip). It folds typographic variants (`test1` / `Test 1`)
   but has no alias/semantic resolution. When the LLM emits a different
   `subject_label` for the same entity across two independent sessions ("postgres"
   in one, "production" in another), the states land in different slots, no
   supersession fires, and both stay active as a stale, contradictory pair.
   Measured downstream (bento/dx-poc, real 26B LLM, 10 evolving-fact scenarios,
   two sessions each): 60% (6/10) cross-session stale; same-session 0/10. This is
   the dominant real-world case (facts evolve across sessions over days).

2. **No temporal recall surface.** There is no first-class way to ask "what is the
   current value and how did it evolve" (`state`) vs "what do we know about this
   subject" (`knowledge`). Callers reconstruct chains by hand from `memory.list`.

## Goals / Non-goals

Goals:
- A deterministic, scoped Subject Registry resolving `raw_label -> subject_id`
  before commit, so supersession keys on stable identity, not LLM strings.
- `state` recall: resolve a slot, return its chain (current + history with
  `effective_from` / `effective_until`), with `as_of` and `limit`. LLM-free.
- `knowledge` recall: semantic neighborhood of related memories, relevance-first
  with a mild recency tie-breaker.
- `both`: deterministic fan-out over the two planes, results tagged by plane.
- Caller-specified `temporal_mode` (no LLM auto-classification) plus deterministic
  ergonomic presets so callers do not hand-pick a mode for every query.
- Horizon isolation: a derived current-state plane that is rebuildable from the
  immutable keep-all plane, with one-way data flow and an integrity gate.
- Structured, evidence-backed supersession metadata (the cheap "why").

Non-goals (deliberate, see notes):
- No causal/"why" graph (YAGNI; would put an LLM in the retrieval path).
- No LLM in the retrieval path at all. Extraction may use an LLM; recall may not.
- No refresh/TTL freshness machinery here. Recall returns staleness metadata only;
  the refresh loop is a separate later feature, source-driven, never inside recall.
- No short/long memory-tier (#10/#11) build here. The horizon framing is captured;
  reconcile with WorkGraph before building it.
- No temporal query language. `limit` + `as_of` cover the useful cases.
- No embedding/cosine merge over fact text for identity (it over- and
  under-retracts; see Edge cases).

## The three orthogonal access axes (recap)

One store, three orthogonal knobs (full rationale in the design notes):
1. **shape** (`temporal_mode`): `state` (supersession chain) vs `knowledge`
   (semantic neighborhood). Caller-specified.
2. **horizon** (`memory_tier`): short (distilled/recent/active) vs long
   (full/as_of). Realized as two isolated profiles (below). Build later.
3. **freshness** (refresh/TTL): validated vs stale. Out of scope here.

shape and freshness are knobs over one store; horizon is the axis worth isolating.

## Subject Registry (the headline mechanism)

The LLM proposes a human label; the SYSTEM owns identity. Resolution happens once,
at commit time, and the resolved `subject_id` is stored on the memory.

Resolution function (deterministic, no LLM, no embeddings):

```
resolve_subject(scope, subject_type, raw_label) -> subject_id | DISAMBIGUATE
  norm = canonical_subject(raw_label)                  # existing identity.py
  key  = (scope_key(scope), subject_type, norm)
  if key in registry:            return registry[key].subject_id   # exact
  candidates = alias_lookup(scope, subject_type, norm)             # explicit map
  if len(candidates) == 1:       return candidates[0]
  if len(candidates) > 1:        return DISAMBIGUATE               # never guess
  return mint(scope, subject_type, norm)              # new id, append-only
```

Rules:
- **Key on `(scope, subject_type, normalized_label)`.** Scope is required and
  non-aliased. The same label in different scopes is different ids by construction
  (prevents "postgres the service" vs "postgres the prod cluster" collapsing).
- **Normalization PROPOSES, it never BINDS.** `canonical_subject` and any
  suffix-stripping only produce a normalized lookup key and candidate set. Two
  distinct normalized labels are bound to one `subject_id` only via an EXPLICIT
  alias entry or a system policy, never via a fuzzy match.
- **Ambiguous match refuses.** If a label maps to more than one existing subject
  within `(scope, subject_type)`, raise `SubjectDisambiguationError` (or mint a new
  id per a configured policy). Never silently merge.
- **Resolve once, store the id.** Historical recall uses the stored `subject_id`;
  do not re-resolve committed memories on read. Alias-map changes affect only
  future commits (reproducibility of the commit decision, not retroactive
  re-identification).
- **Append-only registry.** Minting and alias entries are append-only with their
  own `stele://` provenance where applicable. No in-place identity rewrite.
- **Minimal.** The registry is a deterministic `(scope, subject_type, label) -> id`
  map plus an explicit alias table plus the disambiguation policy. Not a stateful
  entity-management subsystem.

The extraction-time "reuse active subjects in the prompt" nudge stays as a
complementary variance-reducer (fewer disambiguation events), not the mechanism.

## `state` mode

Two internal stages behind one public call:
- `resolve_slots(query, scope, tags) -> slot_candidates`: hybrid search + tag
  filter + registry lookup to find the `(subject_id, aspect)` slot(s) the query is
  about. The materialized slot projection (see Data model) is the index; do not
  rediscover slots from memory text.
- `get_slot_chain(slot, limit=3, as_of=None) -> states`: the chain oldest to
  newest (or as-of a timestamp), each state carrying value/summary,
  `effective_from`, `effective_until` (None for the active head), and
  `source_refs`.

If no slot resolves: return empty `states` plus `warnings: ["no_slot_resolved"]`.
Do NOT silently fall back state -> knowledge (it hides the miss).

## `knowledge` mode

`get_related(query, scope, tags, slot_ids=None, limit=5, recency_weight=0.15)`:
hybrid (and graph-related when the graph backend is on) semantic neighborhood.
Relevance first, recency a mild tie-breaker on `last_confirmed`:
`score = 0.85*relevance + 0.15*recency`. Never let "newer" beat "actually
relevant." Lazy realization: retrieve top ~30 by relevance, then mild rerank.

## Intent: `both`, presets, and the no-classification rule

`temporal_mode` is caller-specified and REQUIRED at the low-level API. The system
NEVER infers intent with an LLM (determinism). Composite queries are served by
deterministic ergonomics, not classification:
- Low-level: `recall_temporal(query, scope, tags, temporal_mode)`.
- Presets (typed wrappers, developer chooses in code): `recall_state`,
  `recall_knowledge`, `recall_explain` (= both), `audit_history` (= as_of/full).
- Public/free-text agent recall defaults to `both`, executed as deterministic
  fan-out: query both planes, TAG each result section by plane, stable ordering,
  per-plane budgets. Tagging by plane preserves `as_of` recoverability and keeps
  state artifacts distinct from knowledge artifacts.

Flat result (type obvious from populated sections):
`{query, resolved_slots, states, related, warnings}`. `state` fills `states`;
`knowledge` fills `related`; `both` fills both.

## Horizon: two isolated profiles + integrity gate

Two profiles over the same durable store, one-way data flow only:
- **keep-all**: immutable, append-only, exact bytes, full superseded chains, all
  evidence. Ground truth.
- **temporal-rewrite (current-state plane)**: a materialized projection of keep-all
  giving "what is true now." DERIVES FROM and CITES keep-all; never mutates it.

Integrity gate (from the debate; these are requirements, not options):
- The projection has NO independent write API and is fully rebuildable from
  immutable artifacts.
- Each projected row carries derivation provenance: `source_memory_id`,
  `supersession_head_id`, derivation + registry version, and validated evidence
  refs, so any read is re-verifiable against raw artifacts.
- The derived plane is the DEFAULT recall path. Raw superseded-chain reads require
  explicit `as_of` / `audit` / `debug` intent and return visibly historical
  records. This is how isolation is enforced, not merely promised (prevents
  split-brain where an agent reads a raw chain and sees a resolved-away
  contradiction).
- Derive at commit time inside the supersession transaction, single-writer per
  `(scope, subject_type, subject_id, aspect)` chain, not lazily at query time
  (kills the projection-staleness race).

"Isolated" may be realized as separate stores, separate namespaces, or a strict
read-only/derive boundary over one store. Open for the plan; the invariant is the
one-way flow.

## Causal: structured supersession metadata (no graph)

No causal graph. Capture the cheap "why" as structured, evidence-backed metadata on
each supersession:
- `supersedes_id` (already present).
- `supersession_kind`: enum `correction | update | invalidation | refinement |
  replacement`.
- `trigger_ref` / `reason_ref`: a `stele://` evidence ref.

NO free-text "why" (reason laundering: uncited prose reads as authoritative). The
evidence ref is mandatory unless the transition is explicitly marked
manual / unknown / low-confidence.

## Public API surface

On `Stele.recall` (extends the existing facade alongside `memory_search`,
`graph_search`, `adaptive`, `episodic`):

```python
recall.temporal(query, *, scope, tags=None, temporal_mode, limit=3, as_of=None)
    -> TemporalResult   # {query, resolved_slots, states, related, warnings}
recall.state(query, *, scope, tags=None, limit=3, as_of=None)        # preset
recall.knowledge(query, *, scope, tags=None, limit=5)                # preset
recall.context(query, *, scope, tags=None)                           # = both (was 'explain')
recall.audit_history(*, scope, subject_type, subject_id, aspect)     # full chain, full key
```

Notes (debate-adjudicated):
- `query` is DETERMINISTIC (hybrid keyword/vector slot lookup + tag filter), never
  LLM-interpreted. It selects slots; it does not classify intent.
- `audit_history` takes the FULL key (`subject_type` is part of the supersession
  key) or a resolved `slot_id`. A bare `(subject_id, aspect)` is under-keyed.
- `context` replaces `explain`: "explain" wrongly implied causal "why" reasoning.
  It is the deterministic state + knowledge fan-out, plane-tagged.

Identity (extraction path, not recall): `resolve_subject(...)` is internal to the
extractor/commit path. Optional `subject_resolver` hook so a consumer can inject a
KB-specific map (no LLM dependency in stele).

## Data model / storage changes

- **Supersession key** gains identity: `(scope, subject_type, subject_id, aspect)`.
  Today `SlotKey` is `(canonical_subject, aspect)`. This is a stored-metadata
  change (additive backfill, see below).
- **Registry records**: `(scope, subject_type, normalized_label) -> subject_id`,
  plus an explicit alias table, append-only.
- **Memory metadata** gains: `subject_id`, `subject_type`, `supersession_kind`,
  `trigger_ref`. Consolidation already writes `canonical_subject`, `aspect`,
  `effective_until`.
- **Slot records / current-state projection** (first-class, searchable): a
  MATERIALIZED derived projection keyed by `(scope, subject_type, subject_id,
  aspect)` carrying canonical subject, aliases, tags, and the current-head value.
  Rebuildable from immutable memory, updated in the SAME transaction as the
  supersession commit, with no independent write API. It is an indexed read model,
  not a new source of truth, and NOT a lazy query-time view (a derived metadata
  view makes `state` resolution O(N) and race-prone against concurrent
  supersessions).

### Migration: additive backfill (decided)

Not forward-only (split-brain: old heads under `(canonical_subject, aspect)`, new
chains under the full key, breaking `as_of`) and not in-place rewrite (violates
artifact immutability). Instead a one-time ADDITIVE backfill:
- Build registry rows + the materialized slot/current-head projection FROM existing
  `(canonical_subject, aspect)` metadata, minting deterministic legacy
  `subject_id`s with legacy defaults for `scope` / `subject_type`.
- Existing memory rows are NEVER touched. New commits use the full key and
  supersede the backfilled legacy heads through the registry.
- Ambiguous legacy collisions become integrity WARNINGS for manual repair, never
  auto-merges. Bounded migration, not an indefinite dual-key mode.

## Components / files touched

- `src/stele/extraction/identity.py`: add the registry resolution (or a new
  `registry.py`); `canonical_subject` stays the normalizer that feeds it.
- `src/stele/extraction/consolidation.py`: `SlotKey` / `slot_for` resolve through
  the registry to `subject_id`; `plan_chains` keys on the new tuple.
- `src/stele/extraction/extractor.py` `from_session`: resolve subjects before
  commit; thread `subject_id` / `supersession_kind` / `trigger_ref` through
  `_commit` (alongside the existing `do_instead` + slot metadata + tags).
- `src/stele/recall/`: new temporal strategy + `recall.temporal/state/knowledge/
  explain/audit_history`; reuse hybrid search + the graph path; keep recall
  LLM-free (enforced by `tests/unit/recall/test_architecture.py`).
- `src/stele/core/config.py`: `RecallConfig` temporal defaults; registry
  disambiguation policy; (later) staleness metadata fields.
- `src/stele/core/memory_record.py`: read-only accessors for the new metadata.
- MCP/CLI: `recall.temporal` and presets as a thin follow-on slice.

## Data flow (worked example: #69 resolved)

Session day1 (LLM labels it "postgres"): extract "Postgres 14 in production"
(aspect `version`). `resolve_subject(scope, "service", "postgres") -> S1` (mint).
Memory stored with `subject_id=S1`.

Session day2 (LLM labels the SAME entity "production"): extract "Postgres 16 in
production" (aspect `version`). `resolve_subject(scope, "service", "production")`:
no exact key, but an explicit alias `production -> S1` (configured, or proposed and
confirmed by policy) resolves to `S1`. Slot `(scope, service, S1, version)` already
has a chain head (v14); the new state supersedes it, stamping v14's
`effective_until`. `recall.state("postgres version", scope=...)` returns
`[{value:"14", until:T1}, {value:"16", until:None}]`. One active head.

If no alias exists and "production" is genuinely ambiguous within
`(scope, service)`, resolution refuses (`SubjectDisambiguationError`) rather than
minting a colliding chain or silently merging.

## Edge cases / failure modes

- **Over-merge (worse than under-merge).** A deterministic WRONG merge silently
  retracts valid memory. Mitigations: scope+type keying, normalization proposes
  but never binds, ambiguous refuses, no cosine-over-fact-text.
- **Cosine trap (dx-poc #892).** Cosine over full fact text over-retracted ("user
  in London" vs "Paris" hard-deleted at >=0.82 = data loss) AND under-retracted
  ("Postgres" vs "MySQL" <0.82, both kept). Any similarity step stays hard-gated,
  same-aspect-scoped, non-destructive (supersede, never delete).
- **Projection bypass / split-brain.** Mitigated by the integrity gate (derived
  plane is default; raw reads gated).
- **Consolidation race.** Single-writer per chain + commit-time derivation.
- **Orphaned evidence refs.** Validate refs at projection time; surface broken refs
  rather than returning them silently.
- **Aspect drift.** Existing `overlap_warnings` (log-only, never auto-merges) is
  retained.
- **No slot resolved.** Empty `states` + `warnings`, no silent fallback.

## Testing plan (TDD)

- **Unit (registry):** `resolve_subject` exact / alias / mint / disambiguate;
  scope isolation (same label different scope -> different id); normalization
  proposes but does not bind; resolve-once (committed id stable across alias-map
  change).
- **Contract (the #69 repro, across backends):** two sessions, session 2 phrases
  the subject differently; with an alias the chain resolves to one active head and
  the prior is recoverable via `as_of`; without an alias, ambiguous resolution
  refuses (no silent merge). This is the issue's deterministic reproduction turned
  into a regression test.
- **No-over-merge regression:** genuinely distinct entities/aspects never merge
  (keep existing distinct-fact contract tests green).
- **Recall:** `state` returns the chain with date ranges; `knowledge` returns the
  neighborhood with the mild recency rerank; `both` returns plane-tagged sections;
  `no_slot_resolved` warning path.
- **Architecture:** recall imports no LLM client (existing
  `test_architecture.py`).

## Build phases (lazy)

1. **Subject Registry FIRST** (scoped, deterministic, resolve-before-commit;
   supersession keys on `(scope, subject_type, subject_id, aspect)`). This alone
   addresses the 60% failure.
2. **`state` mode + materialized current-state projection**: the slot/current-head
   projection and its integrity invariant ship WITH state (state cannot resolve
   deterministically without the projection; do not defer it). First-class slot
   resolution + `as_of` + `limit` over the resolved chains.
3. **`knowledge` mode** + the mild recency rerank; `both` fan-out + presets.
4. **Harden horizon isolation**: provenance metadata + gated raw-chain reads (raw
   access behind `as_of` / `audit` / `debug`). (Reconcile short/long tier with
   WorkGraph as a later feature.)
5. **Later, separate:** refresh/TTL freshness (staleness metadata in recall now is
   cheap; the refresh loop is its own project, source-driven).

## Cross-model validation

Two abe debates adjudicated this design. Round 1 (gemma + qwen, 3 internal rounds)
and an extra round (gemma + qwen + codex). Convergent conclusions, recorded in
`temporal-recall-design-notes.md` (Debate outcomes): the Subject Registry is the
build-first headline; over-merge is the dominant danger; refuse LLM
auto-classification and serve composite queries with deterministic presets; gate
the materialized plane; keep supersession metadata structured and evidence-backed.

## Open questions

- `subject_type` (refined, not fully closed): a small SEEDED vocabulary plus
  validated extension strings (like `SEEDED_ASPECTS`), not a hard global enum
  (premature) and not open/absent (unsafe over-merge within a scope). Open: is
  `subject_id` unique within `scope`, or within `(scope, subject_type)`? That
  decides whether `subject_type` is strictly key material or a resolution guard.
  Disambiguation default on ambiguous match: refuse vs mint-new.
- Supersession-key migration: DECIDED as additive backfill (see Data model). Open:
  the exact legacy `scope` / `subject_type` defaults and the collision-warning
  surface.
- Result types: typed models (`StateItem` / `RelatedItem`) vs dicts.
- `both`-by-default on public recall: confirm, and the per-plane budget defaults.
- Staleness metadata fields and where computed (recall-time vs stored), pending the
  separate refresh feature.
