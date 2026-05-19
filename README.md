# Stele

**Stele is a sovereign, source-backed memory and living knowledge layer for LLM agents.** It stores the exact evidence behind every memory, supersedes durable facts as the world changes, and lets agents retrieve what was true at any point in time — all on a local-first stack with no required network calls and no hosted dependencies.

The product answers two questions without conflating them:

1. **Artifact question** — what exact source did the agent see, avoid seeing, or retrieve from? Stored once, fetched cheaply, scrubbed of PII before becoming model-visible.
2. **Memory question** — what durable fact, preference, decision, or instruction should future agent work remember? Extracted from artifacts, scoped per user/session/agent, every memory cites the `stele://` evidence that produced it.

When `pg-raggraph` is enabled, Stele's `Revisor` adapter adds the third move: **living knowledge** — newer facts supersede older ones, retracted knowledge can be hidden or flagged, and `as_of` / `version_filter` queries become first-class. Artifacts stay immutable; memories evolve.

The repo is being rebuilt from a clean-room blueprint, phase by phase.
Shipped and on `main`: the artifact-storage foundation plus **memory
supersession + `as_of`** (Phase 1), **deterministic extraction** (Phase 2),
**policy-driven recall** (Phase 3), **Chunkshop vector/hybrid indexing across
five backends** (Phase 4), an **end-to-end test harness** (INFRA-A), and
**living knowledge** — the `pg-raggraph`-backed `Revisor` with post-hoc
supersede/retract, `as_of`/`version_filter` graph search, every hit citing
its `stele://` evidence (Phase 5). Runtime working memory (WorkGraph),
adapter SDK, source connectors, and universal search are the next phases —
see the [order of operations](docs/superpowers/2026-05-17-order-of-operations.md)
for the authoritative path and [current status](docs/current-status.md) for
what's done.

New here? Start with the [Memory tutorial](docs/tutorial-memory.md) — a
hands-on walkthrough of store → extract → supersede → recall.

Key planning docs:

- [Current status](docs/current-status.md)
- [Sovereign memory system plan](docs/sovereign-memory-system-plan.md)
- [PRD: Sovereign Stele](docs/prd-sovereign-stele.md)
- [Architecture: Sovereign Stele](docs/architecture-sovereign-stele.md)
- [Build specs](docs/specs/README.md)
- [Vector & hybrid indexing setup (Phase 4)](docs/vector-indexing-setup.md)
- [Living knowledge setup (Phase 5)](docs/living-knowledge-setup.md)
- [Plugging Stele into an agent (Claude / Codex / MCP / others)](docs/agent-integration.md)
- [Security posture & threat model](docs/SECURITY.md)
- [E2E self-host harness](deploy/README.md)

## Current Functional Surface

The current runnable slice includes:

**Artifact storage foundation**

- memory backend exact store/fetch/delete/list
- SQLite exact storage and FTS retrieval
- Postgres exact storage and full-text retrieval
- optional MariaDB exact storage and keyword retrieval when `stele-core[mariadb]` is installed
- optional ClickHouse exact storage and basic keyword retrieval when `stele-core[clickhouse]` is installed
- deterministic summaries through `lede`
- regex PII scrubbing on model-visible surfaces
- keyword retrieval plus process-local Chunkshop-backed chunk indexing for targeted spans
- structural interception wrapper for oversized tool outputs
- JSONL export/import for replay, migration, and cross-backend benchmark setup
- showcase benchmark for prompt-payload reduction, PII leakage, and latency
- recall benchmark for answer-bearing span retrieval against a direct-context oracle

**Sovereign memory (Phases 1–5)**

- `stele.memory` — scoped memory with supersession (`add(supersedes=[...])`),
  post-hoc `retract(...)`, soft delete, content-hash dedup, and
  `as_of=<datetime>` time-travel queries on SQLite + Postgres
- `stele.extract` — deterministic extraction of memories from artifacts,
  message threads, or raw text (`from_artifact` / `from_messages` /
  `from_text`); no LLM, no embeddings
- `stele.recall` — policy-driven context selection with seven strategies
  (`summary_only`, `memory_search`, `artifact_search`, `graph_search`,
  `adaptive`, `raw_fetch`, `abstain`) behind one callable facade
- vector + hybrid retrieval across all five backends via Chunkshop
  (`indexing.mode` / `retrieval.default_mode`) — Phase 4
- **living knowledge** (Phase 5, opt-in `stele-core[postgres-graph]` on a
  Postgres backend): `graph_search` with `as_of` / `version_filter` /
  `retracted_behavior`; `memory.retract()` and `add(supersedes=)` project
  into a `pg-raggraph` graph; every graph hit recovers its exact `stele://`
  source. Off by default; non-Postgres deployments keep memory evolution and
  `graph_search` reports `CapabilityError` (capability honesty).
- every memory cites the `stele://` evidence that produced it; PII scrubbing
  is inherited end to end and never duplicated

See the [Memory tutorial](docs/tutorial-memory.md) for a runnable walkthrough.

## Sovereign Memory in 30 Seconds

```python
from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope

stele = Stele.from_config({"backend": {"type": "sqlite", "path": "stele.db"}})
scope = MemoryScope(user_id="alice")

# 1. Store an artifact (the evidence)
stored = stele.store(content="Alice said: I prefer Helix over Vim.")

# 2. Extract durable memories from it — every memory cites the stele:// source
report = stele.extract.from_artifact(artifact_id=stored.artifact_id, scope=scope)
print(report.stats)  # ExtractionStats(candidate_count=..., accepted_count=...)

# 3. Later, the world changes — supersede the old preference atomically
old = stele.memory.search(
    MemoryQuery(query="editor preference", scope=scope)
)[0]
stele.memory.add(
    text="Alice now prefers Zed.",
    kind="preference",
    source_refs=[stored.reference],
    scope=scope,
    supersedes=[old.id],
)

# 4. Recall the right context for an LLM — adaptive escalation, no oracle
result = stele.recall(query="what editor does Alice prefer?", scope=scope)
print(result.strategy_used, result.context)

# Time-travel: what did we believe before the change?
past = stele.memory.search(
    MemoryQuery(query="editor preference", scope=scope, as_of=old.created_at)
)
```

See [docs/tutorial-memory.md](docs/tutorial-memory.md) for the full walkthrough.

## Living Knowledge (Phase 5)

Opt-in, on a Postgres backend, with `pip install 'stele-core[postgres-graph]'`.
Stele projects memory evolution into a `pg-raggraph` graph so `graph_search`
honors supersession, retraction, and time-travel — every hit still cites its
exact `stele://` source.

```python
from datetime import UTC, datetime
from stele import Stele
from stele.core.memory_record import MemoryScope

stele = Stele.from_config({
    "backend": {"type": "postgres", "dsn": "postgresql://yonk:yonk@localhost:55453/stele"},
    "graph": {"enabled": True, "namespace": "kb"},
})
scope = MemoryScope(namespace="kb")

m = stele.memory.add(text="Study X says compound Z prevents disease.",
                     kind="fact", source_refs=["stele://kb/study-x"], scope=scope)

# Retract it post-hoc — policy decides what graph_search does with it
stele.memory.retract(m.record.id, reason="retracted by journal")

hidden  = stele.recall(query="does Z prevent disease", scope=scope,
                        strategy="graph_search", retracted_behavior="hide")
flagged = stele.recall(query="does Z prevent disease", scope=scope,
                        strategy="graph_search", retracted_behavior="flag")
# hidden.citations excludes it; flagged.citations still CITES it, marked retracted

# Time-travel: what did the graph believe at a past instant?
past = stele.recall(query="does Z prevent disease", scope=scope,
                    strategy="graph_search", as_of=datetime.now(UTC))
```

`graph.enabled` defaults to `false`. Without the extra / not on Postgres,
`graph_search` raises `CapabilityError` and the rest of Stele is unaffected.
Full guide: [docs/living-knowledge-setup.md](docs/living-knowledge-setup.md).
Runnable: `STELE_PG_RAGGRAPH_DSN=… scripts/demo-living-knowledge.sh`.

## Showcase Benchmark

Run the current showcase report:

```bash
.venv/bin/python -m benchmarks.showcase
```

It writes:

- `benchmarks/runs/<date>/Showcase.md`
- `benchmarks/runs/<date>/Showcase.json`

Default local scope is `MemoryBackend` and `SQLiteBackend`. When
`STELE_PG_DSN` is set, `PostgresBackend` is included.

Important: the current showcase measures prompt-payload reduction, exact fetch,
keyword search hit count, latency, and PII leakage. It is not an answer-accuracy
benchmark. Public "minimal loss" claims require a separate direct-context
baseline comparison with >=90% task accuracy and Chunkshop-backed chunk retrieval.

## Recall Benchmark

Run the deterministic recall benchmark:

```bash
.venv/bin/python -m benchmarks.recall
```

It writes:

- `benchmarks/runs/<date>/Recall.md`
- `benchmarks/runs/<date>/Recall.json`

This benchmark reports direct-context oracle accuracy separately from retrieval
answer-span accuracy. The fixture target is `>=90%` retrieval answer accuracy.

## JSONL Replay

Every backend can use the same artifact stream:

```python
from stele import Stele

source = Stele.from_config({"backend": {"type": "sqlite", "path": "stele.db"}})
source.export_jsonl("benchmarks/runs/artifacts.jsonl")

target = Stele.from_config({"backend": {"type": "memory"}})
target.import_jsonl("benchmarks/runs/artifacts.jsonl")
```

JSONL replay preserves references, summaries, metadata, timestamps, and exact
content, including bytes.

## Backend Extras

Install only the drivers you need:

```bash
pip install 'stele-core[postgres]'
pip install 'stele-core[mariadb]'
pip install 'stele-core[clickhouse]'
pip install 'stele-core[all-backends]'
pip install 'stele-core[chunkshop]'        # Phase 4 vector/hybrid indexing
pip install 'stele-core[postgres-graph]'   # Phase 5 living knowledge (Postgres only)
```

`[postgres-graph]` is independent of `[postgres]`; it pins the
`pg-raggraph` version carrying the consumer surface Phase 5 needs and is
only meaningful on a Postgres backend with `graph.enabled: true`:

```yaml
backend:
  type: postgres
  dsn: postgresql://yonk:yonk@localhost:55453/stele
graph:
  enabled: true
  namespace: kb
  retracted_behavior: surface_both   # hide | flag | surface_both
```

Backend config examples:

```yaml
backend:
  type: postgres
  dsn: postgresql://yonk:yonk@localhost:55432/stele
```

```yaml
backend:
  type: mariadb
  dsn: mariadb://yonk:yonk@localhost:3306/stele
```

```yaml
backend:
  type: clickhouse
  dsn: http://default:@localhost:8123/stele
```

## Postgres Demo

Start a repeatable local Postgres 16 + pgvector environment:

```bash
scripts/postgres-up.sh
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
scripts/test-postgres.sh
```

See [docs/postgres-demo.md](docs/postgres-demo.md).
