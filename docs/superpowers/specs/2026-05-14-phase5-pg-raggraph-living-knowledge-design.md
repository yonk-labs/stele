---
phase: 5
title: pg-raggraph Postgres Excellence + Living Knowledge Verification
created: 2026-05-14
status: design-approved
location: out-of-tree (/tmp/stele-phase5-planning/) per user instruction; not committed to git
depends-on: |
  Phase 1 complete (memory + supersession + as_of on memory/sqlite/postgres).
  Phase 2 complete (deterministic extraction layer).
  Phase 3 complete (recall facade with graph_search CapabilityError stub).
  Phase 4 complete (chunk_store + vector + hybrid + ChunkshopRetrievalAdapter).
external-deps: |
  pg_raggraph >= X.Y (optional extra; user's release with the capability signals
  documented in docs/sovereign-memory-system-plan.md:88-96). Backend extra name:
  `[postgres-graph]`. Independent of `[postgres]` so users opt in explicitly.
---

# Phase 5: pg-raggraph Postgres Excellence + Living Knowledge Verification — Design

## TL;DR

Phase 5 ships the production pg-raggraph adapter that completes Phase 3's
`graph_search` stub and proves Stele's "living knowledge" claim. The internal
`Revisor` Protocol owns the projection from Stele's memory + artifact layer
into pg-raggraph's graph. `Stele.memory.add(supersedes=)`, new
`Stele.memory.retract()`, and `Stele.store()` all project to the Revisor when
pg-raggraph is configured. `Stele.recall(strategy="graph_search", as_of=,
version_filter=, retracted_behavior=)` becomes a real strategy. The Revisor is
**never** publicly exposed — pg-raggraph stays a Postgres-only implementation
detail, gated by `OptionalDependencyError` and lazy imports.

Two fixture lanes (versioned software docs + retracted medical/scientific
claims) prove the six-bullet verification bar in full. Phase 5 is the **exit
gate** for the public "living knowledge" claim.

## The Six Headline Proofs (the verification bar)

Phase 5 ships nothing publicly claimed as "living knowledge" unless all six
pass on both fixture lanes:

1. **Supersession works.** New evidence ingested via
   `Memory.add(supersedes=[old_id])` causes `graph_search` to deprioritize /
   hide the old evidence per policy.
2. **Retraction works.** `Memory.retract(memory_id, reason)` causes the
   retracted hit to be hidden (default), flagged, or surfaced-both per
   `retracted_behavior`.
3. **`as_of` recovers history.** `Stele.recall(strategy="graph_search",
   as_of=T0)` returns the snapshot of knowledge that was current at `T0` —
   including superseded evidence if it was active then.
4. **`version_filter` is exact.** `Stele.recall(strategy="graph_search",
   version_filter="v2")` returns only hits tagged with version `v2`; no
   cross-version bleed.
5. **`stele://` provenance is mandatory.** Every `KnowledgeHit` carries a
   `stele://` reference back to its originating artifact or memory. Hits
   without provenance never reach the recall layer.
6. **Non-Postgres baseline is unaffected.** Non-Postgres backends never
   import `pg_raggraph` even at module level (verified by an architectural
   import-check). Postgres baseline works *without* pg-raggraph installed.

## Locked Architectural Decisions

1. **Revisor is internal.** No public namespace on `Stele`. Public write
   surface stays on `Stele.memory` (`add(supersedes=)`, new `retract()`).
   Public read surface stays on `Stele.recall(strategy="graph_search", ...)`
   with new fields `as_of`, `version_filter`, `retracted_behavior`.
2. **Unified `EvidenceRecord`.** Wraps both `ArtifactRecord` and
   `MemoryRecord` via a `kind` discriminator. Both `Stele.store()` and
   `Memory.add()` project to the Revisor when configured.
3. **Seeded-entity default; LLM mode opt-in.** Default is deterministic —
   caller supplies entities + relations via `EvidenceRecord.entities` /
   `relations`. LLM mode is configured via `indexing.pg_raggraph.llm:
   LLMEndpointConfig` (OpenAI-compatible endpoint).
4. **Two fixture lanes for full verification.** Versioned software docs +
   retracted medical claims. Enterprise policy + customer state lanes are
   Phase 5.5.
5. **Default `retracted_behavior = "hide"`.** Retracted evidence does not
   appear by default. `flag` and `surface_both` are opt-in.
6. **Architecture: Phase 4-style Protocol pattern.** `Revisor` Protocol +
   `NoOpRevisor` + `PgRaggraphRevisor` under `src/stele/revisor/`. NoOp
   eliminates projection guards at every call site.
7. **Best-effort projection on writes; hard-fail on reads.** Memory + artifact
   writes are durable in SQL; Revisor projection failure logs at WARN but
   does not abort the user's call. `graph_search` read failures surface as
   `BackendError` — silent fallback would mask a misconfigured graph.
8. **`as_of` works two ways.** `Memory.search(as_of=)` keeps its Phase 1 SQL
   semantics (memories active at `T0`). `Stele.recall(graph_search, as_of=)`
   adds graph-aware semantics (entity-relation graph state at `T0`,
   includes artifacts not yet memorized).

## Public API

Phase 5 does not add a new top-level namespace. It activates Phase 3's
`graph_search` stub and extends three existing surfaces.

### `Stele.recall(strategy="graph_search", ...)` activates

Phase 3 left this raising `CapabilityError("graph_search requires Phase 5
pg-raggraph adapter")`. Phase 5 replaces the body. The `RecallRequest`
model gains three fields:

```python
class RecallRequest(BaseModel):
    # existing Phase 3 fields...
    as_of: datetime | None = None
    version_filter: str | None = None
    retracted_behavior: Literal["hide", "flag", "surface_both"] | None = None
```

When pg_raggraph isn't installed OR backend isn't Postgres OR
`indexing.pg_raggraph.enabled=False`, `graph_search` continues to raise
`CapabilityError`. The `adaptive` strategy gracefully skips the
`graph_search` tier on `CapabilityError`, recording
`Escalation(strategy="graph_search", reason="capability_error")` and
continuing the tier order — does NOT abort the adaptive run.

### `Stele.memory.retract(memory_id, *, reason, retracted_at=None)` is new

```python
def retract(
    self,
    memory_id: str,
    *,
    reason: str,
    retracted_at: datetime | None = None,
) -> MemoryRecord: ...
```

- Sets `MemoryRecord.status="retracted"`, stores
  `metadata["retraction_reason"]` and `metadata["retracted_at"]`.
- When pg-raggraph is configured, projects to `Revisor.retract(reference,
  reason, retracted_at)` after the SQL write succeeds.

### `Stele.memory.add(supersedes=[...])` gets projection

Existing API unchanged. When `supersedes` is non-empty and pg-raggraph is
configured, the call projects to `Revisor.supersede(old_ref, new_ref,
reason)` for each entry after the SQL write succeeds.

### `Stele.store(...)` gets projection

Existing API unchanged. When pg-raggraph is configured, every successful
store projects an `EvidenceRecord(kind="artifact", ...)` to
`Revisor.ingest_evidence(...)`.

### Public types added

```python
class EvidenceRecord(BaseModel):
    kind: Literal["artifact", "memory"]
    reference: str
    text: str
    namespace: str
    session_id: str | None = None
    effective_from: datetime
    effective_until: datetime | None = None
    version_label: str | None = None
    supersedes: list[str] = []
    retracted: bool = False
    retracted_at: datetime | None = None
    retraction_reason: str | None = None
    metadata: dict[str, object] = {}
    entities: list[EntitySeed] = []
    relations: list[RelationSeed] = []


class EntitySeed(BaseModel):
    name: str
    type: str | None = None
    metadata: dict[str, object] = {}


class RelationSeed(BaseModel):
    head: str
    tail: str
    type: str
    metadata: dict[str, object] = {}


class KnowledgeHit(BaseModel):
    reference: str
    kind: Literal["artifact", "memory"]
    text: str
    score: float
    effective_from: datetime
    effective_until: datetime | None = None
    version_label: str | None = None
    retracted: bool = False
    metadata: dict[str, object] = {}


class IndexReport(BaseModel):
    evidence_count: int
    entity_count: int
    relation_count: int
    skipped: int
    failed: int
    failures: list[dict[str, str]] = []
```

All re-exported from `stele.*`.

## File Layout

### New files

| Path | Responsibility |
|---|---|
| `src/stele/revisor/__init__.py` | Re-exports public types |
| `src/stele/revisor/models.py` | All pydantic models |
| `src/stele/revisor/base.py` | `Revisor` Protocol + `RetractedBehavior` literal + `KnowledgeQuery` dataclass |
| `src/stele/revisor/noop.py` | `NoOpRevisor` — ingest no-op; search raises CapabilityError; supersede/retract no-op |
| `src/stele/revisor/pg_raggraph.py` | `PgRaggraphRevisor` — lazy-imports pg_raggraph; full implementation |
| `src/stele/revisor/llm_endpoint.py` | `LLMEndpointConfig` + OpenAI-compat client (mirrors `OpenAICompatAnswerer`) |
| `src/stele/revisor/projection.py` | Memory→EvidenceRecord, Artifact→EvidenceRecord, KnowledgeHit→Citation translations + PII assertion |
| `src/stele/retrieval/graph.py` | `graph_search(revisor, query, *, as_of, version_filter, retracted_behavior, limit)` facade |
| `tests/unit/revisor/__init__.py` | Package marker |
| `tests/unit/revisor/test_models.py` | Model validation |
| `tests/unit/revisor/test_projection.py` | Translations + PII assertion |
| `tests/unit/revisor/test_noop.py` | NoOp Protocol conformance |
| `tests/unit/revisor/test_pg_raggraph.py` | Adapter unit (skip when pg_raggraph missing) |
| `tests/unit/revisor/test_llm_endpoint.py` | LLM client surface |
| `tests/unit/revisor/test_architecture.py` | Import-layer check |
| `tests/unit/recall/test_graph_search_real.py` | Phase 3 stub becomes real |
| `tests/unit/recall/test_recall_request_phase5_fields.py` | New RecallRequest fields |
| `tests/unit/recall/test_adaptive_with_graph_search.py` | Adaptive skip on CapabilityError |
| `tests/integration/pg_raggraph/test_supersession.py` | **Bar #1** |
| `tests/integration/pg_raggraph/test_retraction.py` | **Bar #2** |
| `tests/integration/pg_raggraph/test_as_of.py` | **Bar #3** |
| `tests/integration/pg_raggraph/test_version_filter.py` | **Bar #4** |
| `tests/integration/pg_raggraph/test_provenance.py` | **Bar #5** |
| `tests/integration/pg_raggraph/test_postgres_baseline_without_pg_raggraph.py` | **Bar #6** |
| `tests/contract/test_graph_search_contract.py` | Cross-fixture-lane contract (Postgres only) |
| `tests/fixtures/pg_raggraph/versioned_docs.json` | Lane 1 fixtures |
| `tests/fixtures/pg_raggraph/retracted_medical.json` | Lane 2 fixtures |
| `benchmarks/living_knowledge.py` | Benchmark: current/historical recall + stale-memory error rate |
| `tests/benchmarks_smoke/test_living_knowledge_benchmark.py` | Benchmark smoke |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | Add `[postgres-graph]` extra: `pg_raggraph>=X.Y` |
| `src/stele/core/config.py` | Add `PgRaggraphConfig` + `LLMEndpointConfig`; field `IndexingConfig.pg_raggraph` |
| `src/stele/core/memory.py` | Add `Memory.retract()`; project `add(supersedes=)` and `retract()` to Revisor |
| `src/stele/core/stash.py` | Build `self._revisor` at init; project `Stele.store()` on success; capabilities expansion; close wire-up |
| `src/stele/core/artifact.py` | `Capabilities` adds pg_raggraph + revisor + LLM fields |
| `src/stele/recall/graph_search.py` | Real implementation replaces Phase 3's CapabilityError stub |
| `src/stele/recall/models.py` | RecallRequest gains as_of / version_filter / retracted_behavior |
| `src/stele/recall/adaptive.py` | Catch CapabilityError on graph tier; record `Escalation(reason="capability_error")`; continue |
| `src/stele/recall/facade.py` | Pass new fields through canonical entry + graph_search shim |
| `src/stele/__init__.py` | Re-export Phase 5 public types |

### Untouched (locked)

| Path | Why locked |
|---|---|
| `src/stele/extraction/*` | Phase 2 |
| `src/stele/storage/{memory,sqlite,mariadb,clickhouse}.py` (artifact stores) | Non-Postgres never touches pg_raggraph |
| `src/stele/storage/chunk_store/*` | Phase 4; vector retrieval is independent of graph |
| `src/stele/retrieval/{memory,sqlite,mariadb,clickhouse}.py` | Non-Postgres retrieval untouched |
| `src/stele/pii/*` | Consumed; assertion at projection boundary |
| `src/stele/storage/memory_store/*` | Phase 1 |
| `src/stele/storage/postgres.py` (artifact store) | Exact CRUD on the artifact table, not pg-raggraph (per spec) |

## Data Flow

### Ingestion write path (Stele.store)

```
CALLER
   │ stele.store(data="...", namespace="default")
   ▼
Stele.store(...)
   │ existing Phase 1 path: store artifact + PII-scrub summary
   ▼
SUCCESS: ArtifactRecord persisted to Postgres
   │
   │ if pg_raggraph configured (revisor != NoOp):
   ▼
projection.artifact_to_evidence(artifact) → EvidenceRecord(kind="artifact", ...)
   │
   │ entity_mode:
   │   ┌── "seeded": evidence already carries entities/relations (or empty)
   │   └── "llm":    LLMEndpointConfig client extracts entities/relations from text
   ▼
revisor.ingest_evidence(evidence) → IndexReport
   │
   │ Best-effort: log on failure; do NOT roll back the artifact write.
   ▼
return StoredResult (unchanged)
```

### Memory write path (Memory.add / Memory.retract)

```
CALLER
   │ stele.memory.add(text="...", supersedes=[old_id], ...) OR
   │ stele.memory.retract(memory_id="...", reason="...")
   ▼
Memory.{add,retract}(...)
   │ existing Phase 1 path: SQL write + PII scrub
   ▼
SUCCESS: SQL state correct (memory is source of truth)
   │
   │ if pg_raggraph configured:
   ▼
projection.memory_to_evidence(memory) → EvidenceRecord(kind="memory", ...)
   │
   ▼
revisor.{ingest_evidence | supersede | retract}(...)
   │
   │ For add(supersedes=[old_ids]):
   │   1. revisor.ingest_evidence(new_evidence)
   │   2. for old_ref in old_refs: revisor.supersede(old_ref, new_ref, reason)
   │ For retract:
   │   1. revisor.retract(reference, reason, retracted_at)
   │
   │ Best-effort: log on failure.
   ▼
return MemoryAddResult / MemoryRecord
```

### Graph search read path (Stele.recall(strategy="graph_search"))

```
CALLER
   │ stele.recall(query="...", scope=..., strategy="graph_search",
   │              as_of=None, version_filter=None, retracted_behavior=None)
   ▼
Recall facade → GraphSearchStrategy
   │
   │ if revisor.is_noop or not configured for graph_search:
   │    raise CapabilityError("graph_search requires pg-raggraph...")
   ▼
GraphSearchStrategy.execute(request, deps)
   │
   │ build KnowledgeQuery(
   │     text=request.query,
   │     scope=request.scope,
   │     limit=request.max_artifact_hits + request.max_memory_hits,
   │     version_filter=request.version_filter,
   │     retracted_behavior=request.retracted_behavior or config.default,
   │ )
   ▼
if request.as_of is not None:
    hits = revisor.search_as_of(query, as_of=request.as_of)
else:
    hits = revisor.search_current(query)
   │
   ▼
projection.knowledge_hits_to_citations(hits) → list[Citation]
   │ (every hit asserted to carry stele:// reference; PII-scrubbed snippet)
   ▼
return RecallResult(strategy_used="graph_search", citations=..., ...)
```

### Adaptive integration

```
AdaptiveStrategy iterates tier_order:
   1. memory_search   → tier_complete? stop.
   2. artifact_search → tier_complete? stop.
   3. graph_search    → if CapabilityError:
                          Escalation(strategy="graph_search", reason="capability_error")
                          continue (do NOT abort)
                        else proceed normally
   4. raw_fetch (only if artifact_id is set)
   5. abstain
```

### Invariants

- **Best-effort projection** — Memory + artifact writes are source of truth. Revisor failures logged at WARN; exposed via `Capabilities.last_revisor_error`; do not abort the user's call.
- **No pg_raggraph import outside `src/stele/revisor/`** — verified by import-layer check.
- **PII-scrubbed at projection boundary** — `EvidenceRecord.text` must already be scrubbed. Defensive regex check; failure raises `BackendError` and the projection is skipped (logged).
- **Every `KnowledgeHit` carries `stele://` provenance** — orphan hits raise `BackendError` at the translation layer; the hit is dropped, never surfaced.
- **Two `as_of` paths** — `Memory.search(as_of=)` uses SQL filters (Phase 1); `Stele.recall(graph_search, as_of=)` uses pg-raggraph's graph traversal. They answer different questions and stay distinct.

## Configuration

```python
class LLMEndpointConfig(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 30.0
    temperature: float = 0.0


class PgRaggraphConfig(BaseModel):
    enabled: bool = False
    entity_mode: Literal["seeded", "llm"] = "seeded"
    llm: LLMEndpointConfig | None = None
    namespace_prefix: str = "stele"
    retracted_behavior_default: Literal["hide", "flag", "surface_both"] = "hide"
    project_on_write: bool = True
    max_entities_per_evidence: int = 50
    max_relations_per_evidence: int = 100


class IndexingConfig(BaseModel):
    # Phase 4 fields...
    pg_raggraph: PgRaggraphConfig = Field(default_factory=PgRaggraphConfig)
```

### Validators

- `entity_mode == "llm"` requires `llm: LLMEndpointConfig`; else `ConfigError`.
- `enabled == True` requires `backend.type == "postgres"`; else `ConfigError`.
- `namespace_prefix` must match `[a-z0-9_]{1,32}`; else `ConfigError`.
- `max_entities_per_evidence` and `max_relations_per_evidence` must be `> 0`.

### Capabilities expansion

```python
class Capabilities(BaseModel):
    # Phase 1/3/4 fields...
    pg_raggraph_installed: bool = False
    pg_raggraph_version: str | None = None
    revisor_mode: Literal["pg_raggraph", "noop"] | None = None
    entity_mode: Literal["seeded", "llm"] | None = None
    llm_endpoint_configured: bool = False
    retracted_behavior_default: Literal["hide", "flag", "surface_both"] | None = None
    last_revisor_error: str | None = None
```

## Error Handling

| Condition | Behavior |
|---|---|
| `pg_raggraph` not installed AND `indexing.pg_raggraph.enabled=True` | `OptionalDependencyError` at `Stele.__init__` |
| `backend.type != "postgres"` AND `enabled=True` | `ConfigError("pg_raggraph requires backend.type='postgres'")` |
| `entity_mode="llm"` AND `llm: None` | `ConfigError("entity_mode='llm' requires llm: LLMEndpointConfig")` |
| `Stele.recall(strategy="graph_search")` when `revisor.is_noop` | `CapabilityError` with install hint |
| LLM endpoint non-2xx during ingest | `BackendError("LLM extraction failed: <status>: <body>")`; recorded in `IndexReport.failures`; evidence skipped |
| LLM endpoint timeout | Same as above with `<status>=timeout` |
| `Revisor.ingest_evidence` raises during `Stele.store` projection | Best-effort log; **do not** abort; `_last_revisor_error` set |
| `Revisor.supersede` raises during `Memory.add(supersedes=)` projection | Same best-effort path |
| `Revisor.retract` raises during `Memory.retract` projection | Same |
| `KnowledgeHit` returned with empty `reference` | `BackendError` at translation; hit dropped |
| `KnowledgeHit.text` contains unscrubbed PII | `BackendError`; hit dropped; logged |
| `recall(graph_search, version_filter="vX")` no evidence has vX | Empty RecallResult (not an error) |
| `recall(graph_search, as_of=T0)` no evidence at T0 | Empty RecallResult (not an error) |
| `pg_raggraph` returns malformed records | `BackendError("malformed pg_raggraph record")`; call fails |
| `Memory.retract(memory_id)` for non-existent memory | `ArtifactNotFound` (Phase 1 facade behavior) |

**Asymmetry rationale:** Writes are durable in SQL regardless. Best-effort projection lets the user's call succeed even when the graph is misbehaving — the SQL state is correct, the graph can be rebuilt. Reads from a configured-but-broken graph layer must surface as `BackendError` — silent fallback would lie about the system's living-knowledge behavior.

## Success Criteria

- **SC-001:** Models (`EvidenceRecord`, `KnowledgeHit`, `IndexReport`, `EntitySeed`, `RelationSeed`) exist with the fields specified; field validation enforced. Verified by `test_models.py`.
- **SC-002:** `Revisor` Protocol exists with five methods (`ingest_evidence`, `search_current`, `search_as_of`, `supersede`, `retract`). Verified by `test_noop.py` Protocol conformance.
- **SC-003:** `NoOpRevisor` — ingest no-op, search raises `CapabilityError`, supersede/retract no-op, `is_noop=True`. Verified by `test_noop.py`.
- **SC-004:** `PgRaggraphRevisor` — lazy-imports `pg_raggraph`; `is_noop=False`; `OptionalDependencyError` raised at `Stele.__init__` when extra not installed but `enabled=True`. Verified by `test_pg_raggraph.py`.
- **SC-005:** `LLMEndpointConfig` + OpenAI-compat client — supports configured endpoint, model, timeout, temperature; non-2xx → `BackendError`. Verified by `test_llm_endpoint.py`.
- **SC-006:** `projection.artifact_to_evidence(ArtifactRecord)` produces `EvidenceRecord(kind="artifact", reference=..., ...)`. Verified by `test_projection.py`.
- **SC-007:** `projection.memory_to_evidence(MemoryRecord)` produces `EvidenceRecord(kind="memory", reference=..., supersedes=..., retracted=..., ...)`. Verified by `test_projection.py`.
- **SC-008:** `projection.knowledge_hits_to_citations(...)` returns `Citation` with `reference` (stele://) preserved; PII assertion fires on unscrubbed text. Verified by `test_projection.py`.
- **SC-009:** `RecallRequest` gains `as_of: datetime | None`, `version_filter: str | None`, `retracted_behavior: ... | None`. Defaults are `None`. Verified by `test_recall_request_phase5_fields.py`.
- **SC-010:** `Stele.recall(strategy="graph_search")` against pg-raggraph-configured Stele returns real `RecallResult` with `Citation`s — no longer raises `CapabilityError`. Verified by `test_graph_search_real.py`.
- **SC-011:** `Stele.recall(strategy="adaptive")` in a non-pg_raggraph deployment does NOT raise; records `Escalation(strategy="graph_search", reason="capability_error")` and continues. Verified by `test_adaptive_with_graph_search.py`.
- **SC-012:** `Memory.retract(memory_id, reason, retracted_at=None)` sets `status="retracted"`, persists retraction metadata, projects to `Revisor.retract` when configured. Verified by `test_memory_retract.py` (unit) + `test_retraction.py` (integration).
- **SC-013:** `Memory.add(supersedes=[old_ids])` projects to `Revisor.supersede(old_ref, new_ref, reason)` after SQL write succeeds. Verified by `test_supersession.py`.
- **SC-014:** `Stele.store(...)` projects `EvidenceRecord(kind="artifact")` to `Revisor.ingest_evidence` after SQL write succeeds. Verified by integration tests.
- **SC-015 (Bar #1):** Supersession works on both fixture lanes. Verified by `test_supersession.py` × 2 lanes.
- **SC-016 (Bar #2):** Retraction works on retracted_medical lane; `hide` / `flag` / `surface_both` all behave correctly. Verified by `test_retraction.py`.
- **SC-017 (Bar #3):** `as_of` recovers historical view on both lanes. Verified by `test_as_of.py` × 2.
- **SC-018 (Bar #4):** `version_filter` is exact on versioned_docs lane; no cross-version bleed. Verified by `test_version_filter.py`.
- **SC-019 (Bar #5):** Every KnowledgeHit carries `stele://` provenance. Verified by `test_provenance.py`.
- **SC-020 (Bar #6):** Postgres baseline works without pg_raggraph installed; `enabled=True` without the extra → `OptionalDependencyError`. Verified by `test_postgres_baseline_without_pg_raggraph.py`.
- **SC-021:** Architectural import-layer: `pg_raggraph` imported only from `src/stele/revisor/`. Verified by `test_architecture.py`.
- **SC-022:** `Capabilities` reports `pg_raggraph_installed`, `pg_raggraph_version`, `revisor_mode`, `entity_mode`, `llm_endpoint_configured`, `retracted_behavior_default`, `last_revisor_error`. Verified by `test_capabilities_pg_raggraph_fields.py`.
- **SC-023:** Best-effort projection on writes — when `Revisor.ingest_evidence` raises during `Stele.store`, the artifact write succeeds; `last_revisor_error` is populated. Verified by an integration test with a deliberately-broken Revisor.
- **SC-024:** Two `as_of` paths preserved: `Memory.search(as_of=)` works as Phase 1; `Stele.recall(graph_search, as_of=)` works via graph traversal; they give different results on a corpus where a memory exists but the underlying artifact does not yet. Verified by `test_as_of_two_paths.py`.
- **SC-025:** Living-knowledge benchmark produces `LivingKnowledge.{md,json}` with `current_recall_at_5`, `historical_recall_at_5`, `stale_memory_error_rate`, `version_filter_precision`. Verified by smoke + manual inspection.
- **SC-026:** Seeded-entity mode: `EvidenceRecord.entities` + `relations` flow into pg_raggraph without an LLM call. Verified by `test_pg_raggraph.py::test_seeded_entity_mode`.
- **SC-027:** LLM mode: when `entity_mode="llm"` and `llm: LLMEndpointConfig` configured, ingest calls the endpoint and extracted entities flow into pg_raggraph. Verified by `test_pg_raggraph.py::test_llm_entity_mode` with a mocked LLM endpoint.
- **SC-028:** Phase 1+3+4 deployments without pg_raggraph configured are bit-for-bit unchanged in behavior. Verified by running existing Phase 1/3/4 tests with `pg_raggraph.enabled=False` — all pass.

## Drift Checkpoints

- **⛔ DC-001** (after Revisor lands): `grep -rn 'pg_raggraph' src/stele/ | grep -v 'src/stele/revisor/'` must be empty (allowing for `TYPE_CHECKING` guards in projection.py if needed).
- **⛔ DC-002** (after Memory/Stele.store projections land): `grep -rn 'self\._revisor\.' src/stele/` should match only `src/stele/core/{memory,stash}.py` and `src/stele/recall/graph_search.py`. No other module reaches the Revisor directly.
- **⛔ DC-003** (after integration tests land): All 6 integration tests in `tests/integration/pg_raggraph/` pass on the applicable fixture lanes. **This is the Phase 5 exit gate** for the living-knowledge claim.
- **⛔ DC-004** (after adaptive integration): `Stele.recall(strategy="adaptive")` in a non-pg_raggraph deployment does not raise; the adaptive escalation trail records `capability_error` for the graph tier and continues.
- **⛔ DC-005** (after best-effort wiring): A deliberately-failing Revisor (test fixture) does not break `Stele.store()` or `Memory.add()`; `Capabilities.last_revisor_error` reports the failure.
- **⛔ DC-FINAL**: every SC-001..SC-028 has a passing test cited; Out-of-Scope verified untouched; living-knowledge benchmark produces a complete report.

## Out of Scope

- **Memory-row vectors in pg-raggraph.** Memory text ingests as graph evidence; vector embeddings go through Phase 4's chunk_store.
- **Cross-namespace graph traversal.** Single-namespace scope per call.
- **`stele rebuild-graph` admin CLI.** Phase 5.5 or M13.
- **Auto-detection of `version_label` from artifact text.** Callers tag via metadata.
- **Batch / cache / async LLM ingest.** Single round-trip per evidence.
- **Other graph backends (Neo4j, KuzuDB).** pg-raggraph only; Protocol shape leaves room.
- **Enterprise policy + customer/account fixture lanes.** Phase 5.5.
- **`flag` / `surface_both` as default.** Default `hide`.
- **`Memory.unretract()`.** Recover via explicit `Memory.add(text=..., supersedes=[retracted_id])`.
- **pg-raggraph schema migrations.** pg-raggraph owns its tables; Stele pins a compatible version.
- **GraphQL / REST exposure.** Out of scope.
- **New authorization / tenancy model.** Existing scope filtering only.

## Living Knowledge Verification (the exit gate)

**No public claim of "living knowledge" behavior until all six bullets pass on both fixture lanes.**

### Lane 1 — Versioned software docs

Fixture: `tests/fixtures/pg_raggraph/versioned_docs.json`. ≥10 evidence
records, ≥5 queries with mixed `version_filter` + current + historical
expectations. Mirrors pg-raggraph's Python-docs benchmark.

### Lane 2 — Retracted medical/scientific claims

Fixture: `tests/fixtures/pg_raggraph/retracted_medical.json`. ≥8 evidence
records, ≥4 queries covering `retracted_behavior` hide / flag /
surface_both. Mirrors pg-raggraph's HRT benchmark.

### Bar verification matrix

| Bar bullet | Lane 1 (versioned docs) | Lane 2 (retracted medical) |
|---|---|---|
| #1 supersession | ✓ py39 → py312 | ✓ HRT 2002 → 2017 |
| #2 retraction | (n/a by design) | ✓ HRT 2002 retracted; hide/flag/surface_both |
| #3 as_of | ✓ recall(as_of=2020) returns py39; recall(as_of=2024) returns py312 | ✓ recall(as_of=2010) returns 2002 claim; recall(as_of=2020) returns 2017 |
| #4 version_filter | ✓ version_filter="py39" returns only py39 docs | (n/a by design) |
| #5 provenance | ✓ stele://docs/... on every hit | ✓ stele://medical/... on every hit |
| #6 baseline w/o pg_raggraph | ✓ Postgres + no pg_raggraph: graph_search raises CapabilityError; Phase 1/3/4 unaffected | (same) |

### Benchmark metrics

`benchmarks/living_knowledge.py` reports per-lane:

- `current_recall_at_5` — fraction of queries where current-only search returns the expected answer
- `historical_recall_at_5` — fraction where `as_of=<historical T>` returns the expected historical answer
- `stale_memory_error_rate` — fraction of current queries that incorrectly return superseded evidence (target: 0% under `hide`)
- `version_filter_precision` — fraction where ALL hits match the requested version (target: 100%)

## Testing Requirements Summary

| Suite | Path | Anchors |
|---|---|---|
| Models | `tests/unit/revisor/test_models.py` | SC-001 |
| Protocol + NoOp | `tests/unit/revisor/test_noop.py` | SC-002, SC-003 |
| PgRaggraph adapter | `tests/unit/revisor/test_pg_raggraph.py` | SC-004, SC-026, SC-027 |
| LLM endpoint | `tests/unit/revisor/test_llm_endpoint.py` | SC-005 |
| Projection | `tests/unit/revisor/test_projection.py` | SC-006, SC-007, SC-008 |
| RecallRequest fields | `tests/unit/recall/test_recall_request_phase5_fields.py` | SC-009 |
| graph_search real | `tests/unit/recall/test_graph_search_real.py` | SC-010 |
| Adaptive skip | `tests/unit/recall/test_adaptive_with_graph_search.py` | SC-011 |
| Memory.retract | `tests/unit/core/test_memory_retract.py` | SC-012 |
| Memory.add projection | (integration) `tests/integration/pg_raggraph/test_supersession.py` | SC-013 |
| Stele.store projection | (integration) | SC-014 |
| **Verification bar (load-bearing)** | `tests/integration/pg_raggraph/test_*.py` × 6 | SC-015..SC-020 |
| Architecture | `tests/unit/revisor/test_architecture.py` | SC-021 |
| Capabilities | `tests/unit/core/test_capabilities_pg_raggraph_fields.py` | SC-022 |
| Best-effort writes | (integration) | SC-023 |
| Two as_of paths | `tests/integration/pg_raggraph/test_as_of_two_paths.py` | SC-024 |
| Benchmark | `benchmarks/living_knowledge.py` + smoke | SC-025 |
| Regression | existing Phase 1/3/4 tests with pg_raggraph disabled | SC-028 |

## Cross-References

- Strategy doc Living Knowledge Base section: `docs/sovereign-memory-system-plan.md:81-130`
- Phase 5 scope section: `docs/sovereign-memory-system-plan.md:636-653`
- Evolution Boundary: `docs/sovereign-memory-system-plan.md:181-200`
- PRD Phase 5 summary: `docs/prd-sovereign-stele.md:353-356`
- M12 milestone: `docs/specs/implementation-execution-plan.md:358-385`
- Phase 3 graph_search stub: `src/stele/recall/graph_search.py` (currently on `phase3-policy-driven-recall` branch; Phase 5 plan Task 0 will verify Phase 3 has merged to main first)
- Phase 4 ChunkStore pattern precedent: `src/stele/storage/chunk_store/base.py` + `noop.py` equivalents (Phase 4 ships on main as part of `docs/superpowers/specs/2026-05-14-phase4-chunkshop-indexing-design.md`)
- Benchmark precedent for LLM endpoint client: `benchmarks/answer_workflow.py::OpenAICompatAnswerer`

## Location Note

This spec lives at `/tmp/stele-phase5-planning/` per user instruction. It
is **not committed to git**. When the Phase 2/3 agents finish settling
their branches, the user will direct where to commit (likely `main` or a
dedicated `phase5-pg-raggraph-living-knowledge` branch).
