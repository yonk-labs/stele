---
phase: 3
title: Policy-Driven Recall
created: 2026-05-13
status: design-approved
depends-on: |
  Phase 1 complete (Tasks 0–21 of `docs/superpowers/plans/2026-05-12-phase1-memory-supersession.md`).
  Phase 2 complete (Tasks 0–23 of `docs/superpowers/plans/2026-05-13-phase2-deterministic-extraction.md`).
---

# Phase 3: Policy-Driven Recall — Design

## TL;DR

Phase 3 lifts the answer-workflow benchmark's hardcoded strategies into a
production `Recall` engine at `src/stele/recall/`. Callers ask
"given this query and scope, give me the right context for my LLM" and get
back a `RecallResult` describing the strategy used, the assembled context,
the citations, the escalation trail (for adaptive), and the cost stats.
Phase 3 is a **context selector**, not an answer generator — it never calls
an LLM itself.

Six strategies ship for real: `summary_only`, `memory_search`,
`artifact_search`, `adaptive`, `raw_fetch`, `abstain`. `graph_search` ships
as a `CapabilityError` stub until Phase 5 wires pg-raggraph. The benchmark
gets migrated to use `Stele.recall(...)` instead of its private
`_run_strategy`; the two paths produce structurally equivalent results,
locked by a regression test.

## The Four Headline Proofs

1. **Behavior preservation.** The five existing benchmark scenarios
   (`summary_only` / `search_first` / `summary_then_search` / `adaptive` /
   `raw_fetch`) reproduce their current accuracy + token counts when routed
   through `Stele.recall(...)` — proving the lift was behavior-preserving.
2. **No oracle.** `adaptive` works **without** `_answer_is_sufficient`: a new
   heuristic (hit-count + confidence floor) escalates correctly on the
   existing scenarios, with optional caller-supplied `sufficient` callback
   for LLM-in-the-loop judgment.
3. **Memory-aware.** `memory_search` uses Phase 1's `Memory.search_with_score`
   and returns memory hits as citations with `kind="memory"`.
4. **Explicit abstention.** `abstain` fires (either by explicit call or as
   adaptive's last-tier fallback) with a structured `abstain_reason` — never
   raises, never silently returns empty context.

## Locked Architectural Decisions

These were settled during brainstorming; they constrain the rest of the
design.

1. **Strategy set: 6 real + 1 stub.** `summary_only`, `memory_search`,
   `artifact_search`, `adaptive`, `raw_fetch`, `abstain` implemented.
   `graph_search` raises `CapabilityError("graph_search requires Phase 5
   pg-raggraph adapter")`.
2. **Adaptive escalation: hit-count + confidence floor + optional caller
   callback.** Default heuristic is deterministic. Caller may pass
   `sufficient=Callable[[RecallContext], bool]` for smarter judgment.
3. **Canonical entry + convenience shims.** `stele.recall(query=...,
   scope=..., strategy="adaptive")` is canonical; `stele.recall.adaptive(...)`,
   `stele.recall.memory_search(...)`, etc. are one-line wrappers. The
   facade is a *callable* — implements `__call__` and exposes the seven
   shim methods.
4. **`artifact_id` is a hard scoping constraint.** When set, every strategy
   locks retrieval to that artifact (memory_search filters by
   `source_refs`, artifact_search uses the reference, raw_fetch fetches it,
   adaptive scopes every tier). When `None`, global search.
5. **Small additive helpers on Memory + Extractor.**
   `Memory.search_with_score(query, scope, source_ref_filter=None)` and
   `MemoryExtractor.preview(text, source_refs, scope)`. Filter pushed into
   the backend (not Python post-fetch).
6. **Strategy-class pattern.** One file per strategy implementing a common
   `Strategy` Protocol — mirrors Phase 1's `MemoryStore` shape.

## Public API

### Canonical entry + convenience shims

```python
# Canonical entry
result: RecallResult = stele.recall(
    query="what does the user prefer about the dashboard?",
    scope=MemoryScope(user_id="alice"),
    strategy="adaptive",
    artifact_id=None,
    sufficient=None,
    max_memory_hits=5,
    max_artifact_hits=5,
    confidence_floor=None,        # overrides RecallConfig.confidence_floor when set
)

# Convenience shims (one-line wrappers around the canonical):
stele.recall.summary_only(artifact_id="abc", scope=...)
stele.recall.memory_search(query="...", scope=...)
stele.recall.artifact_search(query="...", scope=...)
stele.recall.graph_search(...)              # raises CapabilityError
stele.recall.adaptive(query="...", scope=..., sufficient=None)
stele.recall.raw_fetch(artifact_id="abc", scope=...)
stele.recall.abstain(query="...", scope=..., reason="explicit")
```

`stele.recall` is a property returning a `Recall` instance that is both
callable (`__call__` routes by `strategy`) and exposes the seven shims as
methods.

### Return shape

```python
StrategyName = Literal[
    "summary_only", "memory_search", "artifact_search",
    "graph_search", "adaptive", "raw_fetch", "abstain",
]

CitationKind = Literal["memory", "artifact", "chunk"]
EscalationReason = Literal[
    "tier_complete",
    "below_floor",
    "zero_hits",
    "sufficient_callback_false",
    "exhausted",
]


class Citation(BaseModel):
    kind: CitationKind
    id: str                              # memory_id, artifact_id, or chunk_id
    reference: str                       # full stele:// URI (always populated)
    score: float                         # normalized to [0, 1]
    snippet: str                         # PII-scrubbed text shown to the LLM


class Escalation(BaseModel):
    strategy: StrategyName               # which tier ran in this step
    hit_count: int
    top_score: float | None              # None if no hits
    reason: EscalationReason


class RecallStats(BaseModel):
    memory_searches: int = 0
    artifact_searches: int = 0
    chunk_searches: int = 0
    fetches: int = 0
    estimated_context_tokens: int = 0
    latency_ms: float = 0.0


class RecallResult(BaseModel):
    strategy_used: StrategyName          # what actually fired (may be "abstain" inside adaptive)
    context: str                         # PII-scrubbed assembled context for the LLM
    citations: list[Citation]
    escalations: list[Escalation]        # always populated; non-adaptive strategies have exactly one entry
    pii_flags: list[str]
    stats: RecallStats
    abstained: bool                      # True iff strategy_used == "abstain"
    abstain_reason: str | None           # populated when abstained
```

### Input shape

```python
class RecallRequest(BaseModel):
    query: str
    scope: MemoryScope
    strategy: StrategyName = "adaptive"
    artifact_id: str | None = None
    sufficient: Callable[[RecallContext], bool] | None = None
    max_memory_hits: int = 5
    max_artifact_hits: int = 5
    confidence_floor: float | None = None


@dataclass(frozen=True)
class RecallContext:
    """Snapshot of the in-flight adaptive escalation, handed to sufficient callbacks."""
    query: str
    scope: MemoryScope
    accumulated_citations: list[Citation]
    accumulated_text: str
```

## `artifact_id` Semantics — Forced Scope

When `artifact_id` is provided, every strategy scopes its retrieval to that
artifact. When `None`, each strategy uses its natural global scope.

| Strategy | `artifact_id = None` | `artifact_id = "abc123"` (forced scope) |
|---|---|---|
| `summary_only` | `ValidationError` — strategy needs an artifact | Returns the summary of `abc123` |
| `memory_search` | Searches all memories matching `scope` | Filters to memories whose `source_refs` include `stele://<ns>/abc123` |
| `artifact_search` | Calls `stele.search(query)` across the artifact store | Calls `stele.search(reference="stele://<ns>/abc123", query)` — current benchmark behavior |
| `graph_search` | `CapabilityError` (Phase 5) | `CapabilityError` (Phase 5) |
| `raw_fetch` | `ValidationError` — needs an artifact | Fetches `abc123` raw |
| `adaptive` | memory → artifact → abstain (raw_fetch tier skipped) | memory → artifact → raw → abstain; every tier scoped to `abc123` |
| `abstain` | Returns empty context with reason | Returns empty context with reason (artifact_id ignored) |

The `<ns>` placeholder is whatever namespace the artifact lives under;
Phase 3 looks it up via `Stele.fetch(artifact_id)` once at the start of
adaptive and caches the resolved `stele://` reference on the
`_RecallDeps` struct so subsequent tiers don't re-fetch.

## File Layout

### New files

| Path | Responsibility |
|---|---|
| `src/stele/recall/__init__.py` | Re-exports `RecallRequest`, `RecallResult`, `Citation`, `Escalation`, `RecallStats`, `StrategyName`, `RecallContext` |
| `src/stele/recall/models.py` | All Pydantic + dataclass models above |
| `src/stele/recall/base.py` | `Strategy` Protocol (`execute(request, ctx) -> RecallResult`); `_RecallDeps` dataclass injected to strategies |
| `src/stele/recall/ranking.py` | `normalize_scores(hits)` (per-backend raw → [0,1]); `merge_hits(*sources)` (dedup by `(kind, id)` keeping max) |
| `src/stele/recall/summary_only.py` | `SummaryOnlyStrategy` |
| `src/stele/recall/memory_search.py` | `MemorySearchStrategy` |
| `src/stele/recall/artifact_search.py` | `ArtifactSearchStrategy` |
| `src/stele/recall/graph_search.py` | `GraphSearchStrategy` (stub raises `CapabilityError`) |
| `src/stele/recall/raw_fetch.py` | `RawFetchStrategy` |
| `src/stele/recall/abstain.py` | `AbstainStrategy` |
| `src/stele/recall/adaptive.py` | `AdaptiveStrategy` (registry of strategies, escalation logic) |
| `src/stele/recall/facade.py` | `Recall` callable class (canonical entry + 7 convenience shims) |
| `tests/unit/recall/__init__.py` | Package marker |
| `tests/unit/recall/test_models.py` | Field validation |
| `tests/unit/recall/test_ranking.py` | Score normalization + merge_hits |
| `tests/unit/recall/test_summary_only.py` | Strategy unit tests |
| `tests/unit/recall/test_memory_search.py` | Strategy unit tests |
| `tests/unit/recall/test_artifact_search.py` | Strategy unit tests |
| `tests/unit/recall/test_graph_search.py` | CapabilityError stub regression |
| `tests/unit/recall/test_raw_fetch.py` | Strategy unit tests |
| `tests/unit/recall/test_abstain.py` | Strategy unit tests |
| `tests/unit/recall/test_adaptive.py` | Escalation trail, hit-count + floor, callback path, tier-order config |
| `tests/unit/recall/test_facade.py` | Canonical-vs-shim equivalence; `__call__` works |
| `tests/unit/recall/test_architecture.py` | Import-layer check — no Phase 4/5 deps, no LLM clients |
| `tests/contract/test_recall_contract.py` | Cross-backend (memory + sqlite + postgres) |
| `tests/benchmarks_smoke/test_answer_workflow_via_recall.py` | Regression: new path == old path on existing fixtures |

### Modified files (small, additive)

| Path | Change |
|---|---|
| `src/stele/core/memory.py` | Add `Memory.search_with_score(query, scope, source_ref_filter=None) -> list[ScoredMemoryHit]` |
| `src/stele/core/memory_record.py` | Add `ScoredMemoryHit` model (wraps `MemoryRecord` + normalized `score: float`) |
| `src/stele/storage/memory_store/base.py` | Add `search_with_score(query, scope, source_ref_filter)` to the Protocol |
| `src/stele/storage/memory_store/memory.py` | Implement `search_with_score` (in-process) |
| `src/stele/storage/memory_store/sqlite.py` | Implement `search_with_score` (FTS5 rank + WHERE on source_refs) |
| `src/stele/storage/memory_store/postgres.py` | Implement `search_with_score` (tsvector rank + WHERE on source_refs jsonb) |
| `src/stele/storage/memory_store/mariadb.py` | `CapabilityError` stub matching Phase 1 pattern |
| `src/stele/storage/memory_store/clickhouse.py` | `CapabilityError` stub matching Phase 1 pattern |
| `src/stele/extraction/extractor.py` | Add `MemoryExtractor.preview(text, source_refs, scope) -> list[MemoryCandidate]` — pure core only, no storage |
| `src/stele/core/config.py` | Add `RecallConfig` model + `recall: RecallConfig` on `StashConfig` |
| `src/stele/core/stash.py` | Add `Stele.recall` property; extend `Stele.close()` to close `_recall` if initialized |
| `src/stele/__init__.py` | Re-export `RecallRequest`, `RecallResult`, `Citation`, `Escalation`, `RecallStats`, `RecallContext` |
| `benchmarks/answer_workflow.py` | `_run_strategy` delegates to `stele.recall(...)`; regression test asserts equivalence |

### Untouched (locked)

| Path | Why locked |
|---|---|
| `src/stele/core/artifact.py` | Artifact models are Phase 1's source of truth |
| `src/stele/storage/{memory,sqlite,postgres,mariadb,clickhouse}.py` (artifact stores) | Phase 1 contract |
| `src/stele/retrieval/*` | Existing artifact retrieval consumed via `Stele.search` — not modified |
| `src/stele/extraction/candidates.py`, `classifier.py`, `patterns.py` | Phase 2's pure core consumed via `MemoryExtractor.preview` |
| `src/stele/pii/*` | PII layer is consumed; recall never re-scrubs |

## Strategy Walkthroughs

Every strategy receives a `RecallRequest` plus a `_RecallDeps` struct
(memory facade, stele, scrubber, config) and returns a `RecallResult`.

### `SummaryOnlyStrategy`

**Requires `artifact_id`.** Resolves the artifact's stored summary
(set at `stele.store(...)` time, already PII-scrubbed). Returns a single
`Citation(kind="artifact", score=1.0, snippet=summary)`. Stats:
`fetches=1`, `estimated_context_tokens=estimate_tokens(summary)`.

### `MemorySearchStrategy`

Calls
`memory.search_with_score(query, scope, source_ref_filter=resolved_reference)`.
The filter is `None` when `artifact_id` is `None`, otherwise the resolved
`stele://<ns>/<id>` URI. Returns up to `max_memory_hits` citations with
`kind="memory"`, each carrying the memory's `MemoryRecord.id` as the
citation `id` and the memory's full `stele://` reference. Stats:
`memory_searches=1`.

### `ArtifactSearchStrategy`

- If `artifact_id is None`: calls `stele.search(query, limit=max_artifact_hits)`
  (Phase 1's global retrieval).
- If `artifact_id` is set: calls
  `stele.search(reference=resolved_reference, query, limit=max_artifact_hits)`
  — matches today's benchmark exactly.

Returns hits as `Citation(kind="chunk", ...)`. Stats: `artifact_searches=1`
(and `chunk_searches=1` if the underlying retrieval routes through the
chunk index).

### `GraphSearchStrategy`

Raises `CapabilityError("graph_search requires Phase 5 pg-raggraph adapter")`.
The stub exists so the public API + tests are stable across phases. No file
edits when Phase 5 lands — just swap the body.

### `RawFetchStrategy`

**Requires `artifact_id`.** Calls `stele.fetch(artifact_id, raw=True)`
— same path the benchmark uses today. Returns a single
`Citation(kind="artifact", score=1.0, snippet=content)`. `raw=True`
requires `pii.raw_fetch_enabled` in config; otherwise the existing
`PIIBlockedError` fires and propagates. Stats: `fetches=1`.

### `AbstainStrategy`

Always returns a `RecallResult` with:

```python
RecallResult(
    strategy_used="abstain",
    context="",
    citations=[],
    escalations=[Escalation(
        strategy="abstain",
        hit_count=0,
        top_score=None,
        reason="exhausted",
    )],
    pii_flags=[],
    stats=RecallStats(),
    abstained=True,
    abstain_reason=request.abstain_reason or config.abstain_default_reason,
)
```

Never raises. Callable explicitly or invoked as adaptive's last tier.

### `AdaptiveStrategy`

Composes the other strategies via an internal registry keyed by
`StrategyName`. Tier order is `RecallConfig.adaptive_tier_order` (default
below); each tier runs in sequence until a stop condition fires.

Default tier order:
```python
["memory_search", "artifact_search", "raw_fetch", "abstain"]
```

**When `artifact_id is None`** and
`adaptive_skip_raw_fetch_without_artifact_id=True` (default), the
`raw_fetch` tier is silently skipped.

For each tier:

1. Run the tier; capture its `RecallResult` and stats.
2. Append an `Escalation` row to a running list capturing
   `(strategy, hit_count, top_score, reason)`.
3. Decide whether to stop:
   - `hit_count >= 1` AND `top_score >= confidence_floor` →
     **stop**; reason=`tier_complete`.
   - If `sufficient` callback set, call it with accumulated
     `RecallContext`. If returns `True` → **stop**; else continue with
     reason=`sufficient_callback_false`.
   - `hit_count == 0` → continue with reason=`zero_hits`.
   - `hit_count >= 1` but `top_score < confidence_floor` → continue
     with reason=`below_floor`.
4. After all tiers exhausted → the last entry runs `AbstainStrategy`.

The returned `RecallResult.strategy_used` is the **terminating tier**
(not `"adaptive"`). `escalations` carries the full trail. Callers wanting
to know "did adaptive run?" check `len(escalations) > 1`. Stats are summed
across all tiers.

## Data Flow

```
CALLER
   │
   │ stele.recall(query="...", scope=alice, strategy="adaptive", artifact_id=None)
   ▼
Recall facade (callable)
   │ build RecallRequest
   │ dispatch on request.strategy → AdaptiveStrategy.execute(req, deps)
   ▼
AdaptiveStrategy.execute(request, deps)
   │
   │ ┌─── tier 1: MemorySearchStrategy ────────────────────┐
   │ │  memory.search_with_score(query, scope,             │
   │ │    source_ref_filter=None)                          │
   │ │  → list[ScoredMemoryHit]                            │
   │ │  → ranking.normalize_scores → Citations[kind=memory]│
   │ │  → check confidence_floor + sufficient callback     │
   │ │  → escalation row appended                          │
   │ └─────────────────────────────────────────────────────┘
   │   ↓ stop?
   │ ┌─── tier 2: ArtifactSearchStrategy ──────────────────┐
   │ │  stele.search(query, limit=5)                       │
   │ │  → list[SearchHit]                                  │
   │ │  → ranking.normalize_scores → Citations[kind=chunk] │
   │ │  → ranking.merge_hits with tier-1 citations         │
   │ │  → recheck                                          │
   │ └─────────────────────────────────────────────────────┘
   │   ↓ stop?
   │ ┌─── tier 3: RawFetchStrategy (skipped if no aid) ────┐
   │ │  stele.fetch(artifact_id, raw=True)                 │
   │ │  → Citation[kind=artifact]                          │
   │ │  → recheck                                          │
   │ └─────────────────────────────────────────────────────┘
   │   ↓ stop?
   │ ┌─── tier 4: AbstainStrategy ─────────────────────────┐
   │ │  return RecallResult(strategy_used="abstain", ...)  │
   │ └─────────────────────────────────────────────────────┘
   ▼
Build final RecallResult:
   • strategy_used = terminating tier (or "abstain")
   • context = "\n\n".join(c.snippet for c in citations) trimmed to max_context_chars
   • citations = accumulated, score-normalized, deduped
   • escalations = full trail
   • pii_flags = union of pii_flags from underlying surfaces (never re-scrubbed)
   • stats = summed across all tiers + total latency_ms
   ▼
RETURN to caller
```

### Invariants

- **No LLM call ever leaves Phase 3.** The `sufficient` callback is the
  only place the caller can choose to involve an LLM, and that's their
  decision — Phase 3 doesn't import or know about any LLM client.
- **PII scrubbing is inherited, not duplicated.** Memory hits come
  pre-scrubbed from Phase 1. Artifact search/fetch hits come pre-scrubbed
  from existing retrieval. Phase 3 never scrubs again — it collects
  `pii_flags` into the result.
- **Score normalization is centralized.** `ranking.normalize_scores(hits)`
  is the only place that knows how to convert per-backend raw scores
  (Postgres `ts_rank_cd`, SQLite FTS5 BM25, in-memory keyword match
  counts) into `[0, 1]`. Each strategy calls it; no strategy ever sees a
  raw score.

## Configuration

New section in `src/stele/core/config.py`:

```python
class RecallConfig(BaseModel):
    enabled: bool = True
    default_strategy: StrategyName = "adaptive"
    confidence_floor: float = 0.4
    max_memory_hits: int = 5
    max_artifact_hits: int = 5
    max_context_chars: int = 16_000
    adaptive_tier_order: list[StrategyName] = Field(
        default_factory=lambda: [
            "memory_search",
            "artifact_search",
            "raw_fetch",
            "abstain",
        ]
    )
    adaptive_skip_raw_fetch_without_artifact_id: bool = True
    abstain_default_reason: str = "no_sufficient_context"
```

Pydantic validators reject:
- `adaptive_tier_order` containing strategies that aren't in `StrategyName`.
- `adaptive_tier_order` without `"abstain"` as the final tier (abstain must
  always be the fallback).
- `confidence_floor` outside `[0.0, 1.0]`.

Defaults are picked so the existing benchmark scenarios pass without tuning.

## Error Handling

| Condition | Behavior |
|---|---|
| `recall.enabled = False` | `CapabilityError("recall is disabled in config")` |
| `strategy="summary_only"` without `artifact_id` | `ValidationError("summary_only requires artifact_id")` |
| `strategy="raw_fetch"` without `artifact_id` | `ValidationError("raw_fetch requires artifact_id")` |
| `strategy="graph_search"` (any context) | `CapabilityError("graph_search requires Phase 5 pg-raggraph adapter")` |
| Invalid `strategy` string | Pydantic `ValidationError` at request construction |
| `artifact_id` references a non-existent artifact | `ArtifactNotFound` propagated from underlying `Stele.fetch` |
| `raw_fetch` when `pii.raw_fetch_enabled=False` | `PIIBlockedError` propagated |
| Backend raises during memory search | `BackendError("memory search failed: <cause>")` re-raised. **Do not silently abstain.** |
| Backend raises during artifact search | `BackendError("artifact search failed: <cause>")` re-raised. |
| `sufficient` callback raises | `SteleError("sufficient callback raised: <cause>")` re-raised. Don't swallow caller bugs. |
| `adaptive` with empty `adaptive_tier_order` | Pydantic validator rejects at config load. |

**Why no automatic abstain on backend errors.** Silent abstention on a
backend failure would mask real outages. Callers wrap `stele.recall(...)`
in their own try/except if they want that policy — caller decision, not
policy decision.

## Success Criteria

- **SC-001:** `RecallRequest`, `RecallResult`, `Citation`, `Escalation`,
  `RecallStats`, `RecallContext`, `StrategyName` types exist with the
  fields specified above. Validated by `test_models.py`.
- **SC-002:** `ranking.normalize_scores(hits)` maps per-backend raw scores
  to `[0, 1]`. `ranking.merge_hits(*sources)` dedups by `(kind, id)`
  keeping max score. Verified by `test_ranking.py`.
- **SC-003:** `SummaryOnlyStrategy` returns the artifact's stored summary
  for valid `artifact_id`; raises `ValidationError` when missing. Verified
  by `test_summary_only.py`.
- **SC-004:** `MemorySearchStrategy` calls `Memory.search_with_score`
  with `source_ref_filter=resolved_reference` when `artifact_id` is set,
  `None` otherwise. Verified by `test_memory_search.py`.
- **SC-005:** `ArtifactSearchStrategy` uses global vs scoped search based
  on `artifact_id`. Verified by `test_artifact_search.py`.
- **SC-006:** `GraphSearchStrategy.execute(...)` always raises
  `CapabilityError`. Verified by `test_graph_search.py`.
- **SC-007:** `RawFetchStrategy` calls `stele.fetch(raw=True)`; requires
  `artifact_id`; propagates `PIIBlockedError`. Verified by
  `test_raw_fetch.py`.
- **SC-008:** `AbstainStrategy` returns `abstained=True`,
  `abstain_reason` populated from request or config default, never raises.
  Verified by `test_abstain.py`.
- **SC-009:** `AdaptiveStrategy` runs tiers in configured order;
  escalation trail records every tier with its `hit_count`, `top_score`,
  `reason`. Verified by `test_adaptive.py`.
- **SC-010:** `AdaptiveStrategy` stops on `hit_count >= 1` AND
  `top_score >= confidence_floor`. Verified by `test_adaptive.py`.
- **SC-011:** When `sufficient` callback set, `AdaptiveStrategy` calls it
  with accumulated `RecallContext` and respects its return value. Verified
  by `test_adaptive.py`.
- **SC-012:** `AdaptiveStrategy` skips `raw_fetch` tier when
  `artifact_id is None` and `adaptive_skip_raw_fetch_without_artifact_id=True`.
  Verified by `test_adaptive.py`.
- **SC-013:** Canonical `stele.recall(query=..., strategy="adaptive")`
  and shim `stele.recall.adaptive(query=...)` produce identical
  `RecallResult` for identical inputs. Verified by `test_facade.py`.
- **SC-014:** When `artifact_id` is set, every strategy (memory_search,
  artifact_search, raw_fetch, adaptive) scopes retrieval to that artifact.
  Verified by per-strategy tests + an integration assertion in the contract
  test.
- **SC-015:** `Memory.search_with_score(query, scope, source_ref_filter)`
  filter is pushed into the backend (SQLite WHERE, Postgres WHERE on jsonb
  source_refs). Verified by inspecting EXPLAIN plans in a backend-aware
  test, or by asserting that Python-side filtering is not performed
  (architectural check).
- **SC-016:** `MemoryExtractor.preview(text, source_refs, scope)` returns
  `list[MemoryCandidate]` from Phase 2's pure core without calling
  `Memory.add`. Verified by a memory-row-count-unchanged assertion.
- **SC-017:** Cross-backend contract test parametrized across
  `memory + sqlite + postgres` produces structurally equivalent
  `RecallResult` for the same input (same `strategy_used`, same
  `len(citations)`, same `abstained` flag). Verified by
  `test_recall_contract.py`.
- **SC-018:** `recall.enabled=False` causes `Stele.recall.*` to raise
  `CapabilityError`. Verified by an orchestrator test.
- **SC-019:** `RecallResult.pii_flags` is a union of flags from underlying
  surfaces; recall never modifies snippets. Verified by an integration
  test asserting `result.context` contains no PII patterns from the
  fixture set.
- **SC-020:** Benchmark migration: `_run_strategy` in
  `benchmarks/answer_workflow.py` delegates to `stele.recall(...)`. The
  five existing strategies produce structurally equivalent
  `WorkflowResult` rows for the existing fixtures. Accuracy delta on the
  deterministic judge is 0. Verified by
  `test_answer_workflow_via_recall.py`.

## Drift Checkpoints

- **⛔ DC-001** (after Tasks introduce all 6 real strategies): run
  ```
  grep -rn 'pg_raggraph\|chunkshop\|openai\|anthropic\|lede' src/stele/recall/
  ```
  Expected: empty. If anything matches, the slice has drifted into Phase
  4/5 territory, picked up an LLM client, or duplicated Phase 2 extraction
  logic.

- **⛔ DC-002** (after adaptive lands): run
  ```
  grep -rn '_answer_is_sufficient\|expected_answer' src/stele/recall/adaptive.py
  ```
  Expected: empty. Adaptive must escalate without oracle access.

- **⛔ DC-003** (after benchmark migration): run
  `test_answer_workflow_via_recall.py` — accuracy delta between old
  `_run_strategy` and new `stele.recall(...)` must be 0 on the
  deterministic judge across all five existing strategies.

- **⛔ DC-FINAL**: every SC-001..SC-020 has a passing test cited; the
  Out-of-Scope list is verified untouched.

## Out of Scope

- **Real `graph_search`.** Phase 3 ships the stub only. Phase 5 (pg-raggraph)
  implements it.
- **LLM-backed sufficiency by default.** The `sufficient` callback is
  optional and caller-supplied. Phase 3 does not provide a default
  LLM-judge implementation.
- **Vector search.** Phase 4 adds vector via Chunkshop. Phase 3 strategies
  use only the existing keyword retrieval surfaces.
- **Cross-artifact graph traversal.** Same as graph_search — Phase 5.
- **Caching / memoization of recall results.** Identical queries
  re-execute. Caching is a caller concern.
- **Multi-turn recall / session state.** Each `recall(...)` call is
  independent. Phase 6/7 may add session-aware variants.
- **Answer generation.** Phase 3 selects context; the caller prompts the
  LLM.
- **MariaDB / ClickHouse memory recall.** Phase 1's `CapabilityError`
  stubs continue to apply on `memory_search` for those backends.
- **CLI / MCP / LangChain integration.** Those are M7/M8 in the milestone
  plan.
- **Recall analytics dashboards.** Stats are returned per-call; aggregation
  is the caller's job.
- **Auto-tuning of `confidence_floor`.** Defaults are static. Phase 3
  doesn't learn from results.
- **Re-ranking via cross-encoders / rerankers.** Out of scope. Score
  normalization is purely transformation, not re-ranking.
- **Modifying existing artifact retrieval (`src/stele/retrieval/*`).**
  Phase 3 consumes `Stele.search` as-is.

## Testing Requirements Summary

| Suite | Path | Anchors |
|---|---|---|
| Models | `tests/unit/recall/test_models.py` | SC-001 |
| Ranking | `tests/unit/recall/test_ranking.py` | SC-002 |
| Strategy units (per strategy) | `tests/unit/recall/test_<strategy>.py` × 6 | SC-003..SC-008 |
| Adaptive | `tests/unit/recall/test_adaptive.py` | SC-009, SC-010, SC-011, SC-012 |
| Facade | `tests/unit/recall/test_facade.py` | SC-013, SC-018 |
| Forced scope | per-strategy + contract | SC-014 |
| Memory helper | `tests/unit/core/test_memory_search_with_score.py` | SC-015 |
| Extractor preview | `tests/unit/extraction/test_extractor.py` (extended) | SC-016 |
| Cross-backend | `tests/contract/test_recall_contract.py` | SC-017 |
| PII inheritance | `tests/unit/recall/test_pii_inheritance.py` | SC-019 |
| Benchmark migration | `tests/benchmarks_smoke/test_answer_workflow_via_recall.py` | SC-020 |
| Architecture | `tests/unit/recall/test_architecture.py` | DC-001 |

## Cross-References

- Phase 1 / Phase 2 source-of-truth files (consumed, mostly not modified):
  - `src/stele/core/memory.py` — `Memory.search`, `Memory.add`, plus the
    new `Memory.search_with_score` helper this phase adds.
  - `src/stele/core/memory_record.py` — `MemoryRecord`, `MemoryScope`,
    `MemoryQuery`, `MemoryKind`; plus the new `ScoredMemoryHit` this
    phase adds.
  - `src/stele/extraction/extractor.py` — `MemoryExtractor.extract_*`
    consumed; new `MemoryExtractor.preview` added here.
  - `src/stele/extraction/candidates.py` — pure core consumed via
    `preview`.
  - `src/stele/core/stash.py` — `Stele.fetch`, `Stele.search`, `Stele.memory`,
    `Stele.extract` consumed; new `Stele.recall` property added here.
- Strategy docs:
  - `docs/sovereign-memory-system-plan.md:622-628` — Phase 3 scope
  - `docs/prd-sovereign-stele.md:345-348` — Phase 3 summary
- Benchmark precedent:
  - `benchmarks/answer_workflow.py:483-577` — current `_run_strategy`
    (the code being lifted into `src/stele/recall/`)
- Phase 1 / Phase 2 plan / brief precedent for format and gate discipline:
  - `docs/superpowers/plans/2026-05-12-phase1-memory-supersession.md`
  - `docs/superpowers/plans/2026-05-13-phase2-deterministic-extraction.md`
  - `docs/superpowers/specs/2026-05-13-phase2-deterministic-extraction-design.md`
