# Runtime Agent Memory Architecture Spec

## TL;DR

Stele should add runtime agent-memory capabilities without weakening its core trust model. The target design is automatic capture, layered memory, active WorkGraphs, prompt context tiering, adapter health, and benchmarked context compression. The Stele version should remain deterministic by default, source-backed through `stele://` refs, policy-gated for PII/raw access, and testable across backends.

## Reference Implementation Reviewed

This spec is informed by a prior-art implementation reviewed during architecture research:

- Repository: `TencentDB-Agent-Memory`
- Primary stack: TypeScript OpenClaw plugin plus Python Hermes provider
- Main integration surfaces: OpenClaw hooks, OpenClaw tools, Hermes provider, Node gateway, Tencent Cloud VectorDB, SQLite/FTS/sqlite-vec
- Most relevant modules:
  - `index.ts`
  - `src/core/tdai-core.ts`
  - `src/core/hooks/auto-capture.ts`
  - `src/core/hooks/auto-recall.ts`
  - `src/utils/pipeline-manager.ts`
  - `src/offload/*`
  - `src/gateway/server.ts`
  - `hermes-plugin/memory/memory_tencentdb/*`

## Stele Baseline

Stele should preserve these existing strengths in the core memory contract:

- Source-backed `stele://` references are a cleaner provenance primitive.
- Deterministic extraction gives Stele a stronger correctness baseline.
- Supersession and `as_of` queries give Stele an explicit temporal truth model.
- PII scrubbing and raw fetch gates should remain explicit and policy-governed.
- The explicit `Stele.recall` strategy surface should remain the primary product contract, even when adapters add prompt packing.

The reference implementation demonstrates runtime capabilities Stele should account for:

- It captures memory automatically inside an agent runtime.
- It injects recall context automatically before prompt construction.
- It maintains short-term task state through context offload and Mermaid task graphs.
- It separates hot interaction capture from deeper L1/L2/L3 processing.
- It has operational sidecar lessons from the Hermes provider and gateway watchdog.

## Prior Art Assessment Matrix

| Reference Concept | Stele Treatment | Rationale |
| --- | --- | --- |
| L0/L1/L2/L3 layered memory pyramid | ADOPT | The model is sound, but Stele should enforce evidence chains between layers. |
| Auto-capture lifecycle hooks | ADAPT | Use public adapter hooks for LangChain/MCP/OpenAI Agents/etc.; do not replicate OpenClaw coupling. |
| Auto-recall prompt injection | ADAPT | Keep explicit `Stele.recall`, then add adapter context packers that call it. |
| Context offload raw refs | ADAPT | Store raw data as Stele artifacts with PII/raw policy, not as separate unmanaged refs. |
| Mermaid task graph | ADOPT AS VIEW | Use Mermaid as a renderer for a structured WorkGraph, not the source of truth. |
| L1 extraction/dedup/write queue | PARTIAL ADAPT | Adopt staged processing and session flush; keep Stele extraction deterministic by default. |
| L2 scene files | REIMAGINE | Implement source-backed topic/session views, not free-form LLM-authored Markdown state. |
| L3 persona/profile generation | REIMAGINE | Implement evidence-backed profile views with versioning and citations. |
| Pipeline warm-up/idle scheduling | ADOPT | Useful for adapters and long-running sessions. |
| Gateway watchdog patterns | ADOPT | Relevant to any Stele sidecar or framework adapter. |
| Runtime monkeypatching | AVOID | Too fragile for Stele's core positioning. |
| Prompt-only call limits | AVOID | Stele should enforce budgets in code. |
| Silent degraded no-op behavior | AVOID | Stele should expose health/degraded state explicitly. |

## Target Stele Architecture Additions

The runtime-memory features should land as three additive layers around Stele's existing core.

```text
Framework adapter layer
  - observes tool calls, messages, session boundaries
  - calls Stele artifact/memory/recall APIs
  - injects packaged context into prompts
  - exposes adapter health

Runtime working-memory layer
  - stores active task/session state as WorkGraph records
  - links every task event to stele:// evidence
  - renders Mermaid/Markdown/JSON views
  - supports compact prompt context plus drill-down refs

Derived knowledge layer
  - evidence-backed topic/session/profile views
  - versioned and regenerable
  - optional LLM assistance only behind validators
```

The core invariant is:

```text
Any derived claim -> source-backed node/event -> memory atom -> stele:// artifact -> exact content
```

If a layer cannot preserve this chain, it should not be authoritative in Stele.

## Spec 1: WorkGraph Domain Model

### Purpose

Add a Stele-native representation of active work, long-running task state, and compact task progress. This is the highest-value design pattern identified in the reference implementation.

TencentDB's version:

```text
tool output -> raw ref
tool/action summary -> Mermaid node
Mermaid graph -> compressed prompt state
node id -> drill-down ref
```

Stele's version:

```text
tool output -> Stele artifact
artifact summary/chunks -> TaskTraceEvent
TaskTraceEvent -> TaskNode/TaskEdge
WorkGraph -> compact prompt context
node/event id -> stele:// drill-down refs
```

### Non-Goals

- Do not make Mermaid the authoritative state.
- Do not require an LLM to create a valid WorkGraph.
- Do not store raw tool output directly in graph nodes.
- Do not bypass artifact PII/raw-access policy.

### Proposed Package

```text
src/stele/workgraph/
  __init__.py
  models.py
  store.py
  renderers.py
  context.py
  validators.py
tests/unit/workgraph/
tests/contract/test_workgraph_store.py
```

### Core Models

`WorkGraph`

- `id: str`
- `namespace: str`
- `session_id: str | None`
- `scope: str | None`
- `title: str`
- `status: Literal["active", "paused", "completed", "failed", "abandoned"]`
- `created_at: datetime`
- `updated_at: datetime`
- `source_refs: list[str]`
- `metadata: dict[str, Any]`

`TaskNode`

- `id: str`
- `graph_id: str`
- `kind: Literal["goal", "tool_call", "decision", "finding", "blocker", "artifact", "handoff", "verification"]`
- `label: str`
- `summary: str`
- `status: Literal["pending", "active", "done", "blocked", "failed", "superseded"]`
- `source_refs: list[str]`
- `artifact_refs: list[str]`
- `memory_refs: list[str]`
- `created_at: datetime`
- `updated_at: datetime`
- `metadata: dict[str, Any]`

`TaskEdge`

- `id: str`
- `graph_id: str`
- `from_node_id: str`
- `to_node_id: str`
- `kind: Literal["depends_on", "caused", "derived", "supersedes", "verifies", "blocks", "continues"]`
- `source_refs: list[str]`
- `created_at: datetime`
- `metadata: dict[str, Any]`

`TaskTraceEvent`

- `id: str`
- `graph_id: str`
- `node_id: str | None`
- `event_kind: Literal["message", "tool_call", "tool_result", "artifact_stored", "memory_extracted", "recall_used", "decision", "verification", "error"]`
- `summary: str`
- `source_refs: list[str]`
- `timestamp: datetime`
- `metadata: dict[str, Any]`

### Validation Rules

- Every graph must include at least one source ref once persisted.
- Every node must include at least one source ref, artifact ref, memory ref, or explicit `derived_from` pointer.
- Every edge that asserts causality or derivation must include at least one source ref or connect nodes that both cite evidence.
- All refs must parse with Stele's existing reference parser.
- Raw content is forbidden in `label`, `summary`, and `metadata` values above a small threshold.
- PII policy must run on human-readable summaries before persistence.
- Status transitions must be valid:
  - `pending -> active -> done`
  - `pending -> blocked`
  - `active -> blocked`
  - `blocked -> active`
  - `active -> failed`
  - any non-terminal status -> `abandoned`
  - terminal statuses cannot transition except through explicit supersession.

### Acceptance Criteria

- A WorkGraph can be created from a session id and namespace.
- Nodes, edges, and trace events can be added without an LLM.
- Invalid refs fail validation before persistence.
- Raw large content cannot be stored directly in a node summary.
- Mermaid, Markdown, and JSON renderers can render the same graph.
- Renderers include drill-down refs.
- Contract tests run against memory and SQLite backends initially.

## Spec 2: WorkGraph Store Protocol

### Purpose

Define a backend-neutral protocol before adding storage-specific implementations.

### API Sketch

```python
class WorkGraphStore(Protocol):
    def create_graph(self, graph: WorkGraph) -> WorkGraph: ...
    def get_graph(self, graph_id: str, *, as_of: datetime | None = None) -> WorkGraph | None: ...
    def list_graphs(
        self,
        *,
        namespace: str,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[WorkGraph]: ...
    def add_node(self, node: TaskNode) -> TaskNode: ...
    def update_node(self, node_id: str, patch: Mapping[str, Any]) -> TaskNode: ...
    def add_edge(self, edge: TaskEdge) -> TaskEdge: ...
    def add_event(self, event: TaskTraceEvent) -> TaskTraceEvent: ...
    def query_graph(
        self,
        *,
        namespace: str,
        query: str,
        session_id: str | None = None,
        active_only: bool = True,
        limit: int = 20,
    ) -> list[TaskNode]: ...
```

### Backend Order

1. Memory store for model and contract tests.
2. SQLite store for local durable adapter usage.
3. Postgres store only when graph features need production backend parity.

### Acceptance Criteria

- All store implementations pass the same contract tests.
- Query by namespace/session/status is deterministic.
- `as_of` support is either implemented or explicitly raises `CapabilityError`.
- Graph deletion follows the same soft-delete policy as the rest of Stele where possible.

## Spec 3: Artifact-To-WorkGraph Capture

### Purpose

Turn framework events into source-backed graph updates.

### Inputs

- User message observed by adapter.
- Assistant message observed by adapter.
- Tool call metadata.
- Tool result payload.
- Stored artifact result from Stele.
- Extracted memory ids.
- Recall result metadata.
- Session start/end.

### Rules

- Large tool result payloads must be stored as artifacts first.
- Graph events may include summaries, refs, sizes, content type, and hashes.
- Graph events must not include raw payloads unless they are below threshold and scrubbed.
- Adapter code should own event capture; core Stele should only define models and store operations.

### Acceptance Criteria

- Given a synthetic tool result above threshold, Stele stores an artifact and creates a graph event with only refs and compact summary.
- Given a recall call, Stele records which memory/artifact refs were injected into context.
- Given session end, Stele can close or pause the active WorkGraph without touching other sessions.

## Spec 4: Context Packer

### Purpose

Add prompt-tiering while preserving Stele's explicit recall surface.

### Context Sections

`stable_context`

- Project/user/team profile claims.
- Long-lived policies.
- Adapter/system capabilities.
- Cache-friendly content.

`dynamic_context`

- Query-specific recall results.
- Active WorkGraph nodes.
- Recent task decisions and blockers.
- Current source map.

`recovery_handles`

- `stele://` refs.
- WorkGraph node ids.
- Artifact ids.
- Memory ids.

### API Sketch

```python
class ContextPack(NamedTuple):
    stable_context: str
    dynamic_context: str
    recovery_handles: list[str]
    token_estimate: int
    omitted: list[str]

def pack_context(
    *,
    recall_result: RecallResult,
    workgraph: WorkGraph | None = None,
    budget_tokens: int,
    policy: ContextPolicy,
) -> ContextPack:
    ...
```

### Budget Rules

- Hard cap total packed context.
- Hard cap raw snippets.
- Hard cap WorkGraph nodes.
- Prefer current active blockers and decisions over old completed nodes.
- Prefer evidence-backed summaries over raw snippets unless strategy asks for raw fetch.
- Include omitted counts so the adapter can explain truncation.

### Acceptance Criteria

- Stable and dynamic context are returned separately.
- Stored artifacts/transcripts are not mutated by packed context.
- Budget overflow is deterministic and visible in `omitted`.
- Packed context includes refs for every claim.

## Spec 5: Adapter Health Contract

### Purpose

Make Stele adapters debuggable. Background memory systems need explicit health reporting because silent degraded behavior is hard to diagnose.

### Health Fields

```python
class AdapterHealth(NamedTuple):
    status: Literal["healthy", "degraded", "disabled", "missing_dependency", "stale_index", "policy_blocked"]
    exact_store_available: bool
    memory_store_available: bool
    index_available: bool
    recall_available: bool
    pii_mode: str
    pending_queue_depth: int
    last_capture_at: datetime | None
    last_extract_at: datetime | None
    last_index_at: datetime | None
    last_recall_at: datetime | None
    degraded_reason: str | None
    capabilities: Mapping[str, bool]
```

### Acceptance Criteria

- Adapters expose a health method.
- Missing optional dependencies are reported explicitly.
- Degraded recall does not pretend to be healthy.
- Health state is testable without a live LLM provider.

## Spec 6: Adapter Scheduling Policy

### Purpose

Add warm-up, idle, and session-end scheduling for adapters.

### Policy

- On first useful interaction, capture/extract immediately.
- During early session, process on turns 1, 2, 4, and 8.
- During mature session, process by queue size, elapsed time, or idle timeout.
- On session end, flush only that session.
- On shutdown, bounded flush with timeout and explicit leftovers.

### Acceptance Criteria

- Scheduler never flushes another session by accident.
- Idle flush can be tested with a fake clock.
- Session end flush is idempotent.
- Queue depth appears in adapter health.

## Spec 7: Evidence-Backed Topic, Scene, and Profile Views

### Purpose

Add human-readable scene/profile-style views, but make them structured and evidence-backed.

### Views

`TopicView`

- Cluster of related memories/artifacts.
- Useful for project areas, customer accounts, workflows, and recurring issues.

`SessionView`

- Summary of a single session.
- Includes decisions, unresolved blockers, artifacts created, and follow-up actions.

`ProfileView`

- Stable user/project/team preferences and operating context.
- Source-backed and versioned.

### Rules

- Views are derived, not primary truth.
- Every claim cites memory/artifact refs.
- Views are regenerable.
- LLM-generated views must be marked generated and validated.
- Markdown export is a view, not the canonical store.

### Acceptance Criteria

- A view can be generated deterministically from selected memories/artifacts.
- Markdown export includes citations.
- Updating a memory invalidates or versions affected views.
- The API can explain which refs support a profile claim.

## Spec 8: Optional LLM Summarization

### Purpose

Allow LLMs to improve summaries and graph labels without letting them mutate memory truth unchecked.

### Rules

- LLM output is a proposal.
- Validator enforces schema, refs, PII policy, length limits, and status transitions.
- Invalid proposals are rejected with reasons.
- Accepted proposals are versioned and reversible.
- Deterministic fallback must exist.

### Acceptance Criteria

- Tests cover malformed LLM JSON.
- Tests cover fabricated refs.
- Tests cover PII leakage in generated summaries.
- Tests cover rollback/versioning of generated views.

## Spec 9: Benchmarks For Runtime-Memory Features

### Purpose

TencentDB claims massive context compression. Stele should only make similar claims with evidence.

### Benchmark Scenarios

- Long tool-output session where raw outputs exceed context budget.
- Multi-step debugging task with decisions and blockers.
- Recall task where answer-bearing evidence is stored in artifacts.
- Session resume where WorkGraph context should be enough to continue.
- PII fixture where sensitive raw content must not appear in packed context.

### Metrics

- Input token reduction vs raw transcript.
- Latency added by capture/extract/index/pack.
- Answer-bearing ref recall rate.
- False recall rate.
- PII leakage count.
- Session-resume success rate.
- Context pack determinism across runs.

### Acceptance Criteria

- Benchmark emits JSON and Markdown reports.
- Reports include exact fixture ids and strategy names.
- Claims in README/docs point to benchmark output.
- Regression thresholds are checked in CI for core deterministic paths.

## Proposed Backlog Addendum

These tasks can be appended to `docs/specs/build-backlog.md` after the existing Wave 4 section.

### T-RAM-001: WorkGraph Models And Validators

Build `WorkGraph`, `TaskNode`, `TaskEdge`, and `TaskTraceEvent` models with validation rules and tests.

Depends on:

- Existing reference parser/signing
- Existing PII scrubber
- Existing artifact/memory result models

Acceptance:

- Models serialize to JSON.
- Invalid refs fail validation.
- Large raw content in summaries fails validation.
- Every persisted node/event has a source path back to Stele evidence.

### T-RAM-002: WorkGraph Store Protocol And Memory Backend

Define the store protocol and implement the in-memory backend.

Acceptance:

- Contract tests cover create/get/list/query/add-node/add-edge/add-event.
- Query by namespace and session is deterministic.
- Unsupported `as_of` behavior is explicit.

### T-RAM-003: SQLite WorkGraph Store

Implement durable local WorkGraph storage.

Acceptance:

- SQLite backend passes the same WorkGraph contract tests.
- Session-scoped list/query works.
- Status changes persist.
- Soft-delete or explicit tombstone behavior is documented.

### T-RAM-004: WorkGraph Renderers

Implement Mermaid, Markdown, and JSON renderers.

Acceptance:

- Mermaid renderer includes node ids and compact labels.
- Markdown renderer includes citations/drill-down refs.
- JSON renderer round-trips structured records.
- Renderers never become authoritative storage.

### T-RAM-005: Artifact-To-WorkGraph Capture Helper

Add adapter-facing helpers that turn observed runtime events into artifacts and graph events.

Acceptance:

- Large tool output is stored as artifact before graph event creation.
- Recall usage can be recorded with refs injected.
- Session end closes or pauses only the active graph.

### T-RAM-006: Context Packer

Package recall and WorkGraph state into stable/dynamic/recovery context.

Acceptance:

- Stable and dynamic sections are separate.
- Budget truncation is deterministic.
- Every packed claim carries refs.
- Packed context is never written back into stored artifacts by default.

### T-RAM-007: Adapter Health Contract

Define and test the health status contract for future adapters.

Acceptance:

- Health reports exact store, memory store, index, recall, PII mode, queue depth, and degraded reason.
- Missing optional dependencies produce explicit states.
- Health can be tested with fake stores/providers.

### T-RAM-008: Adapter Scheduling Policy

Implement reusable scheduling primitives for capture/extract/index.

Acceptance:

- Warm-up turns 1/2/4/8 are configurable.
- Idle flush uses injectable clock.
- Session end flush is scoped.
- Queue state appears in health.

### T-RAM-009: Evidence-Backed Views

Implement structured topic/session/profile views.

Acceptance:

- Views are derived from memories/artifacts.
- Every claim cites refs.
- Markdown export includes citations.
- Updating a source can invalidate or version derived views.

### T-RAM-010: Optional LLM Proposal Pipeline

Allow LLMs to propose graph labels, summaries, and profile claims behind validators.

Acceptance:

- Fabricated refs are rejected.
- PII leakage is rejected.
- Invalid schema is rejected.
- Accepted generated state is versioned and reversible.

### T-RAM-011: Long-Task Context Compression Benchmark

Benchmark WorkGraph/context-packer value.

Acceptance:

- Emits JSON and Markdown reports.
- Measures token reduction, latency, answer-bearing ref recall, false recall, PII leakage, and resume success.
- README claims cite generated reports.

## Recommended Phase Placement

| Task | Suggested Phase |
| --- | --- |
| T-RAM-001 to T-RAM-004 | After current Phase 5 graph foundation, before broad adapter SDK work |
| T-RAM-005 to T-RAM-008 | Phase 8 plugin SDK/framework adapters |
| T-RAM-009 | Phase 5/6 depending on pg-raggraph readiness |
| T-RAM-010 | Post-deterministic baseline only |
| T-RAM-011 | Before any public context-compression claim |

## Design Constraints Stele Should Keep

- No authoritative derived state without `stele://` evidence.
- No LLM-first memory mutation.
- No runtime monkeypatching in the core.
- No prompt-only enforcement for budgets or call limits.
- No raw ref store outside the artifact lifecycle.
- No silent memory failure in adapters.
- No README claim without benchmark evidence.

## Open Questions

- Should WorkGraph records be memories, artifacts, or a third first-class record type?
- Should WorkGraph support `as_of` from day one or only after SQLite/Postgres storage?
- Should graph search use pg-raggraph, a simpler relational model, or both?
- What minimum adapter should prove the model first: LangChain, MCP, OpenAI Agents SDK, or Stele's own demo runner?
- Should generated profile views become recall inputs by default, or only after explicit opt-in?

## Practical Recommendation

Build WorkGraph as a small, source-backed Stele subsystem before attempting broad framework integration. Then add one adapter that proves the loop:

```text
observe tool result -> store artifact -> update WorkGraph -> extract memory -> recall/pack context -> resume task
```

That gives Stele TencentDB's most valuable user-visible behavior while preserving Stele's stronger trust model.
