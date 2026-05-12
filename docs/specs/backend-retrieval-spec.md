# Backend and Retrieval Specification

## TL;DR

All backends must satisfy exact artifact storage. Retrieval is capability-based: memory uses in-process keyword search, SQLite uses exact tables plus FTS5, MariaDB uses exact tables plus FULLTEXT or fallback, Postgres uses exact tables plus FTS/vector/optional pg-raggraph, and ClickHouse uses append-optimized exact storage plus documented TTL/delete semantics and vector retrieval where configured. Chunkshop is the common chunk/vector indexing adapter. pg-raggraph is a Postgres-only retrieval provider.

## Backend Capability Matrix

| Backend | Exact Store | Keyword | Vector | Hybrid | Graph | TTL Cleanup | Hard Delete |
|---|---:|---:|---:|---:|---:|---:|---:|
| memory | yes | yes | optional no-op/future | no | no | yes | yes |
| SQLite | yes | FTS5 | Chunkshop/sqlite-vec when configured | optional rank merge | no | yes | yes |
| MariaDB | yes | FULLTEXT or fallback LIKE | Chunkshop when configured | optional rank merge | no | yes | yes |
| Postgres | yes | tsvector | Chunkshop/pgvector when configured | optional rank merge | pg-raggraph when configured | yes | yes |
| ClickHouse | yes | optional basic text predicates | Chunkshop when configured | optional rank merge | no | backend TTL/manual mutation | eventually consistent depending engine |

Capabilities must be reported by runtime config and installed dependencies, not by backend name alone.

## StorageBackend Protocol

```python
class StorageBackend(Protocol):
    def initialize(self) -> None: ...
    def store(self, artifact: Artifact) -> ArtifactRecord: ...
    def fetch(self, reference: Reference) -> ArtifactRecord: ...
    def try_fetch(self, reference: Reference) -> ArtifactRecord | None: ...
    def list(
        self,
        *,
        namespace: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[ArtifactRecord]: ...
    def delete(self, reference: Reference) -> bool: ...
    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult: ...
    def capabilities(self) -> StorageCapabilities: ...
    def close(self) -> None: ...
```

## RetrievalBackend Protocol

```python
class RetrievalBackend(Protocol):
    def search_artifact(
        self,
        reference: Reference,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | None = None,
        filters: QueryFilters | None = None,
    ) -> list[SearchHit]: ...

    def query_namespace(
        self,
        namespace: str,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | None = None,
        filters: QueryFilters | None = None,
    ) -> list[SearchHit]: ...

    def capabilities(self) -> RetrievalCapabilities: ...
```

## Artifact Table Contract

Every durable backend needs an artifact table or equivalent relation with these logical columns:

| Column | Type | Required | Notes |
|---|---|---:|---|
| artifact_id | string | yes | primary id, URL-safe |
| reference | string | yes | canonical new reference |
| namespace | string | yes | indexed |
| session_id | string null | no | indexed |
| content | text/blob | yes | exact original payload |
| content_encoding | string | yes | utf-8, base64, bytes |
| content_type | string | yes | package enum |
| metadata_json | json/text | yes | arbitrary user metadata |
| summary | text | yes | scrubbed summary returned by default |
| raw_summary | text null | no | only if configured to retain |
| digest_sha256 | string | yes | exact content digest |
| byte_size | integer | yes | exact encoded byte size |
| token_estimate | integer | yes | deterministic estimate |
| lifecycle | string | yes | session, ttl, manual |
| expires_at | timestamp null | no | indexed where supported |
| created_at | timestamp | yes | indexed |
| updated_at | timestamp | yes | updated on metadata/lifecycle changes |

## Chunk Table Contract

When retrieval needs local chunks, use this logical shape. Chunkshop-owned tables may be used directly if they preserve equivalent mapping.

| Column | Type | Required | Notes |
|---|---|---:|---|
| chunk_id | string | yes | unique |
| artifact_id | string | yes | indexed |
| reference | string | yes | denormalized for fast result mapping |
| namespace | string | yes | indexed |
| seq_num | integer | yes | chunk order |
| text | text | yes | original chunk text before output scrubbing |
| text_digest_sha256 | string | yes | dedupe/debug |
| metadata_json | json/text | yes | includes content type and chunk offsets |
| created_at | timestamp | yes | indexed |

## Memory Backend

Purpose:

- Fast local development.
- Unit and contract tests.
- In-process agents.

Data structures:

- `dict[str, ArtifactRecord]` keyed by canonical reference.
- `dict[str, set[str]]` namespace index.
- `dict[str, set[str]]` session index.
- Optional simple chunk list per artifact.

Keyword retrieval:

- Case-insensitive token matching.
- Score can be normalized overlap: matched query tokens divided by query token count.
- Return chunks or line windows, not whole artifact, when possible.

Limitations:

- No durability.
- No cross-process visibility.
- Capability report must mark durable=false.

## SQLite Backend

Purpose:

- Default durable local backend.
- CI-required durable backend.

Storage:

- One SQLite database file.
- Enable WAL mode by default.
- Use `json` stored as text.
- Use FTS5 virtual table for keyword search.

Recommended schema:

```sql
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  reference TEXT NOT NULL UNIQUE,
  namespace TEXT NOT NULL,
  session_id TEXT,
  content BLOB NOT NULL,
  content_encoding TEXT NOT NULL,
  content_type TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  summary TEXT NOT NULL,
  raw_summary TEXT,
  digest_sha256 TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  token_estimate INTEGER NOT NULL,
  lifecycle TEXT NOT NULL,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_namespace ON artifacts(namespace);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_expires ON artifacts(expires_at);

CREATE VIRTUAL TABLE IF NOT EXISTS artifact_fts
USING fts5(artifact_id UNINDEXED, namespace UNINDEXED, reference UNINDEXED, content);
```

Delete semantics:

- Delete artifact row.
- Delete FTS rows.
- Delete local chunk rows if present.
- Ask Chunkshop adapter to delete vector rows where supported, or tombstone if not.

## MariaDB Backend

Purpose:

- MySQL-family deployment support.

Storage:

- Use `LONGTEXT` or `LONGBLOB` for content.
- Use `JSON` where available, otherwise text-encoded JSON.
- Use `FULLTEXT` index for keyword retrieval when engine/version supports it.
- Fallback to `LIKE` only for small/dev cases and report degraded capability.

Recommended schema notes:

- `artifact_id VARCHAR(128) PRIMARY KEY`
- `reference VARCHAR(512) UNIQUE`
- `namespace VARCHAR(255)`
- `content LONGTEXT` for text, `LONGBLOB` for bytes if binary split is needed.
- `metadata_json JSON`
- `FULLTEXT(content, summary)` when supported.

Delete semantics:

- Transactional artifact delete.
- Delete related chunk/index rows in same transaction where local tables are used.
- Chunkshop vector delete support must be detected; otherwise mark vector index stale and rebuild.

## Postgres Backend

Purpose:

- Strong general production backend.
- Baseline keyword and vector retrieval.
- Optional graph/time-aware retrieval through pg-raggraph.

Storage:

- Use `TEXT` for text content and `BYTEA` for bytes if binary is supported in first build.
- Use `JSONB` metadata.
- Use `tsvector` generated column or maintained column for keyword retrieval.
- Use pgvector only through Chunkshop adapter unless local direct vector support is explicitly added later.

Recommended schema notes:

```sql
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  reference TEXT NOT NULL UNIQUE,
  namespace TEXT NOT NULL,
  session_id TEXT,
  content BYTEA NOT NULL,
  content_encoding TEXT NOT NULL,
  content_type TEXT NOT NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary TEXT NOT NULL,
  raw_summary TEXT,
  digest_sha256 TEXT NOT NULL,
  byte_size BIGINT NOT NULL,
  token_estimate BIGINT NOT NULL,
  lifecycle TEXT NOT NULL,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_namespace ON artifacts(namespace);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_expires ON artifacts(expires_at);
```

Keyword retrieval:

- Use `to_tsvector` and `plainto_tsquery` or `websearch_to_tsquery`.
- Rank with `ts_rank_cd`.

pg-raggraph boundary:

- Adapter owns conversion from `ArtifactRecord` to pg-raggraph records.
- Adapter never changes the public API shape.
- Adapter is only constructed when backend type is Postgres and graph provider is enabled.
- Non-Postgres configs must not import pg-raggraph.
- Exact CRUD must use the Postgres artifact table, not pg-raggraph APIs.

## ClickHouse Backend

Purpose:

- Large-scale analytical artifact storage and retrieval experiments.

Storage:

- Use MergeTree-family table.
- Partition by month or namespace hash if needed.
- Primary sort key should support namespace/time scans.
- Exact fetch by reference should be supported through indexed/sorted reference lookup, but expected latency must be benchmarked.

Recommended schema notes:

```sql
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id String,
  reference String,
  namespace String,
  session_id Nullable(String),
  content String,
  content_encoding String,
  content_type String,
  metadata_json String,
  summary String,
  raw_summary Nullable(String),
  digest_sha256 String,
  byte_size UInt64,
  token_estimate UInt64,
  lifecycle String,
  expires_at Nullable(DateTime64(3, 'UTC')),
  created_at DateTime64(3, 'UTC'),
  updated_at DateTime64(3, 'UTC'),
  deleted UInt8 DEFAULT 0
)
ENGINE = MergeTree
ORDER BY (namespace, reference, created_at);
```

Delete semantics:

- First build may use tombstones (`deleted=1`) plus optional asynchronous mutation.
- Capability report must state whether hard delete is immediate, eventual, or unsupported.
- TTL cleanup may use ClickHouse TTL clauses or explicit mutation; benchmark and docs must say which.

Keyword retrieval:

- First build can expose basic substring search as `keyword_degraded`.
- Full text indexes may be added if target ClickHouse version supports the desired feature.

## Chunkshop Integration

Purpose:

- Reuse existing chunking, embedding, and backend vector sink support.
- Avoid creating duplicate vector schemas unless Chunkshop lacks a needed mapping.

Confirmed local constraints:

- Local Chunkshop v4 exposes `Pipeline.ingest_text(doc_id, text, metadata)` and sink `query_top_k(query_vec, k)`.
- `ingest_text` returns count, not chunk objects.
- Sink hit shape is `(doc_id, seq_num, distance)`.

Adapter responsibilities:

1. Convert artifact to Chunkshop document:

```python
doc_id = artifact.artifact_id
text = artifact.content_as_text()
metadata = {
    "reference": artifact.reference,
    "namespace": artifact.namespace,
    "session_id": artifact.session_id,
    "content_type": artifact.content_type,
    "created_at": artifact.created_at.isoformat(),
}
```

2. Store enough local mapping to resolve `(doc_id, seq_num)` to chunk text.
3. Call Chunkshop pipeline to index text.
4. Use Chunkshop sink `query_top_k` for vector top-k.
5. Map vector hits back to package-owned `SearchHit`.
6. Scrub hit text before returning unless raw output is explicitly enabled.

Indexing modes:

- `skip`: store exact artifact only.
- `async`: submit indexing job and return immediately.
- `sync`: block until keyword/vector indexes are updated.

Failure policy:

- Store success must not be rolled back when async indexing fails.
- `StoredResult.index_status` must reflect queued/indexed/skipped/failed.
- Index errors must be visible through status and metrics.

## Hybrid Retrieval

Hybrid mode combines keyword and vector hits when both are available.

Ranking rule for first build:

```text
hybrid_score = keyword_weight * normalized_keyword_score + vector_weight * normalized_vector_score
```

Defaults:

```yaml
retrieval:
  hybrid:
    keyword_weight: 0.45
    vector_weight: 0.55
```

Rules:

- Normalize scores per result set.
- Merge by `(artifact_id, chunk_id or text_digest)`.
- Preserve contributing scores in metadata.
- If one source is unavailable and mode was explicit `hybrid`, raise `CapabilityError`.
- If one source is unavailable and mode was implicit default, degrade to available mode.

## PII and Retrieval

Retrieval backends return unsanitized internal text to the facade. The facade applies PII policy before returning model-visible results.

Rules:

- Backend adapters should not independently scrub unless storage-level scrub mode is enabled.
- Scrubbing belongs at output boundary for consistent behavior.
- Internal chunk text may contain PII if raw artifact contains PII.
- Benchmark fixtures must assert known PII values do not appear after facade output scrubbing.

## Migrations

Migration framework:

- Use simple numbered SQL files per backend.
- Track applied migrations in `stele_migrations`.
- Migrations must be idempotent.
- First migration creates artifact tables and indexes.
- Retrieval/index tables can have separate migrations.

Directory:

```text
src/stele/storage/migrations/
  sqlite/
    001_artifacts.sql
    002_keyword_fts.sql
  mariadb/
    001_artifacts.sql
    002_keyword_fulltext.sql
  postgres/
    001_artifacts.sql
    002_keyword_fts.sql
  clickhouse/
    001_artifacts.sql
```

## Acceptance Checklist

- Every backend implements exact store/fetch/delete/list/cleanup.
- Capability reports match actual runtime behavior.
- Keyword retrieval works for memory, SQLite, MariaDB, and Postgres.
- ClickHouse retrieval limitations are explicit and tested.
- Chunkshop vector retrieval maps hits back to references and chunk text.
- pg-raggraph is isolated to the Postgres graph adapter.
- PII scrubbing occurs after retrieval and before public output.
