# Tutorial: Sovereign Memory — Store, Extract, Supersede, Recall

This is a hands-on walkthrough of Stele's sovereign-memory layer (Phases 1–3).
By the end you will have stored evidence, extracted durable memories from it,
superseded a fact as the world changed, time-traveled to a past belief, and
asked Stele to assemble the right context for an LLM — all locally, with no
network calls and no LLM in the loop.

Every snippet runs as-is against a throwaway SQLite database.

## Prerequisites

```bash
# from the repo root, with the venv created (uv sync or pip install -e '.[dev]')
.venv/bin/python   # the interpreter used below
```

Everything here works on the `memory` and `sqlite` backends with no extra
services. Postgres behaves identically if you set `STELE_PG_DSN` and use
`{"backend": {"type": "postgres", "dsn": ...}}`.

## 0. The mental model

Stele separates two questions and never conflates them:

| Question | Surface | Mutable? |
|---|---|---|
| *What exact source did the agent see?* | **Artifact** (`stele.store` / `stele.fetch`) | No — immutable |
| *What durable fact should we remember?* | **Memory** (`stele.memory`) | Yes — supersedable |

Memories are *derived* from artifacts and always cite the `stele://` evidence
that produced them. Extraction turns text into memory candidates. Recall
selects the right memories/artifacts as LLM context.

## 1. Open a Stele

```python
from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope

stele = Stele.from_config({"backend": {"type": "sqlite", "path": "/tmp/tut.db"}})
scope = MemoryScope(user_id="alice")
```

`MemoryScope` is how memories are partitioned. The fields are `user_id`,
`agent_id`, `app_id`, `session_id`, `namespace` — all optional, all part of the
content-hash used for duplicate detection. Two memories with identical text but
different scope are *not* duplicates.

## 2. Store an artifact — the evidence

```python
stored = stele.store(
    content="Onboarding note: Alice said she prefers the Helix editor over Vim.",
)
print(stored.artifact_id)   # opaque id
print(stored.reference)     # stele://default/<artifact_id>  — the citation
print(stored.summary)       # deterministic lede summary, already PII-scrubbed
```

`stored.reference` is the canonical `stele://` URI. **Never build these by hand
— always use the value Stele gives you.** It is the provenance every memory
must cite.

## 3. Extract memories from the artifact

```python
report = stele.extract.from_artifact(
    artifact_id=stored.artifact_id,
    scope=scope,
)

print(report.stats)
# ExtractionStats(candidate_count=N, accepted_count=M, rejected_count=K)

for acc in report.accepted:
    c = acc.candidate
    print(f"[{c.kind}] conf={c.confidence:.2f} via={c.classifier_path} :: {c.text}")
    print("   stored as", acc.stored_id)
```

What happened:

- The artifact text ran through the **pure deterministic core**
  (`extract_candidates`) — `lede` extracts key facts/stats/phrases/summary, no
  LLM, no embeddings.
- A **type-based classifier** assigns a default kind (here: `fact`, confidence
  0.7); a **regex pattern overlay** can *override* it to an agent-loop kind
  (`preference`, `decision`, `instruction`, `commitment`, `issue`) when a
  pattern matches with higher confidence.
- The overlay is deliberately conservative — it favors false negatives over
  false positives. The onboarding note is *third-person* ("Alice said she
  prefers…"); the `preference` pack matches *first-person* phrasing ("I
  prefer…", "my favorite…"). So this candidate stays `kind="fact"`. Feed it
  `"I prefer the Helix editor."` instead and you get `kind="preference"`,
  `classifier_path="pattern_overlay"`, confidence 0.85. This conservatism is
  intentional: a wrong kind is worse than a generic one.
- Candidates above `extraction.min_confidence` (default 0.6) are committed via
  `Memory.add`. Rejections (below threshold, duplicate, validation error) are
  recorded in `report.rejected`, not raised.
- Every accepted memory cites `stored.reference` automatically and carries the
  extraction config fingerprint in its metadata.

Two other entry points exist:

```python
# From a raw string — you supply the provenance refs
stele.extract.from_text(
    text="Decision: we will ship the migration on 2026-06-30.",
    source_refs=[stored.reference],
    scope=scope,
)

# From an agent message thread — auto-stashed as one artifact
stele.extract.from_messages(
    messages=[
        {"role": "user", "content": "Always use parameterized SQL queries."},
        {"role": "assistant", "content": "Understood."},
    ],
    scope=scope,
)
```

`from_text` with an empty `source_refs` raises `ValidationError` — a memory
with no evidence is not allowed.

## 4. Search memory

```python
hits = stele.memory.search(
    MemoryQuery(query="editor preference", scope=scope)
)
for m in hits:
    print(m.id, m.status, "::", m.text)
```

`memory.search` takes a `MemoryQuery` (`query`, `scope`, plus optional
`as_of`, `include_superseded`, `limit`). By default it returns only `active`
memories that are valid right now.

## 5. The world changes — supersede a fact

Alice switched editors. We don't *edit* the old memory (memory is
append-only); we add a new one that **supersedes** it, atomically:

```python
old = stele.memory.search(
    MemoryQuery(query="editor preference", scope=scope)
)[0]

evidence = stele.store(content="Standup 2026-05-15: Alice now uses Zed daily.")

result = stele.memory.add(
    text="Alice prefers the Zed editor.",
    kind="preference",
    source_refs=[evidence.reference],
    scope=scope,
    supersedes=[old.id],
)
print(result.record.id, "supersedes", result.superseded_ids)
```

In one transaction: the old memory's `status` flips to `superseded` and its
`effective_until` is stamped; the new memory becomes `active`. A default
search now returns only the Zed memory:

```python
[m.text for m in stele.memory.search(MemoryQuery(query="editor", scope=scope))]
# ['Alice prefers the Zed editor.']
```

> Trying `stele.memory.update(old.id, text="...")` raises `CapabilityError` —
> text edits must go through `add(supersedes=[id])` so history is preserved.

## 6. Time-travel with `as_of`

What did we believe *before* the change?

```python
past = stele.memory.search(
    MemoryQuery(
        query="editor",
        scope=scope,
        as_of=old.created_at,           # any datetime
    )
)
print([m.text for m in past])
# ['Alice prefers the Helix editor.']  — the world as it was then
```

`include_superseded=True` drops the status filter entirely and returns the
full lineage:

```python
everything = stele.memory.search(
    MemoryQuery(query="editor", scope=scope, include_superseded=True)
)
for m in everything:
    print(m.status, "::", m.text)
```

This works identically on SQLite and Postgres — the `as_of` window is a SQL
`WHERE` filter, not an application-layer scan.

## 7. Recall — assemble context for an LLM

`stele.recall` is the policy layer. You ask "give me the right context for
this query" and it picks a strategy and returns a `RecallResult` with the
assembled context, citations, an escalation trail, and cost stats. **It never
calls an LLM** — it selects context; you prompt the model.

```python
result = stele.recall(
    query="what editor does Alice prefer?",
    scope=scope,
    strategy="adaptive",      # the default
)
print(result.strategy_used)   # the tier that actually answered
print(result.context)         # PII-scrubbed text to drop into your prompt
for cite in result.citations:
    print(cite.kind, cite.reference, round(cite.score, 3))
print(result.stats)           # searches/fetches/tokens/latency
```

### The six strategies

| Strategy | What it does |
|---|---|
| `summary_only` | Returns a stored artifact's summary. Requires `artifact_id`. |
| `memory_search` | Scored memory search; optional `artifact_id` scopes to that source. |
| `artifact_search` | Keyword search over the artifact store (global or scoped). |
| `raw_fetch` | Returns an artifact's raw content. Requires `artifact_id`; honors the `pii.raw_fetch_enabled` gate. |
| `abstain` | Returns empty context with a structured reason. Never raises. |
| `adaptive` | Runs tiers (`memory_search → artifact_search → raw_fetch → abstain`) until one clears the confidence floor. |
| `graph_search` | Phase 5 living knowledge: real on a Postgres backend with `stele-core[postgres-graph]` and `graph.enabled: true` (supports `as_of` / `version_filter` / `retracted_behavior`); raises `CapabilityError` otherwise. See [living-knowledge-setup.md](living-knowledge-setup.md). |

Each has a one-line shim:

```python
stele.recall.memory_search(query="editor", scope=scope)
stele.recall.summary_only(artifact_id=stored.artifact_id, scope=scope)
stele.recall.abstain(scope=scope)
```

The canonical call and the shim produce identical results — pick whichever
reads better at the call site.

### How adaptive escalates (no oracle)

`adaptive` runs each tier in order and stops at the first tier where
`hit_count >= 1` **and** `top_score >= confidence_floor` (default 0.4). If a
tier comes back empty or below the floor, it escalates to the next. After the
last real tier it falls back to `abstain`. The full trail is in
`result.escalations`:

```python
r = stele.recall(query="something obscure nobody stored", scope=scope)
print(r.abstained, r.abstain_reason)
for step in r.escalations:
    print(step.strategy, step.hit_count, step.top_score, step.reason)
```

No expected-answer oracle is involved — escalation is a pure deterministic
heuristic. If you *want* LLM-in-the-loop judgment, pass a `sufficient`
callback; that is the only place an LLM can enter, and it is entirely your
decision:

```python
def good_enough(ctx) -> bool:
    # ctx.accumulated_text, ctx.accumulated_citations, ctx.query, ctx.scope
    return "zed" in ctx.accumulated_text.lower()

stele.recall(query="editor?", scope=scope, sufficient=good_enough)
```

### Forced scope

Pass `artifact_id` to lock every strategy (and every adaptive tier) to a
single artifact: `memory_search` filters to memories whose `source_refs`
include that artifact's reference, `artifact_search` scopes to it,
`raw_fetch` fetches it.

## 8. Clean up

```python
stele.close()
```

`close()` releases the artifact store plus any initialized memory/extract/
recall facade. Memory rows are never hard-deleted in this slice —
`stele.memory.delete(id)` is a soft delete (`status="deleted"`); `get(id)`
still returns the row for audit, but `search`/`list` exclude it.

> **Gotcha when re-running this tutorial:** the SQLite memory store lives in
> its *own* file next to the artifact db — for `path="/tmp/tut.db"` that is
> `/tmp/memory_tut.db`. Deleting only `/tmp/tut.db` leaves memories behind, and
> content-hash dedup will then reject the "same" extraction on the next run
> (`accepted_count=0`). To start truly fresh, remove both files.

## What's enforced (so you can trust the above)

- Every memory cites at least one `stele://` source_ref, or `add` raises.
- Memory text is PII-scrubbed at storage time; recall never re-scrubs, it
  inherits scrubbed text and collects `pii_flags`.
- Supersession is atomic — a mid-write failure leaves both rows in their
  pre-state.
- `as_of` behaves identically on SQLite and Postgres (contract tests).
- Recall imports no LLM client, no `pg_raggraph`, no `chunkshop` — verified by
  `tests/unit/recall/test_architecture.py`.

## Where to go next

- Run the demos: `scripts/demo-supersession.sh`, `scripts/demo-extraction.sh`.
- Read the design specs in `docs/superpowers/specs/` for the full contracts.
- See [`docs/current-status.md`](current-status.md) for what's shipped and the
  Phase 4–8 roadmap.
