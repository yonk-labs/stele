# Stele Clean-Room Blueprint

## TL;DR

Build `stele` as a clean-room off-prompt memory layer for LLM agents. The product contract is simple: intercept large tool outputs, store exact artifacts, return compact model-visible references, scrub PII, and retrieve relevant details through backend-native search and Chunkshop-backed chunk/vector indexing. Public docs, reports, and APIs should describe this product on its own terms.

## Product Contract

- Large tool output is intercepted before it enters the model prompt.
- Exact content is stored behind an opaque `stele://<namespace>/<artifact_id>` reference.
- Model-visible surfaces return scrubbed summaries and bounded retrieval snippets by default.
- Exact raw fetch exists only through explicit trusted/raw configuration.
- Retrieval has one public shape across backends: `search(reference, query)` and `query(namespace, query)`.
- Backends report capabilities honestly instead of pretending SQLite, MariaDB, Postgres, ClickHouse, and memory have identical semantics.
- Accuracy claims require direct-context baseline comparison and >=90% task accuracy.
- Prompt-payload reduction claims must not be presented as answer quality.

## OSS Roles

- `lede`: deterministic hot-path summaries.
- `chunkshop`: chunking, embedding, vector indexing, and cross-backend vector retrieval where supported.
- `pg-raggraph`: optional Postgres-only graph/time-aware retrieval mode.

## Backend Strategy

- Memory: local development, unit tests, simple keyword retrieval.
- SQLite: durable local backend with exact artifact storage and FTS5 retrieval.
- Postgres: primary production backend with exact artifact storage, JSONB metadata, FTS retrieval, and optional Chunkshop/pg-raggraph extensions.
- MariaDB: exact storage plus FULLTEXT/fallback retrieval, then Chunkshop where supported.
- ClickHouse: analytical artifact store with explicit delete/TTL semantics and Chunkshop retrieval where supported.

## Completion Bar

The system is not done when it can store content. It is done when it proves:

- prompt-payload reduction
- >=90% task accuracy relative to direct-context baseline for quality claims
- long-term recall across sessions
- PII scrubbing with leakage checks
- backend contract conformance
- repeatable reports and Docker-backed integration tests

