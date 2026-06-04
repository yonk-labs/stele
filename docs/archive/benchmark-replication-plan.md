# Benchmark and Verification Plan

## TL;DR

Benchmarks must prove product behavior on its own terms. The first showcase report measures prompt-payload reduction, exact fetch, bounded retrieval, latency, and PII leakage across common tool-output workloads. Quality claims require a separate direct-context baseline and >=90% task accuracy.

## Four Product Goals

1. **Prompt-payload reduction:** large tool outputs are replaced by compact summaries/references, with raw content kept off prompt.
2. **Long-term recall:** stored memories improve cross-session recall over time.
3. **PII scrubbing:** sensitive values are removed from model-visible summaries, replacements, and retrieval results.
4. **Overall performance:** latency, throughput, and cost are measured honestly against direct in-context handling.

## Quality Guardrail

- Prompt-payload reduction is not answer accuracy.
- Public "minimal loss" claims require >=90% task accuracy relative to direct full-context baseline.
- Chunkshop-backed chunk/vector retrieval is required before making broad quality claims for detail-heavy, multi-hop, transformation, aggregation, or vocabulary-mismatch workloads.
- Summary-only mode must be reported separately and treated as unsafe for detail-sensitive tasks.

## Showcase Suite

Purpose: verify the core value proposition across common tool-output scenarios.

Workloads:

- legal contract-style document
- SQL/database exploration output
- log triage / incident response buffer
- JSON API documentation payload
- code diff review
- multi-agent handoff

Metrics:

- input bytes and estimated tokens
- replacement bytes and estimated tokens
- prompt-payload reduction percentage
- intercept latency
- fetch latency
- search/query latency
- search hit count
- PII leakage count
- backend name

Current required backends:

- memory
- SQLite
- Postgres when `STELE_PG_DSN` is set

Future backend gates:

- MariaDB
- ClickHouse
- Postgres + pg-raggraph
- Chunkshop vector modes

## Accuracy Suite

Purpose: prove whether stash-assisted retrieval can preserve answer quality.

Modes:

- direct full context baseline
- summary only
- keyword retrieval
- Chunkshop vector retrieval
- hybrid retrieval
- graph retrieval where available
- explicit full fetch

Metrics:

- task accuracy
- answer exact match where applicable
- answer F1
- gold evidence present in retrieved context
- abstention accuracy
- stale-memory error rate
- prompt tokens used
- latency

Pass gate:

- stash-assisted mode must reach >=90% of direct-context baseline before quality-preservation claims are allowed.

## PII Suite

Purpose: prove sensitive data does not leak through model-visible output.

Metrics:

- precision
- recall
- F1
- false positives
- false negatives
- known fixture leakage count
- utility preservation
- scrub latency

Pass gate:

- no known fixture PII appears in default model-visible replacement, summary, search, query, LangChain, or MCP output.

## Long-Term Recall Suite

Purpose: prove useful memory across sessions.

Workloads:

- stable facts across sessions
- updated facts where newer memory supersedes older memory
- conflicting facts
- absent facts requiring abstention
- multi-session project/incident/customer histories

Metrics:

- recall@1, recall@5, recall@10
- MRR
- answer exact match/F1
- stale-memory error rate
- abstention accuracy
- query latency

External benchmark candidates:

- LongMemEval
- LoCoMo
- PerLTQA
- RAGAS retrieval-oriented evaluation
- ARES retrieval evaluation

## Report Artifacts

Each benchmark run emits:

```text
benchmarks/runs/<date>/
  Showcase.md
  Showcase.json
```

Accuracy, PII, recall, and performance suites should use the same pattern:

```text
benchmark-output/<suite>/<timestamp>/
  report.md
  report.json
  raw/runs.jsonl
  environment.json
```

## Drift Rules

- Do not optimize for a large reduction percentage alone.
- Do not describe prompt-payload reduction as accuracy.
- Do not claim long-term recall because data was stored; measure retrieval and answer correctness.
- Do not treat PII as a regex demo; measure leakage and utility preservation.
- Do not claim backend parity without contract tests for each named backend.
