# Session-memory metadata & filtered retrieval — design note

Status: design proposal (2026-05-29). Motivated by the consolidation-chunker
benchmark, which proved two things the hard way:

1. **Chunking separates context from content.** A date anchor that lives in the
   surrounding text gets split from the fact it anchors, so retrieval can't
   reunite them. (Injecting `[Session date: …]` headers helped only `raw_fetch`,
   which keeps everything together; every distilled/retrieved lane was flat —
   see `benchmarks/consolidation-chunker-deep-2026-05-28.md`, Addendum 2.)
2. **Embeddings cannot rank dates or numbers.** "7 May" and "12 May" embed
   almost identically, so semantic search can find "a date-bearing sentence"
   but never the *right* date. Temporal questions are unanswerable by vector
   similarity alone.

The product consequence: for agent **session memory**, time/identity context
must be a **structured, filterable field per chunk** — not text we hope to
retrieve semantically. "Last week I was working on something, what was it?" is a
*date-range filter* + *topic rank*, and the filter half is impossible without
the field.

## What stele already has

- `ArtifactRecord` stores `metadata: dict`, `session_id`, `namespace`,
  `created_at`, `updated_at`, `expires_at`, `lifecycle`.
- `SearchHit` carries `metadata` (chunk-level keys now propagate from the chunk
  store: `kind`, plus consolidation's `subject/predicate/object/support_span`).
- `query(namespace, query, *, limit, mode, session_id, filters, raw)` is the
  **corpus-level** retrieval primitive (search across artifacts, unlike
  `search()` which scopes to one reference).
- The memory facade has `as_of` time-travel.

## The gap

`query(..., filters=...)` threads a `filters` dict to every retrieval backend,
but **only `session_id` is honored today** — every other key is dropped
(`del filters` / `filters.get("session_id")` only). So the pipe exists; nothing
flows through it but session_id.

## Proposal

### 1. Populate session metadata at `store()` time

Tiered for coding-agent sessions. Store as `metadata` keys (+ the existing
first-class `created_at` / `session_id`):

**Essential**
- `created_at` (already first-class) — powers "last week", recency, `as_of`.
- `session_id` (already first-class).
- `cwd` / `project_root` — "what was I doing in ~/proj/stele".
- `git_repo`, `git_branch` — highest-signal field for coding work.

**Valuable**
- `user`, `tool`/`source` (shell | editor | web | test-run), `files` (paths touched).

**Situational**
- `git_commit`, `exit_status` / `error` flag, `agent`/`model`, `token_cost`.

### 2. Extend `filters` semantics (the focused code change)

Honor these keys in every backend's filter handling (currently only
`session_id`):

| filter key | operator | example |
|---|---|---|
| `session_id` | eq (exists today) | `"sess-abc"` |
| `created_after` / `created_before` | range on `created_at` | last-week window |
| `namespace` | eq | already scoped by arg |
| `metadata.<key>` | eq | `{"metadata.git_branch": "auth-refactor"}` |
| `metadata.<key>__in` | membership | `{"metadata.tool__in": ["shell","test"]}` |

Backend support is natural: postgres/sqlite/mariadb/clickhouse all do
`WHERE created_at BETWEEN … AND json_extract(metadata,…) = …`; the memory
backend filters in Python. No new public-surface shape — `query()` keeps its
signature; only the `filters` contract widens.

### 3. Retrieval order: **filter-then-rank**

```
query("sessions", "the thing I was building", filters={
    "created_after": last_monday, "created_before": last_sunday,
    "metadata.git_repo": "stele",
})
# 1. WHERE created_at ∈ window AND metadata.git_repo='stele'   (exact, cheap)
# 2. rank survivors by vector/hybrid on the query text          (semantic)
```

Step 1 is the part embeddings provably cannot do; step 2 is where semantic
search earns its keep. The two compose — this is the architecturally correct
version of the benchmark's `anchor` hack (date as a column you `WHERE` on,
instead of a string jammed into the embedded text).

## Two rules so it doesn't backfire

1. **Do not embed metadata into the vector.** Embed *content*; keep metadata as
   columns/dict. Mixing date/identity strings into the embedded text dilutes the
   topic signal (the benchmark's structured-vs-raw packing was a wash for
   exactly this reason). Filter on the field; embed the meaning.
2. **Metadata is a new PII / secrets surface.** stele scrubs *content* by
   default, but `cwd`, file paths, usernames, and branch names can leak project
   and identity info. If session memory crosses trust boundaries, metadata needs
   the same scrub/gate path as content — at minimum a configurable allowlist of
   metadata keys exposed on model-visible `SearchHit.metadata`.

## Scope estimate

Small and contained:
- `store()` / interception: accept + persist a metadata dict (mostly wiring;
  `metadata` column already exists).
- Each `retrieval/*.py` backend: replace the `session_id`-only filter with a
  shared filter-builder (date range + metadata eq/in). One contract test
  parametrised across backends (mirror `test_vector_contract.py`).
- No change to `query()`'s signature or the `Stele` public contract.

This is the highest-leverage next step for session memory specifically: the
consolidation benchmark showed more retrieval/consolidator tuning yields
diminishing returns, while the one thing nothing in the stack can currently do —
"filter my history by when/where/which-repo, then rank by topic" — is a small,
well-bounded addition with an empirical justification.

## Routing layer: `parse_temporal` (implemented 2026-05-29)

The opt-in front door that turns a natural-language temporal request into the
filter above. Shipped as `src/stele/retrieval/temporal.py` — a pure,
deterministic, **LLM-free** parser (regex grammar + stdlib date math), so it
adds microseconds, not a round-trip.

```python
from stele.retrieval.temporal import parse_temporal
cleaned, tf = parse_temporal("what was I building last week", now)
if tf is not None:                       # temporal intent detected
    hits = stele.query(ns, cleaned, filters=tf.as_filters())  # filter-then-rank
else:
    hits = stele.query(ns, query)        # passthrough, zero behaviour change
```

- **Detect + resolve** relative to a caller-supplied `now` (required —
  relative dates are explicit and replay-safe, never wall-clock-dependent).
  Grammar covers: last/past N units, N units ago, last/this week|month|year,
  last/this/bare weekday, yesterday/today, since …, recently/lately.
- **Strip the temporal phrase before embedding.** "what was I building last
  week" → embed "what was I building", filter on the week. The date words are
  noise for the vector (the date-can't-embed weakness, now on the query side),
  so removing them sharpens the semantic match — a second win beyond the filter.
- **Returns `(query, None)` for non-temporal queries** — no overhead, no
  behaviour change.
- 18-case unit table in `tests/unit/retrieval/test_temporal.py` (fixed
  reference clock, fully deterministic, no API).

**Still opt-in and pending the `filters` extension.** `parse_temporal` produces
`created_after`/`created_before`, but backends honor only `session_id` today
(see the gap above). The clean wiring order: (1) widen `filters`, (2) gate
routing behind `retrieval.temporal_routing`, (3) empty-filtered-result → retry
unfiltered + flag, so a bad parse can't silently hide the answer.

## Implemented + demonstrated (2026-05-29)

The filter half is now real on the memory backend, end-to-end through
`stash.query()`, with a measured benefit.

- `src/stele/retrieval/_filters.py` — `record_matches_filters(record, filters)`:
  the reference semantics for `session_id`, `created_after`/`created_before`
  (tz-normalised), and `metadata.<key>` eq / `__in` / `__gte` / `__lte`.
- `src/stele/retrieval/memory.py` — `query_namespace` applies the predicate and
  now surfaces the artifact's `metadata` on each `SearchHit` (was namespace-only).
- `TemporalFilter.as_metadata_filters(field)` — map the parsed window onto a
  metadata date field (ISO strings, lexicographic, no tz pain).

**Why not LoCoMo:** confirmed empirically — only 58/1540 LoCoMo questions trigger
`parse_temporal`, and those are speaker-relative ("painted recently"), not
asker-relative recency windows. Temporal routing targets session-memory recall,
a query shape LoCoMo does not contain. Measuring it there would be theater.

**The right instrument** (`benchmarks/external/session_memory_demo.py`): 10 dated
work-sessions with vocabulary-overlapping in-window/out-of-window pairs, 4
recency queries ("what auth bug did I fix last week"). Through the real facade:

| path | metric |
|---|---|
| baseline `query(ns, raw_query)` (rank-alone) | **0/4** correct |
| routed `query(ns, cleaned, filters=window)` (filter-then-rank) | **4/4** correct |

Rank-alone picks the vocabulary-matching *distractor* every time because the
recency phrase can't be ranked; the date filter restricts to the window and the
right session wins. This is the benefit, isolated and measured.

**Remaining for production parity** (not blocking the demo): wire the same
predicate into the sqlite/postgres/mariadb/clickhouse retrieval backends and the
vector/chunk-store path (so `mode='vector'|'hybrid'` honors filters too), gate
auto-routing behind `retrieval.temporal_routing`, and add the empty-result
fallback. The memory backend proves the mechanism and the win.
