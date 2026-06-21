# Temporal Recall — Design Notes (pre-spec)

Status: DESIGN NOTES (cross-model consensus captured; not yet a full spec/plan)
Date: 2026-06-21
Builds on: consolidation supersession chains (0.6.3), tags + fact-evolution view
(`docs/specs/memory-tags-design.md`), hybrid keyword+vector recall.
Incorporates: issue #69 (the entity-resolution gap, measured 60% cross-session
stale) and external validation vs MAGMA (arXiv 2601.03236, Jan 2026).

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

### Refinement (user): two valid stele profiles, kept ISOLATED

A MAGMA-like / temporal-rewrite stele is ONE type of stele: the curated
current-state plane that consolidates, supersedes, and rewrites toward "what is
true now." The keep-it-all stele is an equally valid SECOND type: immutable,
append-only, exact-bytes, full history, nothing rewritten. Both are legitimate;
the discipline is to keep them ISOLATED.

This sharpens the horizon axis. Long-term is not merely "the same store queried
with `as_of`." It is the isolated keep-all plane (immutable artifacts + the
complete superseded chains + evidence refs) that the temporal-rewrite plane
DERIVES FROM and CITES, but never mutates. stele already enforces the seed of
this: the Evolution Boundary (artifacts immutable, memory evolves). The user's
point extends that boundary across the horizon axis.

Isolation rules:
- The temporal-rewrite plane (active, consolidated, recency-weighted) may rewrite
  ITS OWN state via supersession. It must never mutate or prune the keep-all plane.
- The keep-all plane is ground truth and evidence: every current/rewritten state
  cites back into it (`source_refs`, superseded links, `as_of` recoverability).
- "Isolated" can mean separate stores, separate namespaces, or a strict
  read-only / derive-only boundary. Open for the spec. The invariant is one-way
  flow (keep-all -> temporal-rewrite), never the reverse.

Consequence for the "ONE store" framing above: shape and freshness stay knobs over
one store; horizon is the axis that may NOT fully collapse to params, because the
keep-all plane is worth isolating. "Do NOT build three subsystems" still holds for
shape + freshness; horizon is the deliberate exception.

## Entity resolution: issue #69 (the load-bearing gap)

The consensus already names slot resolution as THE risk. Issue #69 is its
concrete, measured form: cross-session evolving-fact consolidation fails when the
LLM emits a different `subject_label` for the same real-world entity. Measured
downstream (bento/dx-poc, real 26B LLM, 10 evolving-fact scenarios, two sessions
each): 6/10 cross-session facts left a stale, contradictory state active (60%);
same-session 0/10. `canonical_subject` is pure string normalization (NFKC +
casefold + alpha/digit split), no semantic/alias resolution, so "postgres" and
"production" land in different slots and no supersession fires.

This is the gating risk for `state` mode: a slot you cannot re-resolve has an
empty chain. It is the same problem MAGMA names the "object permanence problem
across disjoint timeline segments" (see below), and MAGMA does not cleanly solve
it either.

Resolution (debate-adjudicated, gemma + qwen + codex extra round): feeding active
subjects into the extract prompt is NOT sufficient alone. It only reduces LLM label
variance; "postgres" and "production" still resolve to different keys, so the 60%
failure survives. The authoritative fix is a deterministic, SCOPED, system-side
Subject Registry, resolved BEFORE commit:
- The LLM proposes a raw `subject_label`; the SYSTEM resolves
  `(scope, subject_type, normalized_label) -> subject_id` via a scoped lookup plus
  an explicit alias table. The LLM never decides identity.
- Supersession keys on `(scope, subject_type, subject_id, aspect)`, NOT the raw
  string and NOT a bare `(subject, aspect)`. Adding scope + type is the change.
- Resolve ONCE at commit and store the `subject_id`; historical recall uses the
  stored id (do not re-resolve committed memories on read).
- Keep the registry MINIMAL: a deterministic `(scope, label) -> id` map + explicit
  alias entries + a disambiguation policy. Not a stateful entity-management
  subsystem (that was the YAGNI objection; the minimal map answers it).
- The old "reuse active subjects in the extract prompt" stays as a complementary
  variance-reducer, not the mechanism.

The INVERSE danger is the debate's biggest catch: over-merging is WORSE than
missing a merge. A deterministic WRONG merge silently RETRACTS valid memory (e.g.,
"postgres" the service vs "postgres" the prod cluster vs "production" the
environment collapsing to one id, then one's update supersedes the others = data
loss). Rules:
- Normalization / suffix-stripping (-db/-prod) only PROPOSES candidates; binding
  requires an explicit alias entry or system policy. NEVER auto-merge on a fuzzy
  or suffix match.
- On an ambiguous match, REFUSE the commit (`subject_disambiguation_required`) or
  mint a new id per policy. Never LLM-guess, never silently merge.
- Scope is a required, non-aliased field; the same label in different scopes is
  different ids by construction.

Trap (still holds, learned downstream dx-poc #892): do NOT reconcile by cosine
over full fact text. It over-retracted ("user in London" vs "Paris" hard-deleted
at >=0.82 = silent data loss) AND under-retracted ("Postgres" vs "MySQL" <0.82,
both kept). Any similarity step stays hard-gated, same-aspect-scoped,
non-destructive (supersede, never delete). First-class searchable slots (the
consensus) ARE the registry index.

## External validation: MAGMA (arXiv 2601.03236, Jan 2026)

"MAGMA: A Multi-Graph based Agentic Memory Architecture for AI Agents" (Jiang, Li,
Li, Li). Independent SOTA work that arrives at this design's core thesis: do not
entangle temporal, causal, and entity information in a monolithic semantic store;
decouple into orthogonal views and retrieve by intent. Source: abstract + HTML
full-text fetch (not a full read); numbers are directional.

What MAGMA does: four orthogonal graphs (semantic, temporal, causal, entity) plus
rule-based "policy-guided traversal" that classifies query intent into {Why, When,
Entity} and weights graph edges per intent. Graphs built by LLM (fast path
segment/encode; slow path LLM reasons over neighborhoods to infer links). Reported
LoCoMo 0.700 judge / LongMemEval 61.2% avg, ~1.5s/query. Did NOT compare vs
Mem0/Zep.

Mapping to this design:
- Temporal graph -> our supersession chains. We are AHEAD: per the paper MAGMA's
  temporal graph only event-orders ("discrete events rather than explicitly
  modeling fact supersession or versioning"); our chains + `effective_until` +
  fact-evolution view model supersession explicitly.
- Entity graph -> our `canonical_subject` slots. This is the gap (#69). MAGMA
  frames it as the "object permanence problem" but its own fix is LLM slow-path
  inference with NO alias dedup described. Nobody has a free lunch; #69 fix 1
  (source-side reuse) is a lighter, deterministic answer.
- Semantic graph -> hybrid keyword+vector recall + `knowledge` mode (plus
  pg-raggraph when on). Covered.
- Causal graph ("Why") -> we have no equivalent. `knowledge` mode is a semantic
  neighborhood, not causal edges. The one genuine capability gap; YAGNI for now
  (building it the MAGMA way needs an LLM in the retrieval path, which violates the
  LLM-free recall invariant).

This also frames the user's "two profiles" point: MAGMA-like temporal-rewrite is
ONE stele profile (the curated current-state plane); the keep-it-all immutable
archive is the other valid, isolated profile (see the horizon refinement above).

Deliberate divergences (keep, on purpose):
- Intent: MAGMA classifies query intent; we REQUIRE caller-specified
  `temporal_mode` (LLM-free, deterministic). Determinism over auto-classification.
- Architecture: MAGMA is a 4-graph + LLM-slow-path engine. We get the high-value
  pieces (temporal + entity) from the slot mechanism we already have + #69's
  source-side fix, no causal graph, no LLM traversal. MAGMA validates the
  direction; we keep our machinery and invariants.

Benchmark caution: MAGMA's 0.70 / 61.2% are NOT apples-to-apples with our numbers
(different harness; and per PR #68 LongMemEval cannot even measure our
consolidation). Do not adopt MAGMA's score as a target without a same-harness
re-run.

## Debate outcomes (extra round: gemma + qwen + codex)

Two abe debates ran on this design. Round 1 (gemma + qwen, 3 internal rounds) and
an extra round (full roster; claude timed out at 180s, so effectively
gemma + qwen + codex). Strong convergence. Headline: build the Subject Registry
FIRST (see "Entity resolution"), because the shipped 60% failure is identity drift
before commit, and every later mechanism faithfully preserves a wrong chain.

Per-claim verdicts and the refinements they add:

- HORIZON (sound, with an integrity gate). The materialized current-state plane is
  fine ONLY if it has no independent write API and is rebuildable from immutable
  artifacts. Add: (a) each projected row carries derivation provenance
  (`source_memory_id`, `supersession_head_id`, derivation + registry version,
  validated evidence refs) so any read is re-verifiable against raw artifacts;
  (b) the derived plane is the DEFAULT recall path, raw superseded-chain reads
  require explicit `as_of` / `audit` / `debug` (this is how isolation is ENFORCED,
  not merely promised); (c) derive at commit-time inside the supersession
  transaction, single-writer per chain, not lazily at query time (kills the
  projection-staleness "heisenbug").

- INTENT (split RESOLVED: refuse LLM auto-classification). Caller-specified
  `temporal_mode` is correct; determinism wins. Composite queries are handled by
  deterministic ergonomics, NOT classification: keep `temporal_mode` required at
  the low-level API, add typed presets (`recall_state` / `recall_knowledge` /
  `recall_explain` = both / `audit_history`), and let public/free-text recall
  default to `both` via deterministic FAN-OUT (query both planes, TAG results by
  plane, stable ordering, per-plane budgets). Tagging by plane preserves `as_of`
  recoverability (do not blur state artifacts with knowledge artifacts).

- CAUSAL (sound to defer the graph; strengthen the metadata). No causal graph
  (YAGNI, needs an LLM in retrieval). But make supersession metadata STRUCTURED and
  EVIDENCE-BACKED: `supersedes_id` + a `supersession_kind` enum
  (`correction | update | invalidation | refinement | replacement`) + a
  `trigger_ref` / `reason_ref` that is a `stele://` evidence ref. NO free-text
  "why" (that is "reason laundering": uncited prose that reads as authoritative).
  Evidence ref mandatory unless the transition is explicitly marked
  manual / unknown / low-confidence.

Meta: claude timed out all 3 rounds at the 180s abe default. Bump the timeout (or
set `fast: true`) in `debator/abe.yaml` before relying on claude as a debater.

## Recommended shape + build order (lazy)

```python
resolve_slots(query, scope, tags) -> slot_candidates
get_slot_chain(slot_id, limit=3, as_of=None) -> states
get_related_memories(query, scope, tags, slot_ids=None, limit=5, recency_weight=0.15) -> memories
recall_temporal(query, scope, tags, temporal_mode) -> {resolved_slots, states, related, warnings}
# refresh lives OUT of recall:
refresh_due_memories(policy); refresh_memory(memory_id)
```

1. Build the Subject Registry FIRST (scoped, deterministic, resolve-before-commit;
   see "Entity resolution"). Supersession keys on `(scope, subject_type,
   subject_id, aspect)`. THEN ship `state` mode: first-class slot resolution +
   `as_of` + `limit`. Without the registry, cross-session chains do not form and
   `state` resolves empty ~60% of the time (measured).
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
- Entity resolution (#69): fix 1 (extraction-time subject reuse) is v1. Are fix 2
  (hard-gated same-aspect alias resolver) and fix 3 (`subject_resolver` hook) in v1
  scope or deferred?
- Horizon isolation (user): is long-term keep-all a separate store/namespace, or a
  read-only derive boundary over one store? One-way flow (keep-all ->
  temporal-rewrite) is the invariant; the realization is open.
- Causal dimension (MAGMA's "Why" graph): out of scope (YAGNI, needs an LLM in the
  retrieval path). Revisit only if `knowledge` mode proves insufficient.
- Subject Registry shape: scoped deterministic `(scope, subject_type, label) -> id`
  map + explicit alias table. Is `subject_type` a closed vocab (like the aspect
  seed) or open? Disambiguation default on ambiguous match: refuse vs mint-new?
- Supersession-key migration: current chains key on `(subject, aspect)`; adding
  `scope` + `subject_type` + `subject_id` is a stored-metadata change. Migrate
  existing chains vs forward-only?
- Recall preset API: `recall_state` / `recall_knowledge` / `recall_explain` /
  `audit_history` wrappers over the required low-level `temporal_mode`. Is
  `both`-by-default on public/free-text recall correct?
- Supersession metadata: `supersession_kind` enum values, and whether `trigger_ref`
  is mandatory (vs allowed-missing only when explicitly marked manual/unknown).
