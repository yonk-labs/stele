# Memory Tags — Design

Status: DRAFT (brainstorming output, pending review)
Date: 2026-06-20
Scope: `stele` memory facade + distill timeline + fact-evolution view
Related: builds on the existing `metadata` field, the `distill.timeline` view (0.6.1),
and the 0.6.3 consolidation supersession chains (the fact-evolution view reads them).

## Problem

Memories need **multi-valued, queryable grouping** — a memory can belong to a
project AND a topic AND a session at once, and users want to "show everything
tagged X" and build timelines. Today stele has two grouping mechanisms, neither
of which fits:

- **`scope`** (`user_id`/`agent_id`/`app_id`/`session_id`/`namespace`) — fixed,
  single-valued hierarchy. A memory has exactly one session, one namespace. Can't
  express "this belongs to project bento AND topic auth AND sprint 12".
- **`metadata`** (arbitrary dict) — multi-valued-capable but unindexed and with no
  query/grouping API.

Tags fill the gap: free, multi-valued labels with a uniform write + filter +
timeline API.

## Decisions (from brainstorming)

- **Source:** both **explicit** (caller-supplied) AND **auto-derived** (stele adds
  structural tags so grouping/timeline work with zero effort).
- **Read:** a **filter** primitive, a **timeline** view, AND a **fact-evolution**
  view (current value + prior values with date ranges for an evolving fact), all
  built on the filter.
- **Storage:** **metadata convention** — tags live under a reserved
  `metadata["tags"]` key. No schema migration; works across all 5 backends now;
  reuses the proven metadata plumbing (the same path consolidation's cross-session
  lookup uses). The public API (`tags=[...]`, `list(tags=...)`) is stable, so a
  future first-class indexed column is an internal optimization, not a breaking
  change. Known cost: facade-side filtering is O(active memories) per query
  (acceptable at current scale; upgrade path = a Postgres GIN index on the default
  benchmark backend).

## Tag format

Structured `type:value` strings, plus flat freeform labels:

- `session:<session_id>`, `project:<namespace>`, `day:<YYYY-MM-DD>` — reserved
  **auto-tags** stele derives at write time.
- `topic:auth`, `sprint:12`, `urgent` — caller-supplied.

Normalization (deterministic, pure): trim, collapse internal whitespace, casefold,
drop empties, dedupe, sort. A tag is at most one `:` split into `type:value`; extra
colons stay in the value. Stored as a sorted `list[str]` so equality/containment is
stable.

## Components / files touched

- `src/stele/extraction/tags.py` (new, pure): `normalize_tags(list[str]) -> list[str]`,
  `auto_tags(scope, effective_from) -> list[str]` (derives `session:`/`project:`/`day:`),
  `merge_tags(explicit, auto) -> list[str]`. No I/O, no LLM.
- `src/stele/core/memory.py`:
  - `add(..., tags: list[str] | None = None)`: normalize + merge with `auto_tags`,
    store under `metadata["tags"]`. (Tags are NOT supersession-relevant — they are
    labels, not asserted facts; supersession/dedup logic is unchanged.)
  - `add_many`: same `tags` per `AddRequest`.
  - `list(scope, ..., tags: list[str] | None = None, match: Literal["any","all"] = "any")`:
    after the backend returns the scoped rows, filter to those whose
    `metadata["tags"]` intersect (`any`) or superset (`all`) the requested tags.
  - `retag(memory_id, add=[...], remove=[...])` (thin wrapper over the existing
    `update_metadata`): tags are mutable labels, so re-tagging is allowed and does
    NOT violate the memory-text-immutability invariant.
- `src/stele/core/memory_record.py`: add a read-only `tags` property returning
  `list(self.metadata.get("tags", []))` (convenience; no new stored column).
- `src/stele/extraction/extractor.py` `from_session`: pass the session's auto-tags
  through `_commit` (the per-memory metadata already flows here; add tags alongside
  `do_instead`/slot metadata). Preserves the #62 + consolidation metadata.
- `src/stele/distill/` timeline: extend the existing `distill.timeline` to accept
  `tags=[...]` + `match`, filtering its memory set by tag before time-ordering.
  Reuse the existing oldest-first ordering and windowing; do NOT rebuild it.
- `src/stele/distill/` evolution (new view): `distill.evolution(scope, *, tags=None,
  subject=None, aspect=None, match="any")` → for each `(canonical_subject, aspect)`
  slot in the tag-scoped set, return its supersession CHAIN oldest→newest with each
  state's value/summary + `effective_from` + `effective_until`. This is the
  "postgres v15 until 2026-06-14, now v18" answer. It reads memories with
  `status_filter=["active", "superseded"]` (the whole chain), groups by the
  `canonical_subject`/`aspect` metadata that **consolidation already writes**, and
  orders each slot by `effective_from`: the active link is "current"
  (`effective_until=None`), each superseded link carries its `effective_until` (the
  "until X"). Pure read over the facade; no new storage; LLM-free. **Depends on
  consolidation** (the chains + the slot metadata + `effective_until`); with
  `consolidation_enabled=False` there are no chains, so the view degrades to a flat
  per-subject list with no supersession history (documented, not a failure).
- MCP/CLI surfaces (`stele_memory_add` tags arg, `stele_memory_list --tag`,
  `stele distill evolution --tag --subject --aspect`,
  `stele distill timeline --tag`): in scope but as a thin follow-on slice; the
  facade is the primitive.

## Data flow

`extract.from_session(scope=session=s1, namespace=bento)` → each committed memory
gets `metadata["tags"] = ["day:2026-06-20", "project:bento", "session:s1"]` (auto),
merged with any explicit tags. Later: `memory.list(scope, tags=["project:bento"])`
returns all bento memories; `distill.timeline(scope, tags=["topic:auth"])` returns
the auth memories oldest-first.

**Evolving fact (the motivating case):** across sessions the LLM extracts "postgres
version = 15", then later "postgres version = 18" (both slot `postgres`/`version`).
Consolidation supersedes 15 with 18, stamping 15's `effective_until` = when 18
landed. Then `distill.evolution(scope, tags=["project:bento"], subject="postgres",
aspect="version")` returns `[{value: "15", from: T0, until: T1}, {value: "18",
from: T1, until: None}]` — i.e. "postgres was v15 until <T1>, now v18", scoped to
project bento. The current value is the active link; the "until" comes from the
superseded link's `effective_until`.

## Edge cases / invariants

- **Mutable labels, immutable facts:** tags live in metadata and may be edited via
  `retag`/`update_metadata`. The memory `text` immutability invariant is untouched
  (tags are not facts). Supersession is unaffected — a superseded memory keeps its
  tags; `list(status_filter=["active"])` + tag filter is the "current tagged" view.
- **PII:** auto-tags derive from `scope` identifiers (`session_id`, `namespace`),
  not from scrubbed content — no raw PII enters tags. Caller-supplied tags are the
  caller's responsibility (documented); they are NOT PII-scrubbed (they are labels).
- **Empty / malformed tags:** normalized away (empty after trim → dropped).
- **Scale:** facade-side tag filter scans the scoped active set; same O(N) profile
  as consolidation's cross-session lookup. Documented; upgrade path is a real index.
- **No tag explosion control in v1:** unbounded distinct tags allowed (YAGNI); add
  governance later if needed.

## Testing plan (TDD)

- **Unit:** `normalize_tags` (trim/casefold/dedupe/sort/empty), `auto_tags`
  (session/project/day derivation; missing session_id omits `session:`),
  `merge_tags`.
- **Contract (across backends):** `add(tags=[...])` then `list(tags=..., match=any/all)`
  returns the right set; auto-tags present; `retag` adds/removes.
- **Timeline:** `distill.timeline(tags=[...])` returns only tagged memories,
  oldest-first.
- **Evolution:** ingest an evolving fact (v15 → v18 in one `subject`/`aspect` slot),
  call `distill.evolution(subject=, aspect=)`, assert it returns both states
  oldest→newest with the superseded one's `effective_until` set and the active one's
  `effective_until=None`; tag-scoping restricts it to the right project. Also assert
  the `consolidation_enabled=False` degradation (flat list, no chain).
- **Regression:** `from_session` still threads `do_instead` + slot metadata AND now
  tags (no clobber); existing memory/extraction/distill suites stay green.

## Open questions

1. Reserved auto-tag set: `session`/`project`/`day` for v1; is `agent:`/`app:`
   wanted too? (Default: just the three; easy to add.)
2. `project:` maps to `scope.namespace` — confirm that's the right "project" notion
   (vs a separate field).
3. MCP/CLI exposure: ship in the same change or as an immediate follow-on slice?
4. Tag normalization: casefold by default — confirm (some users may want
   case-sensitive values like `sprint:Q3`). Default casefold; revisit if it bites.
5. `distill.evolution` return shape (a typed `EvolutionItem`/`StateItem` vs plain
   dicts) and whether `subject`/`aspect` are required (single-slot) or optional
   (all evolving slots in scope). Default: optional filters; return all slots that
   have a chain, plus single-slot when both are given.
6. Whether the evolution view should also surface the `source_refs` per state (so
   "v15 until last week" links to the evidence that said v15). Default: yes, include
   refs — it is stele's exact-evidence thesis and nearly free here.
