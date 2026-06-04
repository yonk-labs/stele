# Sovereign Memory System Plan

Date: 2026-05-12

## TL;DR

Build `stele` as a sovereign, componentized memory system where exact
artifact storage is the root of trust, local extraction/indexing produces useful
memories, and every higher-level memory/retrieval engine is replaceable behind an
adapter. The minimum Mem0-like surface is not "clone Mem0"; it is add/search/list/
update/delete durable memories with user/session/agent scopes, source
provenance, local extraction, conflict handling, and policy-controlled recall.

## North Star

The product should answer two different questions without conflating them:

1. **Artifact question:** What exact source did the agent see, avoid seeing, or
   retrieve from?
2. **Memory question:** What durable fact, preference, decision, or instruction
   should future agent work remember?

Stele owns the first question. The sovereign memory layer adds the second
question on top without losing source-backed evidence.

There are also two different knowledge streams:

1. **Runtime agent knowledge:** artifacts, decisions, observations, summaries,
   tool outputs, traces, and memories collected while agents are running.
2. **Preemptive enterprise knowledge:** messy source systems crawled or ingested
   before the agent asks: wikis, ticket systems, CRM, ERP, file shares,
   databases, logs, catalogs, source maps, and "where to look" metadata.

The API should let agents read/write both streams through one contract, but the
ingest mechanics should remain separate. Runtime capture is event-driven and
policy-gated. Enterprise source ingestion is connector-driven, scheduled, and
optimized for discovery/search.

## Non-Negotiables

- No hosted dependency in the default path.
- No network calls unless explicitly enabled.
- No telemetry.
- No raw artifact content in logs by default.
- No model downloads during the store/search hot path.
- Every extracted memory links back to one or more `stele://` source references.
- Exact artifact fetch remains independent from semantic, vector, graph, or LLM
  retrieval.
- External memory tools are adapters, not core dependencies.

## Component Model

```text
Tool output / conversation event
  -> Interception policy
  -> ArtifactStore
  -> PIIPolicy
  -> SummaryProvider
  -> MemoryExtractor
  -> MemoryStore
  -> RetrievalIndex
  -> Optional GraphIndex
  -> RecallPolicy
  -> Framework adapters
```

| Component | Default Sovereign Implementation | Replaceable With |
| --- | --- | --- |
| `ArtifactStore` | Memory, SQLite, Postgres, MariaDB, ClickHouse | S3-compatible local object store, enterprise DB |
| `SummaryProvider` | `lede` | local LLM summarizer, custom callable |
| `PIIPolicy` | regex scrubber, optional local Presidio/spaCy | enterprise DLP adapter |
| `MemoryExtractor` | deterministic rules + local LLM optional | Mem0, Zep, Letta, custom extractor |
| `MemoryStore` | SQLite/Postgres memory table | Mem0, Zep, MemPalace, Letta, Pinecone-style service |
| `RetrievalIndex` | keyword/FTS, Chunkshop + pgvector | Qdrant, LanceDB, Vespa, external vector DB |
| `GraphIndex` | pg-raggraph on self-hosted Postgres | Graphiti/Zep, Neo4j, disabled |
| `RecallPolicy` | local strategy selector | application-specific policy |
| `FrameworkAdapter` | Python wrapper, LangChain, MCP | CrewAI, LlamaIndex, OpenAI Agents SDK |
| `SourceConnector` | local files, JSONL, SQL tables, HTTP export folders | SharePoint, Slack, Jira, Confluence, Salesforce, S3-compatible stores |
| `UniversalSearch` | package-owned search facade over memories/artifacts/indexes | OpenSearch, Vespa, Pinecone Nexus-style service, enterprise search |

## Living Knowledge Base

When pg-raggraph is enabled, it should not be treated as just "better vector
search." Its job is the living knowledge base path: knowledge changes, newer
facts supersede older facts, retracted knowledge is hidden or flagged, and
version/time filters become first-class recall inputs.

pg-raggraph already has relevant capability signals in the sibling repo:

- `evolution_tier="structural"` for document-level evolving knowledge.
- `effective_from`, `effective_to`, `version_label`, `retracted`,
  `retracted_at`, `retraction_reason`, and `supersedes_document_id` metadata.
- `as_of` and `version_filter` query kwargs.
- `retracted_behavior` modes: `hide`, `flag`, `surface_both`.
- benchmark notes in its changelog: 13/13 version-filter purity on versioned
  Python docs and 15/15 on the medical HRT retraction/time-travel benchmark.

Stele should wrap that as a package-owned `Revisor`
capability instead of leaking pg-raggraph native objects.

### Revisor Contract

```python
class Revisor(Protocol):
    def ingest_evidence(self, evidence: EvidenceRecord) -> IndexReport: ...
    def search_current(self, query: KnowledgeQuery) -> list[KnowledgeHit]: ...
    def search_as_of(self, query: KnowledgeQuery, as_of: datetime) -> list[KnowledgeHit]: ...
    def supersede(self, old_ref: str, new_ref: str, reason: str | None = None) -> None: ...
    def retract(self, ref: str, reason: str, retracted_at: datetime | None = None) -> None: ...
```

### Verification Bar

Do not claim living-knowledge behavior until Stele verifies these through
its own adapter tests:

- new evidence can supersede old evidence
- superseded evidence is deprioritized or hidden according to policy
- retracted evidence is hidden, flagged, or surfaced alongside replacement
  evidence according to policy
- `as_of` queries can intentionally recover historical views
- `version_filter` returns only the requested version family
- every living-knowledge hit still maps back to exact `stele://` evidence

The first fixtures should mirror pg-raggraph's proven lanes:

- versioned software docs
- retracted medical/scientific claims
- enterprise policy updates
- customer/account state changes

## Minimum Mem0-Like Functionality

### Public Memory API

The first sovereign memory API should be intentionally small:

```python
memory.add(
    messages=[...],
    user_id="acme",
    agent_id="support-agent",
    session_id="ticket-123",
    source_refs=["stele://support/export-abc"],
    metadata={"customer": "acme"},
)

memory.search(
    query="what do we know about Acme SSO issues?",
    user_id="acme",
    limit=10,
)

memory.list(user_id="acme", agent_id=None, namespace=None)
memory.get(memory_id)
memory.update(memory_id, text=..., metadata=...)
memory.delete(memory_id)
```

### Required Data Model

```text
MemoryRecord
  id
  text
  kind: fact | preference | decision | instruction | commitment | issue | summary
  scope: user_id, agent_id, app_id, session_id, namespace
  source_refs: list[stele://...]
  source_chunk_ids: list[str]
  confidence
  status: active | superseded | retracted | disputed | deleted
  supersedes: list[memory_id]
  created_at
  updated_at
  effective_from
  effective_until
  metadata
  pii_flags
```

### Evolution Boundary: Artifacts Are Immutable, Memories Evolve

The product has only one supersession system, and it lives on memories — not
on artifacts.

- **Artifacts are immutable evidence.** An artifact captured what was true at
  capture time. It is never marked superseded or retracted. Artifacts can be
  deleted under retention/TTL policy or replaced by a re-stored copy with a new
  `stele://` reference, but they do not carry `supersedes`, `effective_from`,
  `effective_until`, or `retracted` columns.
- **Memories carry the evolution semantics.** A memory's `supersedes`,
  `status`, `effective_from`, and `effective_until` fields are the *only* place
  the system records "this fact replaced that fact."
- **The `Revisor` is a projection.** When pg-raggraph is enabled,
  evolution columns on its document/chunk rows mirror the memory's evolution
  state so graph queries can honor `as_of` and `retracted_behavior`. The memory
  record is the source of truth; the graph rows are derived.

This boundary is the reason the public contract can stay capability-honest on
backends without living-knowledge support: a SQLite-only deployment can carry
memory evolution semantics in the memory table and skip the graph projection
entirely. The artifact layer never has to know.

### Required Behaviors

- Add memories from messages, artifacts, summaries, or explicit user calls.
- Search memories by query plus scope filters.
- Retrieve source evidence for every memory.
- Detect obvious duplicate memories.
- Mark stale memories as superseded instead of overwriting history.
- Support abstention when no memory is relevant enough.
- Keep raw artifact storage separate from memory text.
- Enforce PII policy before memory text becomes model-visible.

## Backend Plugin System

This may become a separate product later, but the core needs the seam now.
Stele should be the read/write/CRUD API for agent knowledge; backend
plugins should decide where data lives and how it is searched.

The plugin system should cover five extension categories:

| Plugin Type | Purpose | Examples |
| --- | --- | --- |
| `StorageBackend` | exact artifacts and durable records | memory, SQLite, Postgres, MariaDB, ClickHouse |
| `MemoryStore` | durable extracted memories | local SQLite/Postgres, Mem0 adapter, Letta adapter |
| `RetrievalIndex` | artifact/chunk search | keyword, SQLite FTS, Chunkshop, Qdrant, Vespa |
| `Revisor` | evolving knowledge, supersession, retractions | pg-raggraph, Graphiti/Zep adapter |
| `SourceConnector` | preemptive enterprise ingestion | SQL tables, files, S3, Jira, Confluence, Slack |

### Plugin Packaging

Keep core small:

```text
stele                 # core API, memory backend, lede, regex PII
stele-core[sqlite]         # durable local default
stele-core[postgres]       # exact Postgres + FTS
stele-core[chunkshop]      # vector indexing adapter
stele-core[pgraggraph]     # living knowledge adapter
stele-core[connectors]     # optional source connectors
```

Later, support third-party packages:

```text
memory-stash-qdrant
memory-stash-vespa
memory-stash-lettermemory
memory-stash-source-jira
memory-stash-source-confluence
```

Do not require plugin authors to subclass concrete internals. They should
implement protocols, declare capabilities, and pass a contract test suite.

### Capability Declaration

Every backend/index/store plugin should report:

```text
exact_fetch
keyword_search
vector_search
graph_search
living_knowledge
delete_semantics: immediate | async | tombstone_only
pii_enforcement: none | model_visible_only | storage_level
sovereign: true | false
network_required: true | false
```

This lets the policy engine choose a safe route without hard-coding product
names.

## Extraction Pipeline

### Tier 1: Deterministic Local Extraction

Use this by default.

- `lede.summary`
- `lede.key_facts`
- `lede.stats`
- `lede.metadata`
- regex PII flags
- simple classifiers for `fact`, `decision`, `preference`, `commitment`,
  `instruction`, and `issue`

This gives useful memory candidates without a local LLM.

### Tier 2: Local LLM Extraction

Optional, configured explicitly.

- OpenAI-compatible local endpoint only: Ollama, vLLM, llama.cpp, LM Studio.
- Extract structured memory candidates from summaries/chunks, not raw giant
  artifacts unless policy allows.
- Require JSON schema output.
- Store extraction prompt/model/version in metadata for auditability.

### Tier 3: Graph-Enriched Extraction

Optional Postgres excellence path.

- Chunkshop indexes artifact chunks.
- pg-raggraph extracts entities and relationships through a local endpoint or
  caller-seeded known entities.
- Memory records link to graph entities and source chunks.
- Recall can combine memory similarity, keyword evidence, and graph adjacency.

## Chunkshop Role

Chunkshop should be the indexing pipeline, not the memory API.

Use it to:

- frame messy artifacts into documents
- chunk documents with corpus-appropriate strategies
- embed local vectors with ONNX/fastembed
- attach extractor tags/metadata
- write `original_content`, `embedded_content`, tags, metadata, and embeddings
  to pgvector
- run bakeoffs so retrieval recipes are evidence-based per corpus

The Stele adapter should map every Chunkshop row back to:

- artifact reference
- chunk id
- namespace
- session/user/project metadata
- PII policy state

Chunkshop also matters for preemptive enterprise knowledge. Source connectors
should feed enterprise data into Chunkshop cells, run bakeoffs per corpus, and
write indexed rows with source provenance. Runtime agent artifacts and
preemptively ingested enterprise data can then be searched through the same
package-owned `UniversalSearch` facade even though their ingestion paths differ.

## pg-raggraph Role

pg-raggraph should be the optional graph retrieval provider for self-hosted
Postgres.

Use it for:

- multi-hop relationship retrieval
- time/version-aware retrieval
- source provenance trails
- graph reranking over Chunkshop chunks

Do not make it required for:

- exact fetch
- basic memory add/search
- SQLite deployments
- non-Postgres backends

When enabled, pg-raggraph should own evolving-knowledge retrieval, not raw CRUD.
Stele remains the API and source-of-truth reference layer; pg-raggraph is
the living search/index sidecar.

## Replaceable Adapter Contracts

### MemoryExtractor

```python
class MemoryExtractor(Protocol):
    def extract(self, event: MemoryExtractionInput) -> list[MemoryCandidate]: ...
```

Inputs include summary, selected chunks, source refs, metadata, and optional
messages. Outputs are candidates, not committed memories.

### MemoryStore

```python
class MemoryStore(Protocol):
    def add(self, records: list[MemoryRecord]) -> list[MemoryRecord]: ...
    def search(self, query: MemoryQuery) -> list[MemoryHit]: ...
    def list(self, filters: MemoryFilters) -> Page[MemoryRecord]: ...
    def update(self, memory_id: str, patch: MemoryPatch) -> MemoryRecord: ...
    def delete(self, memory_id: str) -> None: ...
```

Mem0, Zep, Letta, MemPalace, or a future Pinecone-style managed layer should be
able to implement this without changing the public `Stele` facade.

### RetrievalIndex

```python
class RetrievalIndex(Protocol):
    def index_artifact(self, artifact: ArtifactRecord) -> IndexReport: ...
    def search(self, query: RetrievalQuery) -> list[SearchHit]: ...
    def delete_artifact(self, reference: str) -> None: ...
```

Chunkshop is one implementation. A direct SQLite FTS implementation and keyword
memory implementation remain valid lower-tier implementations.

### SourceConnector

```python
class SourceConnector(Protocol):
    def discover(self) -> list[SourceDescriptor]: ...
    def sync(self, cursor: SyncCursor | None = None) -> SyncReport: ...
```

Source connectors are for preemptive enterprise knowledge. They should produce
`EvidenceRecord` objects with source provenance, timestamps, permissions, and
content-type metadata. They should not write directly to model-visible memory.

### UniversalSearch

For v1, `UniversalSearch` is an **internal facade with a single
implementation**, not a plugin point. It exposes one method shape:

```python
def search(query: SearchRequest) -> SearchResponse: ...
```

It is deliberately not declared as a `Protocol` yet. A plugin seam should be
introduced only when a second concrete implementation actually exists (for
example, an enterprise search backend or OpenSearch federation). Declaring the
contract before a second implementation locks the shape on a guess and forces
every later implementer to live with it.

The facade should federate:

- extracted memories
- exact artifact metadata
- artifact chunks
- enterprise source descriptors
- graph/living-knowledge hits

It should return one normalized result shape with:

- result type: memory | artifact | chunk | entity | source | connector
- score and score components
- source refs
- privacy flags
- freshness/effective-time metadata
- required follow-up action, if any

## Is Universal Search Required?

Yes, but it should start as an internal facade, not a separate product.

The reason is practical: agents do not know whether the answer lives in a
durable memory, a raw artifact, a chunk index, a graph entity, or a source
catalog entry saying "look in Salesforce account notes." If the agent has to
choose among five tools, recall becomes brittle. A universal search facade gives
the agent one tool:

```text
search_knowledge(query, scope, freshness, privacy_mode, evidence_required)
```

The facade can route internally:

1. Search high-confidence memories.
2. Search artifact metadata.
3. Search chunk indexes.
4. Search living graph/evolution index if enabled.
5. Search source catalog / connector descriptors.
6. Return abstention or "known place to look" when content is not yet indexed.

Keep it inside this product until it has independent gravity. Split it only if
other projects want the same universal search layer without artifact storage or
memory CRUD.

## Preemptive Enterprise Knowledge

The system needs a source catalog, not just a memory table.

```text
SourceDescriptor
  source_id
  type: sql | file_share | ticketing | crm | wiki | object_store | api
  name
  description
  owner
  permissions_ref   # opaque caller-honored value; not enforced by v1
  freshness
  sync_status
  content_types
  query_hints
  sample_refs
  connector_config_ref
```

**v1 permission scope:** `permissions_ref` is an opaque string the caller is
expected to honor at query time. The system does not parse, model, or enforce
source-side permission systems. Multi-tenant permission enforcement
(per-user/per-group filtering of source content) is out of scope for v1 and
will land in a later phase. See `sovereign-enterprise` profile.

This gives agents useful answers even before all content is indexed:

- "There is a Jira project for customer escalations."
- "Salesforce has account notes, but this user lacks permission."
- "The policy wiki was last synced two days ago."
- "The raw source exists, but only metadata is indexed."

That is the bridge between a memory system and an enterprise knowledge system.

## Recall Policy

Current local benchmark evidence says `search_first` is the cheapest
high-accuracy strategy on the local scenario set. Convert that into a policy
engine instead of hard-coding a single behavior.

Policy inputs:

- query type
- content type
- summary confidence
- memory hit score
- retrieval hit score
- PII risk
- token budget
- source freshness
- backend capability

Policy outputs:

- summary only
- memory search
- artifact search
- graph search
- raw fetch allowed/denied
- abstain

## Sovereign Profiles

Every profile must satisfy the sovereignty bar (no required network call after
install/model-cache setup). Profiles differ in which extraction tier they
imply and which model assets the user has to pre-stage. The table below
reconciles each profile with the extraction tiers defined in *Extraction
Pipeline*.

| Profile | Extraction tier | Local LLM required? | Embeddings? | Network at runtime? |
| --- | --- | --- | --- | --- |
| `sovereign-lite` | Tier 1 only | no | no | no |
| `sovereign-search` | Tier 1, optional Tier 2 | optional | local ONNX | no |
| `sovereign-graph` | Tier 1 + Tier 3 | yes (or caller-seeded entities) | local ONNX | no |
| `sovereign-enterprise` | Tier 1 + Tier 3 + source connectors | yes (or caller-seeded entities) | local ONNX | yes, only to configured source systems |
| `adapter-mode` | depends on adapter | depends on adapter | depends on adapter | depends on adapter |

### `sovereign-lite`

- Memory or SQLite backend.
- `lede` summaries.
- regex PII.
- keyword/FTS retrieval.
- Tier 1 deterministic memory extraction only.
- no embeddings, no local LLM, no model cache required.

### `sovereign-search`

- SQLite or Postgres backend.
- Chunkshop vector indexing with local ONNX embeddings.
- Tier 1 deterministic extraction by default; Tier 2 local-LLM extraction
  optional if a local OpenAI-compatible endpoint is configured.
- local extractor tags.
- memory search plus artifact search.

### `sovereign-graph`

- Postgres + pgvector.
- Chunkshop indexing.
- pg-raggraph graph retrieval.
- Tier 3 graph-enriched extraction: requires a local LLM endpoint **or**
  caller-seeded known entities. There is no third path.

### `sovereign-enterprise`

- source catalog enabled.
- local/source-controlled connectors.
- scheduled sync jobs.
- Chunkshop bakeoff per source family.
- universal search across memories, artifacts, chunks, graph hits, and source
  descriptors.
- Tier 3 extraction with the same local-LLM-or-seeded-entities requirement as
  `sovereign-graph`.
- **Permissions scope (v1):** `SourceDescriptor.permissions_ref` is stored as
  an opaque caller-honored value. The system does not model or enforce source
  permission systems (Confluence ACLs, Salesforce sharing rules, etc.). Multi-
  tenant permission enforcement is out of scope until a later phase; callers
  are responsible for honoring `permissions_ref` at query time. Do not market
  this profile as multi-tenant-safe until enforcement lands.
- Network access at runtime is permitted **only** to explicitly configured
  source systems. No other network path is enabled by the profile.

### `adapter-mode`

- Same public API.
- External `MemoryStore`, `RetrievalIndex`, or `GraphIndex` adapter.
- Explicitly not a sovereign profile: the chosen adapter may itself make
  network calls or send telemetry. Sovereignty bar does not apply.

## Build Phases

### Phase 1: Sovereign Memory Core

- Add `MemoryRecord`, `MemoryCandidate`, `MemoryHit`, and memory filter models.
- Add local SQLite/Postgres memory tables.
- Add `memory.add/search/list/get/update/delete`.
- Add source-ref provenance to every memory.
- Add duplicate detection and supersession.
- Add memory contract tests.

### Phase 2: Deterministic Extraction

- Add `lede` extraction path for key facts/stats/metadata.
- Add simple memory-kind classifier.
- Add extraction reports with candidate count, accepted count, rejected count,
  PII flags, and source refs.
- Add fixtures for preferences, decisions, commitments, changed facts, and
  abstention.

### Phase 3: Policy-Driven Recall

- Add `RecallPolicy`.
- Implement summary-only, memory-search, artifact-search, graph-search,
  adaptive, raw-fetch, and abstain strategy outputs.
- Promote the answer workflow benchmark into a policy regression suite.

### Phase 4: Chunkshop Indexing

- Build a Chunkshop `RetrievalIndex` adapter.
- Map Chunkshop rows to Stele chunk ids.
- Add vector retrieval where backend supports it.
- Add bakeoff-generated recommended config support.

### Phase 5: pg-raggraph Postgres Excellence + Living Knowledge Verification

This is one phase, not two. Wiring pg-raggraph and proving it actually delivers
living-knowledge semantics is the same chunk of work; splitting them risks
shipping the adapter as "better vector search" without the headline feature
ever being verified.

- Add pg-raggraph `GraphIndex` adapter.
- Support local LLM endpoint and seeded-entity modes.
- Add source-backed graph hits as package-owned `SearchHit`/`MemoryHit` objects.
- Add package-owned `Revisor` result models.
- Add adapter tests for supersession, retraction, version filters, and `as_of`.
- Add benchmark rows for current-vs-historical recall and stale-memory error
  rate.

**Exit gate:** the Living Knowledge Verification bar (see *Living Knowledge
Base* section) passes before any later phase ships. No public claim of
living-knowledge behavior before this gate is met.

### Phase 6: External Adapter SDK

- Publish adapter protocols.
- Add example external-memory adapter using a fake in-memory store.
- Later optional adapters: Mem0, Zep/Graphiti, Letta, MemPalace, Pinecone Nexus
  if users accept non-sovereign dependencies.

### Phase 7: Source Catalog and Universal Search

- Add `SourceDescriptor`, `SourceConnector`, and `SyncReport` models.
- Add local file/JSONL/SQL source connectors first.
- Add `UniversalSearch` facade over memory/artifact/chunk/source search.
- Add an MCP tool and Python API for `search_knowledge`.

### Phase 8: Plugin SDK Productization

Plugin contracts (`StorageBackend`, `MemoryStore`, `RetrievalIndex`,
`Revisor`, `SourceConnector`) are committed from Phase 1 onward.
This phase is the decision about whether to extract them into a separate
publishable SDK, not whether plugins exist at all.

- Keep backend plugins inside Stele until at least three external plugin
  use cases exist.
- Split into a separate plugin SDK only if non-Memory-Stash projects need the
  same protocols and contract tests.

## Benchmark Bar

Minimum before claiming "Mem0-like":

- LongMemEval adapter runs locally.
- LoCoMo adapter runs locally.
- local answer workflow benchmark remains >=90% judged accuracy.
- stale-memory error rate is reported.
- abstention accuracy is reported.
- every answer/memory can cite `stele://` source refs.
- no PII fixture leaks through memory text, summaries, search hits, or fetch
  output.

Minimum before claiming "sovereign":

- all required paths run with network disabled after install/model-cache setup.
- local model cache can be pre-populated.
- no cloud service is required for add/search/extract/index/fetch.
- telemetry is absent or provably disabled.

## Product Positioning

Do not say: "We are Mem0 but local."

Say: "Stele is sovereign, source-backed memory infrastructure. It stores
the evidence, extracts durable memories locally, indexes artifacts locally, and
lets teams swap in any external memory service if they choose."

## Naming Check

The current name should stay provisional.

Signals checked on 2026-05-12:

- `memstash` is already an AI-agent memory product with local SQLite, MCP,
  cloud sync, and self-hosting claims.
- Search results did not show a clear exact `stele` collision, but
  package/domain/trademark availability still needs direct registry checks.
- "Stele" describes the product, but it is close enough to `memstash` to
  create confusion in the agent-memory category.

Recommendation:

- Keep `stele://` references for now; they are short and product-neutral.
- Keep the Python package name provisional until registry checks are complete.
- Consider names that emphasize sovereignty/evidence rather than generic memory:
  `Sovereign Stash`, `Evidence Stash`, `Yonk Stash`, `Source Memory`,
  `Artifact Memory`, `Stashbase`, or `Yonk Knowledge Stash`.
