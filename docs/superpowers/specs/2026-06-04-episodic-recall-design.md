# Episodic Recall: Design

Status: **proposed** (not implemented). Tracking: yonk-labs/stele#48. Tracks the episodic-memory gap surfaced
by mapping stele to the classical semantic/episodic/procedural taxonomy (see
[docs/memory-types.md](../../memory-types.md#relation-to-the-classical-taxonomy-semantic--episodic--procedural)).

## TL;DR

stele distills semantic + procedural knowledge out of episodes, but "what
happened when" is only served by raw session search. This adds a first-class
**episodic recall** path: retrieve *an episode* (the event, in time order, with
its evidence). Phase 1 is an `episodic` recall strategy that composes primitives
that already exist (`parse_temporal`, temporal SQL, the `source_refs` back-link,
the recall registry). Episode = one session now; cross-session **spans** come
later. Temporal is a **soft boost by default, hard filter opt-in** (the prior
benchmark showed hard filters can hurt recall).

## Problem

Episodic memory (events, "what happened when") is the one classical category
stele under-serves. The evidence layer (stored session artifacts) *is* the
episodic substrate, but there is no API to ask "reconstruct the auth-refactor
session", "what was I building last week", or "when did we switch to keep120"
and get the episode back with its memories. Today that needs manual artifact
search with no temporal awareness and no link to the distilled memories.

## What an episode is

- **Phase 1: episode = one session.** A stored session artifact (from the
  conversation feed / `stele-ingest`) carries `created_at`, `session_id`,
  `session_mtime`, namespace, and the reduced text. Memories cite their session
  via `source_refs`. So an episode is **a session artifact + the memories
  back-linked to it**. Zero new modeling.
- **Later: spans.** A topic/task arc that crosses sessions (the whole auth
  refactor). Deferred; the data model leaves room for it (an optional
  `span_id` grouping in metadata) so spans can be added without a migration.

## What already exists (reuse, do not reinvent)

| primitive | where | role in episodic recall |
|---|---|---|
| `parse_temporal(query, now)` | `stele.retrieval.temporal` (built 2026-05-29) | turn "last Tuesday" into a time window |
| temporal SQL (`_temporal_sql`) | `storage/memory_store/{sqlite,postgres}.py` | window filtering at the store |
| `source_refs` back-link | `MemoryRecord.source_refs` | an episode's memories, given its artifact ref |
| recall strategy registry | `recall/facade.py`, `recall/adaptive.py` | where `episodic` slots in |
| artifact + chunk search | `search` / `artifact_search` strategy | semantic ranking of episodes |
| session artifacts | the `stele-ingest` feed | the episodes themselves |

Design context and the anti-backfire rules are in
[docs/session-memory-metadata-design.md](../../session-memory-metadata-design.md).

## Design (Phase 1: the `episodic` recall strategy)

A new `EpisodicStrategy` in `src/stele/recall/episodic.py`, registered as
`"episodic"` in the facade and adaptive registries.

**Inputs:** `recall(query, scope, strategy="episodic", limit=K)`, plus optional
`hard_temporal: bool = False` (and `since`/`until` overrides on the request).

**Algorithm:**
1. `cleaned, window = parse_temporal(query, now)` -> strip the time phrase, get a
   window (or None).
2. **Candidates:** session-ingest artifacts in `scope` (filter on
   `metadata.source == "session-ingest"` where present, else all artifacts).
3. **Rank semantically** on `cleaned` over the episode text (chunk/artifact
   search), producing a base score per episode.
4. **Temporal:**
   - default (soft boost): multiply/add a recency-or-proximity boost from the
     window; never exclude.
   - `hard_temporal=True`: restrict candidates to `created_at`/`session_mtime`
     inside the window before ranking.
5. **Attach evidence:** for each top-K episode, fetch its back-linked memories
   (`memory` whose `source_refs` contains the episode ref) via a new
   `memory.by_source_ref(ref)` query.
6. **Assemble:** return episodes newest-relevant first, each as an
   `EpisodeHit { session_id, when, summary, memories[], ref, score }`, plus the
   standard recall context block so it drops into the existing `RecallResult`
   contract.

**New surface (small):**
- `recall/episodic.py` (the strategy).
- `memory.by_source_ref(ref) -> list[MemoryRecord]` (the back-link query) +
  store implementations.
- `EpisodeHit` model (or reuse `SearchHit` + a memories field).
- Optional `hard_temporal` on `RecallRequest` (it already carries optional
  fields; see `test_recall_request_optional_fields.py`).
- Register `episodic` in both registries; an `Stele.recall.episodic(...)` shim.

## Out of scope (later phases)

- **Phase 2:** distilled **episode summaries** (one per session, kind=`summary`
  + `metadata.episode=true`) so "what happened in X" answers without re-reading;
  surfaced as `Stele.distill.episodes(...)`.
- **Phase 3:** a `timeline(scope, since, until, query)` ordered view, and
  episode-to-episode **span** linking via the graph (workgraph / pg-raggraph).

## Cautions (carried from the prior temporal work)

- **Filters can hurt.** The LoCoMo entity-filter result showed hard filtering
  drops relevant results when the parse is wrong. Hence soft-boost default.
- **The two anti-backfire rules** from the metadata design doc apply: never let a
  temporal filter empty the result set silently; fall back to unfiltered rank
  when the window yields too few candidates.
- **Recall is LLM-free / oracle-free** (the recall invariant). Episodic recall
  stays deterministic; `parse_temporal` is rule-based, not an LLM call.

## Testing

- Unit: `parse_temporal` integration (window extraction), soft-boost vs
  hard-filter ranking, `by_source_ref` back-link, empty-window fallback.
- Contract: `episodic` strategy across BACKENDS (memory + sqlite + postgres),
  parametrized like the other recall strategies.
- A small fixture corpus of dated session artifacts + back-linked memories;
  assert "last week" returns the right episode with its memories, and that a
  wrong/empty window falls back rather than returning nothing.

## Rollout

Phase 1 is additive and opt-in (`strategy="episodic"`); it changes no existing
strategy. Ship it, validate demand, then decide on Phase 2/3.
