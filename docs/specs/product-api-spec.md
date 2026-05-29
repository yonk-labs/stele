# Product and API Specification

## TL;DR

`stele` is a Python 3.12+ library that keeps large tool outputs out of the model prompt while preserving exact fetch, targeted retrieval, PII-scrubbed summaries, and reproducible benchmark evidence. The public API owns the product contract. Storage engines, Chunkshop, and pg-raggraph are implementation details behind package-owned models.

## Product Requirements

### PR-001: Structural Interception

Large tool outputs must be intercepted before they become model-visible content.

Required behavior:

- Input above configured thresholds is stored as an exact artifact.
- Model-visible result contains summary, reference, size metadata, retrieval hints, and PII scrub metadata.
- Raw large content is absent from the model-visible replacement.
- Below-threshold content passes through unchanged unless explicit `always_store=True`.
- Failed storage follows configured failure mode: `fail_closed`, `fail_open`, or `raise`.

Default thresholds:

```yaml
interception:
  enabled: true
  min_chars: 8000
  min_estimated_tokens: 2000
  max_replacement_chars: 1800
  fail_mode: raise
```

### PR-002: Exact Artifact Storage

Every stored artifact must be retrievable exactly by reference.

Required behavior:

- `fetch(reference)` returns exact original string/bytes content, subject to access policy and PII output policy.
- Exact fetch must not depend on keyword, vector, or graph retrieval.
- Storage must preserve content type, metadata, namespace, session id, lifecycle, expiration, creation time, and digest.
- A backend may compress internally, but returned exact content must match byte-for-byte for bytes and codepoint-for-codepoint for text.

### PR-003: Targeted Retrieval

Users and agents must be able to search inside one artifact or query across a namespace without fetching all content.

Required behavior:

- `search(reference, query)` searches within one artifact.
- `query(namespace, query)` searches across artifacts in a namespace.
- Results are package-owned `SearchHit` models.
- Unsupported explicit retrieval modes raise `CapabilityError`.
- Default mode picks the best available strategy in this order when configured and healthy: graph, hybrid, vector, keyword.

### PR-004: Long-Term Recall

The system must improve cross-session recall by making stored artifacts discoverable after the original prompt context is gone.

Required behavior:

- Artifacts can be scoped to a namespace and optionally a session.
- Queries can include `session_id`, `created_after`, `created_before`, and metadata filters (`metadata.<key>` eq/`__in`/`__gte`/`__lte`) across all backends and retrieval modes (keyword/vector/hybrid). Optional `retrieval.temporal_routing` parses NL recency windows ("last week") into these filters. See [docs/filtered-retrieval.md](../filtered-retrieval.md).
- Benchmark reports must show recall@K, MRR, answer correctness/F1, stale-memory error rate, and abstention accuracy.
- Public recall claims require at least one external benchmark adapter or documented nightly run.

### PR-004A: Accuracy Preservation

The system must not trade away answer quality just to reduce prompt payload.

Required behavior:

- Token reduction claims must be separated from accuracy/quality claims.
- Public "minimal loss" claims require deterministic accuracy evidence.
- The target quality bar is >=90% task accuracy relative to direct full-context
  baseline on agreed showcase/quality workloads.
- Chunkshop-backed chunk retrieval is required for detail-heavy, multi-hop, and
  vocabulary-mismatch workloads before broad quality claims are made.
- Summary-only mode must be documented as unsafe for tasks that require exact
  details, transformations, multi-hop reasoning, aggregation, or complete review.

### PR-005: PII Scrubbing

PII scrubbing is required on model-visible surfaces.

Required behavior:

- Default model-visible replacement output is scrubbed.
- Search/query results are scrubbed by default.
- MCP and LangChain advisory tool outputs are scrubbed by default.
- Summaries are scrubbed before return.
- Exact `fetch()` defaults to scrubbed output unless caller explicitly requests raw fetch through an unsafe method or config.
- Raw fetch must be visually and programmatically distinct: `fetch_raw(reference)` or `fetch(reference, raw=True)`.
- Raw fetch should require `allow_raw_fetch=True` in config.
- PII detections include entity type, span offsets when available, replacement token, confidence, and detector.

Default PII policy:

```yaml
pii:
  enabled: true
  default_surface_policy: scrub
  raw_fetch_enabled: false
  providers:
    - regex
  replacement_style: typed_token
```

### PR-006: Backend Portability

The public API must support memory, SQLite, MariaDB, Postgres, and ClickHouse without pretending they have identical internals.

Required behavior:

- Each backend reports capabilities.
- Unsupported features degrade only when mode is implicit.
- Exact storage contract is identical across all supported backends.
- Retrieval quality and latency are measured per backend.

### PR-007: Optional Integrations

Core install must work without SQL drivers, Chunkshop, pg-raggraph, LangChain, MCP, or Presidio.

Required behavior:

- `import stele` works with only core deps.
- Optional modules import lazily.
- Missing optional dependency errors name the required extra.
- pg-raggraph is only imported by the Postgres pg-raggraph retrieval adapter.

## Public Python API

### Package Exports

```python
from stele import (
    Stele,
    StashConfig,
    Artifact,
    StoredResult,
    FetchResult,
    SearchHit,
    RetrievalMode,
    CapabilityError,
)
```

### Main Facade

```python
class Stele:
    @classmethod
    def from_config(cls, config: StashConfig | dict | str | Path) -> "Stele": ...

    def store(
        self,
        content: str | bytes,
        *,
        namespace: str = "default",
        session_id: str | None = None,
        content_type: ContentType | str | None = None,
        metadata: dict[str, Any] | None = None,
        lifecycle: Lifecycle | str = "manual",
        ttl_seconds: int | None = None,
        index: Literal["async", "sync", "skip"] | None = None,
    ) -> StoredResult: ...

    def fetch(
        self,
        reference: str,
        *,
        raw: bool = False,
        scrub: bool | None = None,
    ) -> FetchResult: ...

    def search(
        self,
        reference: str,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | str | None = None,
        raw: bool = False,
    ) -> list[SearchHit]: ...

    def query(
        self,
        namespace: str,
        query: str,
        *,
        limit: int = 10,
        mode: RetrievalMode | str | None = None,
        session_id: str | None = None,
        filters: dict[str, Any] | None = None,
        raw: bool = False,
    ) -> list[SearchHit]: ...

    def list(
        self,
        *,
        namespace: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page[ArtifactRecord]: ...

    def delete(self, reference: str) -> bool: ...
    def cleanup_expired(self, *, limit: int = 1000) -> CleanupResult: ...
    def capabilities(self) -> StashCapabilities: ...
    def close(self) -> None: ...
```

### Plain Wrapper API

```python
def stash_tool_result(
    result: Any,
    *,
    stash: Stele,
    namespace: str = "default",
    session_id: str | None = None,
    tool_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Return original result or compact replacement depending on thresholds."""
```

### LangChain Middleware API

```python
def create_memory_stash_middleware(
    stash: Stele,
    *,
    namespace: str = "default",
    session_id_getter: Callable[[Any], str | None] | None = None,
    tool_name_getter: Callable[[Any], str | None] | None = None,
) -> Any:
    ...
```

### LangChain Advisory Tools

Required tools:

- `memory_stash_fetch`
- `memory_stash_search`
- `memory_stash_query`
- `memory_stash_list`
- `memory_stash_delete`
- `memory_stash_summarize`

### MCP Tools

Required tools:

- `stash_store`
- `stash_fetch`
- `stash_search`
- `stash_query`
- `stash_list`
- `stash_delete`
- `stash_capabilities`

MCP tools are advisory only. They do not intercept model-visible tool outputs unless the host explicitly routes through them.

## Data Models

### ContentType

```python
ContentType = Literal[
    "text",
    "json",
    "table",
    "csv",
    "sql",
    "code",
    "code_diff",
    "log",
    "html",
    "markdown",
    "blob",
]
```

### Lifecycle

```python
Lifecycle = Literal["session", "ttl", "manual"]
```

### RetrievalMode

```python
RetrievalMode = Literal["keyword", "vector", "hybrid", "graph"]
```

### Artifact

```python
class Artifact(BaseModel):
    artifact_id: str
    reference: str
    namespace: str
    session_id: str | None = None
    content: str | bytes
    content_encoding: Literal["utf-8", "base64", "bytes"] = "utf-8"
    content_type: ContentType
    metadata: dict[str, Any] = Field(default_factory=dict)
    summary: str
    raw_summary: str | None = None
    digest_sha256: str
    byte_size: int
    token_estimate: int
    lifecycle: Lifecycle
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
```

### StoredResult

```python
class StoredResult(BaseModel):
    artifact_id: str
    reference: str
    namespace: str
    session_id: str | None
    summary: str
    content_type: ContentType
    byte_size: int
    token_estimate: int
    replacement_char_count: int
    estimated_token_savings: int
    estimated_token_savings_pct: float
    index_status: Literal["queued", "indexed", "skipped", "failed"]
    pii: PIIScrubSummary
    created_at: datetime
```

### FetchResult

```python
class FetchResult(BaseModel):
    artifact_id: str
    reference: str
    content: str | bytes
    content_type: ContentType
    raw: bool
    scrubbed: bool
    pii: PIIScrubSummary
    metadata: dict[str, Any]
    digest_sha256: str
    byte_size: int
    created_at: datetime
```

### SearchHit

```python
class SearchHit(BaseModel):
    artifact_id: str
    reference: str
    chunk_id: str | None = None
    text: str
    score: float
    retrieval_mode: RetrievalMode
    scrubbed: bool = True
    pii: PIIScrubSummary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### Replacement Payload

Default model-visible replacement should be stable and parseable.

```text
[stele]
reference: stele://<namespace>/<artifact_id>
content_type: <content_type>
bytes: <byte_size>
estimated_tokens: <token_estimate>
summary:
<scrubbed summary>

Available actions:
- fetch exact content by reference if needed
- search this artifact by reference for targeted details
- query namespace "<namespace>" for related stored context
[/stele]
```

No raw content beyond the scrubbed summary may appear in the replacement.

## Reference Format

### New Format

```text
stele://<namespace>/<artifact_id>?sig=<signature>&exp=<unix_seconds>
```

Rules:

- Namespace may contain slash-delimited path segments.
- Artifact id must be URL-safe.
- Query params are optional unless signing mode is `required`.
- Parser must validate and normalize references.

### Old Compatibility Format

```text
stele://<namespace>/<artifact_id>
```

Rules:

- Old refs parse into the same internal `Reference` model.
- Compatibility parser must not imply data exists.
- JSONL import can create new `stele://` references for imported artifacts.

## Configuration

### Minimal Memory Config

```yaml
backend:
  type: memory
summary:
  provider: lede
pii:
  enabled: true
```

### SQLite Config

```yaml
backend:
  type: sqlite
  path: .stele/stele.db
retrieval:
  default_mode: keyword
  keyword:
    enabled: true
indexing:
  mode: async
```

### Postgres With pg-raggraph Config

```yaml
backend:
  type: postgres
  dsn: postgresql://user:pass@localhost:5432/yonk
retrieval:
  default_mode: graph
  keyword:
    enabled: true
  vector:
    enabled: true
    provider: chunkshop
  graph:
    enabled: true
    provider: pg-raggraph
```

### ClickHouse Config

```yaml
backend:
  type: clickhouse
  dsn: clickhouse://default:@localhost:8123/yonk
retrieval:
  default_mode: vector
  keyword:
    enabled: false
  vector:
    enabled: true
    provider: chunkshop
ttl:
  cleanup_mode: backend_ttl
```

## Error Model

Required exceptions:

```python
class SteleError(Exception): ...
class ConfigError(SteleError): ...
class BackendError(SteleError): ...
class ArtifactNotFound(SteleError): ...
class CapabilityError(SteleError): ...
class ReferenceError(SteleError): ...
class SignatureError(ReferenceError): ...
class PIIBlockedError(SteleError): ...
class OptionalDependencyError(SteleError): ...
class IndexingError(SteleError): ...
```

Rules:

- Public API raises package-owned exceptions.
- Backend driver exceptions are chained but not exposed as the main exception type.
- Structured integrations return structured errors rather than raw stack traces.

## Security and Privacy Rules

- Raw content must not be logged.
- Raw content must not be included in metrics labels.
- Default summaries and search results must be scrubbed when PII is enabled.
- Raw fetch must require explicit API opt-in and config opt-in.
- Signed reference validation must use constant-time comparison.
- Reference signatures must cover namespace, artifact id, and expiration.
- Expired signed refs fail when signing mode is required.
- PII replacement tokens must be deterministic within one response but not necessarily globally stable.

## Observability

Required metrics:

- `stash_store_count`
- `stash_store_bytes`
- `stash_intercept_count`
- `stash_passthrough_count`
- `stash_fetch_count`
- `stash_search_count`
- `stash_query_count`
- `stash_index_submit_count`
- `stash_index_failure_count`
- `stash_pii_detection_count`
- `stash_pii_leak_fixture_count`
- latency histograms for store, summary, fetch, search, query, index, scrub

Required event fields:

- backend type
- namespace hash, not raw namespace when configured private
- content type
- byte size bucket
- token estimate bucket
- retrieval mode
- scrubbed bool
- raw bool
- success bool

## Acceptance Checklist

- Public API can be implemented from this spec without reading backend code.
- Replacement payload contains no raw large content.
- Exact fetch and retrieval are separate code paths.
- PII scrubbing is default-on for model-visible surfaces.
- Optional integrations do not affect core import.
- All public return values are package-owned Pydantic models or primitives.
