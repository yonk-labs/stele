# Filtered retrieval & temporal routing

`query()` can narrow a namespace search by time and metadata **before** it ranks
by relevance — the filter-then-rank pattern. This is how you answer questions
that ranking alone can't: *"what was I working on last week"*, *"only the
auth-branch sessions"*, *"facts about Caroline"*. Embeddings rank by *meaning*;
they can't rank by date, identity, or exact value — so those become filters.

Works on every backend (memory, sqlite, postgres, mariadb, clickhouse) and every
retrieval mode (keyword, vector, hybrid).

> **Surface availability.** Filtering is exposed on the **Python API**
> (`Stele.query(..., filters=...)`), the **MCP `stele_query` tool** (`filters`,
> `session_id`, `now` params — dates as ISO-8601 strings), and the **`stele
> query` CLI** (`--filter KEY=VALUE`, `--created-after/before`, `--session-id`,
> `--now`).

## 1. Attach metadata when you store

Filters match against the artifact's `created_at` (automatic) and its `metadata`
dict (yours):

```python
stele.store(
    "fixed the auth token refresh bug and added tests",
    namespace="sessions",
    session_id="2026-05-20-am",
    metadata={
        "date": "2026-05-20",          # ISO date for range filters
        "git_repo": "stele",
        "git_branch": "auth-refactor",
        "tool": "editor",
    },
)
```

Tip: ISO date strings (`YYYY-MM-DD`) sort correctly with range operators, so a
`metadata["date"]` field is a convenient session/event date independent of the
storage `created_at` timestamp.

## 2. Filter at query time

Pass a `filters` dict to `query()`. All keys are AND-combined:

```python
hits = stele.query(
    "sessions",
    "what auth bug did I fix",
    filters={
        "metadata.date__gte": "2026-05-18",   # range
        "metadata.date__lte": "2026-05-24",
        "metadata.git_branch": "auth-refactor",  # exact
    },
)
```

### Supported filter keys

| key | operator | example |
| --- | --- | --- |
| `session_id` | equals | `{"session_id": "2026-05-20-am"}` |
| `created_after` / `created_before` | `created_at` range (datetimes) | `{"created_after": dt(2026,5,18)}` |
| `metadata.<key>` | equals | `{"metadata.git_branch": "auth-refactor"}` |
| `metadata.<key>__in` | membership | `{"metadata.tool__in": ["editor","shell"]}` |
| `metadata.<key>__gte` / `__lte` | range (ISO strings or numbers) | `{"metadata.date__gte": "2026-05-18"}` |

Unknown keys are ignored (forward-compatible). `session_id` can also be passed
as the dedicated `session_id=` argument.

### From the CLI / MCP

```bash
stele query "what auth bug did I fix" --namespace sessions \
  --created-after 2026-05-18T00:00:00 --created-before 2026-05-24T23:59:59 \
  --filter metadata.git_branch=auth-refactor \
  --filter metadata.tool__in=editor,shell
```

The MCP `stele_query` tool takes the same shape: `filters` (object),
`session_id`, and `now` (all dates ISO-8601 strings, coerced server-side).

## 3. Filtering facts (SPO)

When an artifact is indexed with the consolidation chunker
(`IndexingConfig.chunker="consolidation"`), each fact chunk carries typed
`subject` / `predicate` / `object` metadata. Those are filterable like any other
metadata key — a lightweight entity/relation pass:

```python
# vector rank, but only over facts about Caroline
stele.query("sessions", "education plans",
            mode="vector", filters={"metadata.subject": "Caroline"})
```

## 4. Temporal routing (opt-in)

Instead of building the date filter yourself, let stele parse it from a natural
language query. Turn it on in config:

```yaml
retrieval:
  temporal_routing: true        # default false
  temporal_date_field: date     # filter metadata["date"]; omit to use created_at
```

Then a recency phrase is detected, resolved relative to `now`, stripped from the
query (the date words are noise for the embedding), and applied as a filter:

```python
# "last week" -> created_at/metadata.date in [Mon..Sun] of the prior week
hits = stele.query("sessions", "what was I building last week", now=now)
```

- `now` defaults to wall-clock; **pass it explicitly for replay-safe / tested
  runs**.
- If the windowed query returns nothing, stele retries **without** the window
  so an over-tight or wrong parse can't silently hide the answer.
- Grammar: `last/past N days|weeks|months|years`, `N units ago`,
  `last/this week|month|year`, `last/this/bare weekday`, `yesterday`/`today`,
  `since …`, `recently`/`lately`. Non-temporal queries pass through unchanged.

### Using the parser directly

`parse_temporal` is a pure, deterministic, LLM-free function you can call
without enabling routing:

```python
from stele.retrieval.temporal import parse_temporal

cleaned, tf = parse_temporal("what shipped last week", now)
if tf is not None:
    hits = stele.query(ns, cleaned, filters=tf.as_metadata_filters("date"))
    # or tf.as_filters() to target created_at
else:
    hits = stele.query(ns, query)
```

## Why filter-then-rank

Embeddings encode *similarity*, not *identity* or *order*: "7 May" and "12 May"
embed almost identically, so a vector/keyword query cannot rank the right date,
version, ID, or branch to the top. The filter narrows to the exact/in-range set
first; ranking then orders only the survivors by topic. The two compose. See
[`session-memory-metadata-design.md`](../archive/session-memory-metadata-design.md) for the
design rationale and the benchmark that motivated it.

## Performance notes

- `session_id` is applied in SQL on the database backends; `created_at` and
  `metadata` filters are applied over an over-fetched candidate set (the query
  fetches a larger pool when such filters are present, then narrows).
- Keep filter fields small and discrete. Do **not** stuff long text into
  `metadata` expecting semantic match — embed content, filter on fields.
- Metadata is model-visible on `SearchHit.metadata`. Treat `cwd`, file paths,
  usernames, and branch names as a potential PII/secrets surface if memory
  crosses trust boundaries.
