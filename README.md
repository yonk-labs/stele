# Stele

**Stele is a sovereign, source-backed memory and living knowledge layer for LLM agents.** It stores the exact evidence behind every memory, supersedes durable facts as the world changes, and lets agents retrieve what was true at any point in time — all on a local-first stack with no required network calls and no hosted dependencies.

The product answers two questions without conflating them:

1. **Artifact question** — what exact source did the agent see, avoid seeing, or retrieve from? Stored once, fetched cheaply, scrubbed of PII before becoming model-visible.
2. **Memory question** — what durable fact, preference, decision, or instruction should future agent work remember? Extracted from artifacts, scoped per user/session/agent, every memory cites the `stele://` evidence that produced it.

When `pg-raggraph` is enabled, Stele's `Revisor` adapter adds the third move: **living knowledge** — newer facts supersede older ones, retracted knowledge can be hidden or flagged, and `as_of` / `version_filter` queries become first-class. Artifacts stay immutable; memories evolve.

The repo is mid-rebuild from a clean-room blueprint. Today's runnable slice is the artifact-storage foundation; sovereign memory extraction, `Revisor`, source connectors, and universal search are the next phases — see the [sovereign memory system plan](docs/sovereign-memory-system-plan.md) for the full path.

Key planning docs:

- [Current status](docs/current-status.md)
- [Sovereign memory system plan](docs/sovereign-memory-system-plan.md)
- [PRD: Sovereign Stele](docs/prd-sovereign-stele.md)
- [Architecture: Sovereign Stele](docs/architecture-sovereign-stele.md)
- [Build specs](docs/specs/README.md)

## Current Functional Surface

The current runnable slice includes:

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
