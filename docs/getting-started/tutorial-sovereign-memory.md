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
| `graph_search` | Phase 5 living knowledge: real on a Postgres backend with `stele-core[postgres-graph]` and `graph.enabled: true` (supports `as_of` / `version_filter` / `retracted_behavior`); raises `CapabilityError` otherwise. See [living-knowledge-setup.md](../guides/living-knowledge-setup.md). |

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

## 8. Richer memories: tripartite insight, evidence, and lifecycle kinds (v0.4.0)

A memory no longer has to be one opaque blob. You can record the **observation**,
the **supporting detail**, and the **action** separately, and the evidence
behind a memory now *evolves* as the same fact is re-observed.

### Tripartite insight

`add` accepts three optional fields alongside `text`. They are PII-scrubbed like
`text`, and search indexes the composed view, so a term that lives only in
`detail` is still findable:

```python
r = stele.memory.add(
    text="cooperative-sticky avoids the rebalancing storm",
    summary="consumers rebalance on every deploy",
    detail="the cooperative-sticky assignor keeps partitions put across restarts",
    action="set partition.assignment.strategy=cooperative-sticky",
    kind="fact",
    source_refs=[stored.reference],
    scope=scope,
)
got = stele.memory.get(r.record.id)
print(got.summary, "|", got.action)

# "assignor" appears only in `detail` — composed indexing still finds it:
hits = stele.memory.search(MemoryQuery(query="assignor", scope=scope))
assert r.record.id in {h.id for h in hits}
```

`record.indexable_text` is the composed view used for search/dedup; when the
three fields are absent it falls back to `text`, so existing memories behave
exactly as before.

### Evidence that evolves — re-observation merges

Re-asserting the *same* fact in the same scope no longer inserts a twin row. It
**confirms** the existing memory: `confirmations` increments, `last_confirmed`
is stamped, and `confidence` rises toward `1.0` (never above it, never down).
The asserted text stays immutable — only the evidence about it moves.

```python
first = stele.memory.add(
    text="prod runs in us-east-1", kind="fact",
    source_refs=[stored.reference], scope=scope, confidence=0.5,
)
again = stele.memory.add(           # same text + scope, not superseding
    text="prod runs in us-east-1", kind="fact",
    source_refs=[stored.reference], scope=scope, confidence=0.5,
)
assert again.record.id == first.record.id      # same row, not a twin
assert again.duplicate_of == first.record.id
assert again.record.confirmations == 2
assert again.record.confidence > 0.5           # evolved upward
```

This holds for `add_many` too (including duplicates within one batch), so it
stays observably equal to N sequential `add` calls. Passing `supersedes=[...]`
opts out of the merge — that is an intentional new assertion, not a
re-observation.

`search_with_score` stamps `last_queried` on the rows it surfaces, so you can
tell which memories recall actually used:

```python
hits = stele.memory.search_with_score("prod region", scope)
print(stele.memory.get(hits[0].record.id).last_queried)   # a timestamp now
```

### cq lifecycle kinds

`kind` gained four lifecycle values for capturing agent friction:
`pitfall` (L1) → `workaround` (L2) → `tool_recommendation` (L3) → `tool_gap`
(L4). The L2→L3 transition is just supersession; clustering workarounds into an
L4 signal is a consumer concern (stele only stores the kinds).

```python
wa = stele.memory.add(
    text="pin the transitive dep to dodge the resolver bug",
    kind="workaround", source_refs=[stored.reference], scope=scope,
)
stele.memory.add(
    text="use the resolver's new --strict flag, which fixes it natively",
    kind="tool_recommendation", source_refs=[stored.reference],
    scope=scope, supersedes=[wa.record.id],
)
```

## 9. Optional: semantic recall over memories (v0.5.0, Postgres)

By default `memory.search` ranks by keyword (tsvector) + recency. On a
**Postgres** backend you can opt into a vector leg so a paraphrase with no shared
keywords still recalls the right fact:

```python
stele = Stele.from_config({
    "backend": {"type": "postgres", "dsn": "postgresql://…/db"},
    "retrieval": {"memory_vector": True},   # opt-in; Postgres-only; needs chunkshop
})
print(stele.capabilities().memory_vector_search)   # True
```

When enabled, each memory's `indexable_text` is embedded on write (the embedder
is synthesized internally from the same fastembed model the chunk index uses —
nothing to wire up), and `search_with_score` fuses the keyword and vector legs
via RRF. When it is off — the default, and every non-Postgres backend — recall
is byte-identical to before, so this costs nothing until you ask for it. See
[vector-indexing-setup.md](../guides/vector-indexing-setup.md) for the embedding model
knobs, and note the cheaper alternative of bridging facts into the existing
chunk index if you already run it.

## 10. Clean up

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
- Re-observing a fact confirms (never duplicates) it; the asserted text is never
  mutated; `update(text=...)` still raises. Covered by
  `tests/contract/test_memory_contract.py` and `tests/unit/core/test_memory_duplicates.py`.
- Composed-insight search, evidence evolution, and the lifecycle kinds are
  contract-tested across the memory / sqlite / postgres backends; optional
  Postgres vector recall is proven in `tests/contract/test_memory_vector.py`.
- Recall imports no LLM client, no `pg_raggraph`, no `chunkshop` — verified by
  `tests/unit/recall/test_architecture.py`.

## Where to go next

- Run the demos: `scripts/demo-cq-memory.sh` (tripartite + evidence + lifecycle
  kinds), `scripts/demo-supersession.sh`, `scripts/demo-extraction.sh`.
- Read the design specs in `docs/archive/superpowers/specs/` for the full contracts.
- See [`docs/project/current-status.md`](../project/current-status.md) for what's shipped and the
  Phase 4–8 roadmap.
