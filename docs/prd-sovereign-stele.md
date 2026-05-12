## TL;DR

Stele should become sovereign, source-backed memory infrastructure
for agents: exact local artifact storage, local memory extraction, local search,
and replaceable backend plugins. The product is not "Mem0 but local"; it is the
read/write/search API for agent knowledge where every memory can point back to
exact evidence and every non-sovereign dependency is optional.

# Product Requirements Document - Sovereign Stele

**Date:** 2026-05-12  
**Stage:** functional clean-room baseline, sovereign memory layer planned  
**Primary audience:** developers and platform teams building local or
self-hosted agents  
**Document status:** Review Ready

## 1. Product Definition

Stele is a sovereign memory and evidence layer for LLM agents. It
intercepts large or sensitive tool outputs, stores exact artifacts under
`stele://` references, returns scrubbed summaries/search results, and exposes
CRUD/search APIs for source-backed memories.

The system must support two knowledge streams through one API:

1. **Runtime agent knowledge:** facts, decisions, tool outputs, traces,
   observations, and memories collected while agents are working.
2. **Preemptive enterprise knowledge:** source-system knowledge collected before
   agents ask for it: tickets, CRM records, docs, file shares, databases, logs,
   source descriptors, and "where to look" metadata.

## 2. Problem Statement

Agent memory products remember useful facts, but they often lose or transform
the evidence behind those facts. Agent frameworks also pass large tool outputs
directly into the model before summarization, memory, or governance can help.

For sovereign deployments, teams need one local control plane that can:

- keep raw tool output out of the prompt by default
- preserve exact source artifacts
- extract durable memories locally
- search memories, artifacts, chunks, source catalogs, and living knowledge
- replace storage/search/memory backends without changing agent integrations
- prove quality, privacy, and token-reduction claims with reproducible
  benchmarks

## 3. Target Users

### Primary User: Agent Platform Engineer

Builds internal agent frameworks, coding agents, support agents, data agents, or
workflow agents. Needs a local memory API that is safe enough for production and
simple enough to wire into existing tools.

### Secondary User: Sovereign/Regulated Operator

Runs agents over sensitive data. Needs local storage, local embeddings, local
LLMs where used, no telemetry, explicit PII policy, auditable source references,
and clear deletion/retention semantics.

### Tertiary User: Enterprise Knowledge Engineer

Connects messy internal systems before agents ask questions. Needs connectors,
source catalogs, scheduled sync, chunk/vector indexing, and universal search
across memories plus source systems.

## 4. Core Value Proposition

**Stele stores the evidence, extracts the memory, and makes both
searchable locally.**

Compared with Mem0-style memory APIs, it adds exact source preservation,
sovereign deployment, and structural interception. Compared with RAG/vector
systems, it adds agent memory CRUD, policy, source-backed recall, and exact
artifact fetch. Compared with Pinecone Nexus-style knowledge engines, it is
local/self-hosted by default.

## 5. Product Principles

- **Sovereign first:** no hosted service is required for the default path.
- **Evidence first:** every extracted memory links to one or more `stele://`
  source references.
- **Exact fetch is non-negotiable:** retrieval can be approximate; artifact
  fetch cannot be.
- **Local by default:** summaries, PII scrubbing, extraction, indexing, and graph
  retrieval must have local options.
- **Composable, not captive:** external memory/search systems are adapters.
- **Honest claims:** benchmark reports must distinguish local evidence,
  external benchmarks, competitor baselines, and public claims.

## 6. Current Baseline

Implemented today:

- `Stele` facade for `store`, `fetch`, `search`, `query`, `list`,
  `delete`, `cleanup_expired`, `export_jsonl`, and `import_jsonl`
- `stele://` references
- exact artifact storage/fetch
- PII-scrubbed summaries, fetch output, and search results
- raw fetch gate through `pii.raw_fetch_enabled`
- structural tool-result interception wrapper
- `lede` summary provider
- memory, SQLite, Postgres, MariaDB, and ClickHouse backends
- Chunkshop-backed chunk indexing path with deterministic fallback
- JSONL migration/replay
- local benchmark evidence and Docker backend repeatability

Not complete yet:

- Mem0-like memory CRUD layer
- universal knowledge search
- source connector catalog
- pg-raggraph living knowledge adapter
- LangChain/MCP integrations
- external benchmark adapters and competitor baselines

## 7. Functional Requirements

### FR-1: Exact Artifact Storage

The system must store raw artifacts exactly and return them by reference.

Acceptance criteria:

- `store(content)` returns a compact result with reference, summary, metadata,
  token estimate, and index status.
- `fetch(reference, raw=True)` returns exact original content only when raw fetch
  is explicitly enabled.
- `fetch(reference)` defaults to policy-safe output.
- Storage contract passes across memory, SQLite, Postgres, MariaDB, and
  ClickHouse where configured.

### FR-2: Structural Interception

The system must replace oversized/sensitive tool outputs before model-visible
return.

Acceptance criteria:

- Oversized output is stored and replaced with scrubbed summary plus `stele://`
  reference.
- Below-threshold output passes through unchanged.
- Tool metadata, namespace, and session ID are preserved.
- LangChain and MCP integrations later expose the same behavior.

### FR-3: Sovereign Memory CRUD

The system must provide a local Mem0-like memory API.

Required API:

```python
memory.add(...)
memory.search(...)
memory.list(...)
memory.get(...)
memory.update(...)
memory.delete(...)
```

Acceptance criteria:

- Memory records support user/session/agent/app/namespace scope.
- Every record has `source_refs`.
- Records support `active`, `superseded`, `retracted`, `disputed`, and
  `deleted` states.
- Duplicate detection and supersession are available.
- Search supports scope filters, limit, freshness, and abstention thresholds.

### FR-4: Local Extraction

The system must extract memory candidates locally before any external adapter is
considered.

Acceptance criteria:

- Tier 1 deterministic extraction uses `lede` summary, key facts, stats,
  metadata, and regex PII flags.
- Tier 2 optional extraction uses only explicitly configured local
  OpenAI-compatible endpoints.
- Extraction output is candidate memory, not automatically trusted truth.
- Extraction reports include accepted/rejected counts, PII flags, source refs,
  model/prompt versions where applicable, and confidence.

### FR-5: Universal Search

The system must expose one search facade for agents.

Required route:

```text
search_knowledge(query, scope, freshness, privacy_mode, evidence_required)
```

Acceptance criteria:

- Searches memories, artifact metadata, artifact chunks, source descriptors, and
  living knowledge indexes where available.
- Returns normalized results with type, score, source refs, privacy flags,
  freshness/effective-time metadata, and follow-up action.
- Can return "known place to look" even when content is not fully indexed.
- Can abstain when no result meets evidence/confidence policy.

### FR-6: Backend Plugin System

The system must make storage, memory, retrieval, living-knowledge, and source
connectors replaceable.

Plugin types:

- `StorageBackend`
- `MemoryStore`
- `RetrievalIndex`
- `Revisor`
- `SourceConnector`

Acceptance criteria:

- Plugins implement protocols, not concrete internal subclasses.
- Plugins declare capabilities.
- Plugins pass contract tests.
- Policy engine routes based on capabilities, not product names.

### FR-7: Living Knowledge via pg-raggraph

When pg-raggraph is enabled, the system must support evolving knowledge.

Acceptance criteria:

- New evidence can supersede old evidence.
- Retracted evidence is hidden, flagged, or surfaced according to policy.
- `as_of` retrieves historical views.
- `version_filter` restricts results to a version family.
- Current search deprioritizes superseded/stale evidence.
- Every hit maps back to exact `stele://` evidence.

### FR-8: Source Catalog and Enterprise Connectors

The system must model enterprise knowledge sources separately from extracted
memories.

Acceptance criteria:

- `SourceDescriptor` tracks source type, owner, permissions, freshness,
  sync status, content types, query hints, and sample refs.
- Source connectors produce evidence records with provenance and permissions.
- Source connectors do not write directly to model-visible memory.
- Universal search can surface source descriptors as "where to look."

### FR-9: Privacy and Sovereignty

The default profile must work locally after installation/model-cache setup.

Acceptance criteria:

- No telemetry.
- No hosted API dependency in default path.
- PII fixtures do not leak through summaries, memories, search hits, or default
  fetch output.
- Model downloads are explicit setup steps, never hot-path side effects.
- External adapters declare `sovereign=false` or `network_required=true` when
  applicable.

## 8. Non-Functional Requirements

| Requirement | Target |
| --- | --- |
| Core install | Python 3.12+, lightweight dependencies only |
| Exact fetch accuracy | 1.0 across supported backends |
| PII leakage | zero leaks on configured fixtures |
| Local answer accuracy | >=90% judged task accuracy before public claim |
| Long-memory claims | require LongMemEval or LoCoMo adapter output |
| Raw fetch policy | blocked unless explicitly enabled |
| Deletion | backend semantics documented as immediate, async, or tombstone |
| Offline mode | works with network disabled after setup |
| Observability | no raw artifact logging by default |

## 9. Profiles and Packaging

### `sovereign-lite`

Memory or SQLite, `lede`, regex PII, keyword/FTS, deterministic memory
extraction, no embeddings, no local LLM.

### `sovereign-search`

SQLite or Postgres, Chunkshop vector indexing, local ONNX embeddings, memory
search plus artifact search.

### `sovereign-graph`

Postgres + pgvector, Chunkshop, pg-raggraph, local LLM or seeded entities.

### `sovereign-enterprise`

Source catalog, scheduled connectors, Chunkshop bakeoffs per source family,
universal search, permission metadata preservation.

### `adapter-mode`

Same public API with external `MemoryStore`, `RetrievalIndex`, or
`Revisor`. Not the default sovereign profile.

## 10. Success Metrics

### Product Metrics

- Time to first local memory search under 10 minutes from clean checkout.
- `search_first` or successor policy maintains >=90% judged answer accuracy with
  clear token/round-trip accounting.
- Every extracted memory has at least one source ref.
- Universal search returns relevant memory/artifact/source result for benchmark
  scenarios.
- External benchmark reports are generated reproducibly.

### Engineering Metrics

- Contract tests pass for every first-party backend.
- Plugin contract suite passes for example plugins.
- Offline verification test passes.
- No raw content in default logs.
- JSONL replay reproduces artifact sets across backends.

## 11. Out of Scope

- Replacing Letta/Mem0/Zep as full hosted memory platforms.
- Building a managed SaaS.
- Making pg-raggraph required for all deployments.
- Treating extracted memories as automatically true.
- Legal/trademark clearance for the final product name.
- Cloud connectors in the core package.

## 12. Roadmap

### Phase 1: Sovereign Memory Core

Add memory models, SQLite/Postgres memory store, CRUD/search API, source refs,
duplicate detection, supersession, and memory contract tests.

### Phase 2: Deterministic Extraction

Add `lede` key fact/stat/metadata extraction and candidate memory reports.

### Phase 3: Policy-Driven Recall

Turn answer workflow strategies into a local policy engine.

### Phase 4: Chunkshop Indexing

Wire production Chunkshop vector indexing and bakeoff-generated configs.

### Phase 5: pg-raggraph Living Knowledge

Add adapter tests and result models for supersession, retraction, `as_of`, and
version filters.

### Phase 6: Source Catalog and Universal Search

Add source descriptors, local file/JSONL/SQL connectors, and
`search_knowledge`.

### Phase 7: External Adapter SDK

Publish protocols and contract tests for third-party memory/search/index
plugins.

## 13. Naming Note

The working name is provisional. `memstash` is already an AI-agent memory product
with local SQLite, MCP, cloud sync, and self-hosting claims. Keep `stele://` for
now, but do package/domain/trademark checks before locking the final name.

## 14. Open Questions

- Should the public package remain `stele` or move to a less
  collision-prone name?
- Should universal search become its own product after it stabilizes?
- Which enterprise source connectors are first: files, SQL, Jira, Confluence,
  Slack, Salesforce, or S3-compatible stores?
- Should local LLM extraction be opt-in per namespace, per backend, or per
  profile?
- What is the minimum external benchmark set before a public release?

## Document Status

Review Ready. Metrics and current implementation status are based on
`docs/current-status.md` as of 2026-05-12. Validate naming and customer language
before external use.
