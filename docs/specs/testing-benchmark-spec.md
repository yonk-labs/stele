# Testing and Benchmark Specification

## TL;DR

The rebuild is not complete because it can store artifacts. It is complete when tests and benchmarks prove the four goals: token reduction, long-term recall, PII scrubbing, and better overall performance. This spec defines the required verification stack.

## Test Layers

| Layer | Command | Required In PR | Required For Release | Purpose |
|---|---|---:|---:|---|
| lint | `ruff check .` | yes | yes | style and obvious bugs |
| format | `ruff format --check .` | yes | yes | stable formatting |
| type | `mypy src tests` | yes | yes | public contract safety |
| unit | `pytest tests/unit` | yes | yes | pure logic |
| contract memory | `pytest tests/contract -m memory` | yes | yes | baseline contract |
| contract sqlite | `pytest tests/contract -m sqlite` | yes | yes | default durable backend |
| integration sql | `pytest tests/integration/backends` | no | yes | MariaDB/Postgres/ClickHouse |
| integration vector | `pytest tests/integration/vector` | no | yes | Chunkshop vector behavior |
| integration graph | `pytest tests/integration/pg_raggraph` | no | yes | optional graph retrieval |
| e2e | `pytest tests/e2e` | yes for memory/sqlite | yes all backends | agent/tool flows |
| benchmark smoke | `pytest tests/benchmarks_smoke` | yes | yes | report generation |
| full benchmarks | `python -m stele_bench ...` | no | yes/nightly | product claims |

## Unit Test Requirements

### Core Models

Required cases:

- Valid artifact model.
- Invalid namespace.
- Invalid content type.
- Digest changes when content changes.
- Token estimate is deterministic.
- Metadata JSON round trip.
- Bytes content round trip.
- Lifecycle validation.
- Expiration validation.

### References

Required cases:

- Parse `stele://default/abc`.
- Parse nested namespace `stele://team/project/abc`.
- Reject unsupported reference schemes.
- Parse signed ref.
- Reject malformed scheme.
- Reject missing artifact id.
- Reject tampered signature in required mode.
- Allow unsigned ref in disabled mode.
- Reject expired signed ref in required mode.

### Thresholds

Required cases:

- Below char threshold passes through.
- Above char threshold stores.
- Above token threshold stores.
- `always_store=True` stores.
- Unsupported object is serialized according to content detector.
- Serialization failure follows configured failure mode.

### PII

Required fixture types:

- email
- phone
- SSN-like identifier
- credit-card-like identifier
- API key/token-looking string
- postal address
- person name where provider supports it

Required cases:

- Regex scrubber finds deterministic built-in fixtures.
- Presidio adapter skips cleanly when dependency missing.
- Scrub result includes replacement text and detection summary.
- Replacement is deterministic inside one output.
- Raw text is absent from scrubbed output.

## Contract Test Suite

Every backend runs the same exact storage contract.

Required contract cases:

1. Store text artifact.
2. Fetch exact text.
3. Store bytes artifact.
4. Fetch exact bytes or documented bytes encoding if first build supports text-only durable stores.
5. Delete artifact.
6. Fetch deleted artifact raises `ArtifactNotFound`.
7. List by namespace.
8. List by session id.
9. TTL cleanup removes expired artifact.
10. Manual lifecycle artifact survives TTL cleanup.
11. Old reference alias fetch works after migration import.
12. Metadata round trip.
13. Large content round trip, minimum 1 MB fixture.
14. Capability report includes backend type and durable flag.
15. Raw content does not appear in logs captured by test logger.

Retrieval contract cases:

1. Search within artifact finds known needle.
2. Search within artifact returns bounded text, not full large artifact.
3. Query namespace finds artifact by known topic.
4. Query namespace respects namespace isolation.
5. Explicit unsupported mode raises `CapabilityError`.
6. Implicit default degrades to available retrieval mode.
7. Returned hit uses package-owned `SearchHit`.
8. PII in hit text is scrubbed by default.
9. Raw hit text requires explicit raw mode and config.

## Integration Tests

### LangChain Structural Middleware

Fixture:

- Fake tool returns a 30 KB JSON payload with one known PII value and one known retrieval needle.

Assertions:

- Model-visible tool result contains `stele://`.
- Model-visible tool result contains scrubbed summary.
- Model-visible tool result does not contain raw JSON payload.
- Model-visible tool result does not contain known PII value.
- Advisory fetch can retrieve exact content when raw fetch is enabled.
- Advisory search can retrieve the needle without full fetch.

### MCP Advisory Tools

Assertions:

- `stash_store` stores content and returns compact result.
- `stash_fetch` defaults to scrubbed content.
- `stash_search` returns scrubbed hit text.
- `stash_query` respects namespace.
- `stash_delete` deletes artifact.
- Error responses are structured.

### Chunkshop Vector Integration

Backends:

- SQLite when sqlite-vec path is available.
- MariaDB where vector support is available.
- Postgres with pgvector.
- ClickHouse where Chunkshop sink supports it.

Assertions:

- Artifact indexes through Chunkshop.
- Query vector top-k returns expected artifact in top 5.
- `(doc_id, seq_num)` maps to reference and chunk text.
- No Chunkshop-native result object escapes public API.
- Async indexing status transitions from queued to indexed or failed.

### pg-raggraph Integration

Assertions:

- Non-Postgres backend config does not import pg-raggraph.
- Postgres baseline works with pg-raggraph absent.
- Postgres graph mode works when pg-raggraph is installed and configured.
- Graph adapter returns package-owned `SearchHit` objects.
- Exact fetch still uses artifact table.

## Benchmark Suites

### Suite A: Token Reduction Showcase

Purpose:

- Run the clean-room showcase with the backend matrix.

Workloads:

- legal contract, about 40 KB
- SQL exploration, about 30 KB
- log triage, about 64 KB
- JSON API docs, about 30 KB
- code diff review, about 16 KB
- multi-agent handoff

Metrics:

- input bytes
- input token estimate
- replacement bytes
- replacement token estimate
- token savings
- token savings percent
- summary latency
- store latency
- total intercept latency
- fetch latency
- search latency
- backend
- content type

Pass gate:

- Mean token savings >= 90% for showcase workloads.
- No workload below 75% savings unless documented as below threshold or intentionally not intercepted.
- Raw PII fixture values absent from replacements.

### Suite B: Long-Term Recall

Purpose:

- Prove memory helps across sessions and time.

Internal synthetic workload:

- Generate users/projects/incidents/contracts across 1, 3, 5, 10, and 20 sessions.
- Include updated facts, stale facts, conflicting facts, and absent facts.
- Ask questions after the original session context is removed.

Metrics:

- recall@1
- recall@5
- recall@10
- MRR
- answer exact match
- answer F1
- stale-memory error rate
- abstention accuracy
- retrieval latency
- query token cost

Pass gate for first public claim:

- Beat no-memory baseline on recall@5 and answer F1.
- Stale-memory error rate must be reported, not hidden.
- At least one external benchmark adapter is runnable.

External benchmark candidates:

- LongMemEval
- LoCoMo
- PerLTQA
- RAGAS retrieval-oriented tests
- ARES retrieval evaluation

### Suite C: PII Scrubbing

Purpose:

- Prove sensitive data does not leak through model-visible outputs.

Internal fixture:

- 100+ records with deterministic PII values.
- Mixed content types: text, JSON, logs, table, markdown.
- Include near-misses that should not be scrubbed.

External benchmark candidates:

- PIIBench
- DocPII redaction benchmark
- PRvL-style document PII tasks

Metrics:

- precision
- recall
- F1
- false positives
- false negatives
- leakage count
- utility preservation
- scrub latency
- output byte/token delta after scrubbing

Pass gate:

- Zero known fixture value leakage on default model-visible surfaces.
- Benchmark report must show precision/recall/F1 and false negatives.

### Suite D: Overall Performance

Purpose:

- Prove practical latency/cost/throughput benefit compared with direct in-context handling.

Metrics:

- intercept p50/p95/p99
- summary p50/p95/p99
- store p50/p95/p99
- fetch p50/p95/p99
- search p50/p95/p99
- query p50/p95/p99
- indexing p50/p95/p99
- throughput artifacts/sec
- throughput bytes/sec
- estimated prompt cost saved
- net latency benefit
- breakeven size

Pass gate:

- Benchmarks identify breakeven threshold.
- For showcase-size workloads, net estimated prompt cost reduction must be positive.
- Any backend with poor latency must be documented with recommended use cases.

### Suite E: Retrieval Quality

Purpose:

- Avoid summary-only quality loss.
- Prove the system can stay above the target quality bar compared with direct
  stuffing/full-context handling.

Accuracy target:

- Public quality claims require at least 90% task accuracy relative to the
  direct full-context baseline on deterministic showcase/quality workloads.
- Token reduction numbers without this quality measurement must be labeled
  as prompt-payload reduction only.

Categories:

- summary sufficient
- targeted fact lookup
- multi-hop detail lookup
- transformation task
- full context required
- vocabulary mismatch
- compound intent

Modes:

- no stash/direct context
- summary only
- keyword retrieval
- vector retrieval
- hybrid retrieval
- graph retrieval where available
- full fetch

Metrics:

- deterministic criteria pass/fail
- answer exact match where applicable
- answer F1
- hit contains gold evidence
- tokens consumed
- latency

Pass gate:

- Docs must state where summary-only is unsafe.
- Retrieval modes must improve over summary-only on targeted detail tasks.
- Direct-context baseline and stash-assisted answers must be scored side by side.
- Stash-assisted accuracy must be >= 90% of the direct-context baseline before
  any "minimal loss" claim is allowed.
- Chunkshop-backed chunk/vector retrieval is required before broad accuracy
  claims across detail, multi-hop, and vocabulary-mismatch tasks.

## Report Artifacts

Every benchmark run emits:

```text
benchmark-output/
  <timestamp>/
    report.md
    report.json
    raw/
      runs.jsonl
      environment.json
      config.yaml
```

Required `report.json` fields:

```json
{
  "project": "stele",
  "version": "0.0.0",
  "git_sha": "...",
  "suite": "token_reduction",
  "started_at": "...",
  "finished_at": "...",
  "environment": {},
  "config": {},
  "metrics": {},
  "pass": true,
  "failures": []
}
```

## CI Policy

### Pull Request CI

Required:

- lint
- format check
- type check
- unit tests
- memory contract tests
- SQLite contract tests
- LangChain fake middleware smoke if optional deps installed in CI image
- PII local fixture smoke
- benchmark report generation smoke

### Release CI

Required:

- all PR CI
- MariaDB integration
- Postgres integration
- ClickHouse integration
- Chunkshop vector integration for available backends
- pg-raggraph integration
- showcase token reduction suite
- synthetic long-term recall suite
- PII internal benchmark
- performance benchmark

### Nightly CI

Required where credentials/data are available:

- external long-memory benchmark adapter
- external PII benchmark adapter
- extended concurrency/durability tests
- larger corpus performance tests

## Acceptance Checklist

- Each public claim maps to a benchmark metric.
- Each backend maps to storage and retrieval contract tests.
- PII has both correctness and leakage tests.
- Recall has internal and external evidence paths.
- Performance reports p50/p95/p99 and breakeven, not only averages.
- Benchmark reports are machine-parseable and human-readable.
