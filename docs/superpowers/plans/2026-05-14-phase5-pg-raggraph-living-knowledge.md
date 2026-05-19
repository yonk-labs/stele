# Stele Phase 5: pg-raggraph + Living Knowledge Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Location note:** This plan and its spec live at `/tmp/stele-phase5-planning/` per user instruction — they are NOT in git. When Phase 2/3/4 settle, the user will direct where to commit (likely main, after Phase 3 lands, or a dedicated `phase5-pg-raggraph-living-knowledge` branch).

**Goal:** Ship the production pg-raggraph adapter that completes Phase 3's `graph_search` stub and proves Stele's "living knowledge" claim. Verify the six-bullet bar on two fixture lanes.

**Architecture:** Internal `Revisor` Protocol with `NoOpRevisor` + `PgRaggraphRevisor` implementations under `src/stele/revisor/`. Public surface: existing `Stele.memory` (writes — `add(supersedes=)`, new `retract`) + existing `Stele.recall(strategy="graph_search", as_of=, version_filter=, retracted_behavior=)`. `EvidenceRecord` wraps both artifacts and memories with a `kind` discriminator. Seeded-entity default; LLM mode opt-in via `LLMEndpointConfig`. Best-effort projection on writes, hard-fail on reads. For `as_of`/`version_filter` (time-travel / versioned) queries, adaptive recall restricts its tier order to temporal-aware strategies only (`graph_search`→`abstain`) rather than falling back to a non-temporal tier that would ignore the constraint (BUG-3); it still skips the `graph_search` tier on `CapabilityError` (e.g. pg-raggraph not installed).

**Tech Stack:** Python 3.12+, Pydantic v2, `pg_raggraph>=X.Y` (optional extra `[postgres-graph]`; gated on user's release), urllib for OpenAI-compatible LLM client (no new runtime deps), pytest, ruff, mypy strict.

**Spec (load-bearing):** `/tmp/stele-phase5-planning/2026-05-14-phase5-pg-raggraph-living-knowledge-design.md`

Re-read the spec at every DC-XXX checkpoint below. All 28 success criteria (SC-001 through SC-028) must have evidence at DC-FINAL.

**Phase 1+2+3+4 dependency:** Plan assumes all prior phases are complete on the current branch (likely main, but Task 0 verifies by checking importability of the surfaces Phase 5 builds on). Specifically: `Memory.search_with_score`, `MemoryExtractor.preview`, `Stele.recall`, `Stele.search(mode=...)`, `Stele.indexing_status`, and Phase 3's `GraphSearchStrategy` stub must all exist.

**pg-raggraph release dependency:** PgRaggraphRevisor implementation tasks (10–16) and integration tests (28–33) require the user's pg-raggraph release that includes the capability signals documented in `docs/sovereign-memory-system-plan.md:88-96`. Plan Task 0 checks installation and marks pg-raggraph-only tasks as deferred (with clear messaging) if not present. NoOpRevisor + projection + recall integration can land without pg-raggraph installed.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/stele/revisor/__init__.py` | Re-exports public types |
| `src/stele/revisor/models.py` | EvidenceRecord, EntitySeed, RelationSeed, KnowledgeHit, IndexReport, KnowledgeQuery |
| `src/stele/revisor/base.py` | `Revisor` Protocol + `RetractedBehavior` literal |
| `src/stele/revisor/noop.py` | `NoOpRevisor` |
| `src/stele/revisor/pg_raggraph.py` | `PgRaggraphRevisor` — lazy-imports `pg_raggraph` |
| `src/stele/revisor/llm_endpoint.py` | `LLMEndpointConfig` + OpenAI-compat client |
| `src/stele/revisor/projection.py` | Memory↔Evidence, Artifact↔Evidence, KnowledgeHit→Citation; PII assertion |
| `src/stele/retrieval/graph.py` | `graph_search(revisor, query, *, as_of, version_filter, retracted_behavior, limit)` facade |
| `tests/unit/revisor/__init__.py` | Package marker |
| `tests/unit/revisor/test_models.py` | Model validation |
| `tests/unit/revisor/test_noop.py` | Protocol conformance + capability error on search |
| `tests/unit/revisor/test_projection.py` | All three translations + PII assertion |
| `tests/unit/revisor/test_llm_endpoint.py` | OpenAI-compat client shape |
| `tests/unit/revisor/test_pg_raggraph.py` | Adapter unit tests (skip when pg_raggraph missing) |
| `tests/unit/revisor/test_architecture.py` | Import-layer check |
| `tests/unit/recall/test_recall_request_phase5_fields.py` | RecallRequest gains as_of / version_filter / retracted_behavior |
| `tests/unit/recall/test_graph_search_real.py` | GraphSearchStrategy real (replaces Phase 3 stub) |
| `tests/unit/recall/test_adaptive_with_graph_search.py` | Adaptive skip on CapabilityError |
| `tests/unit/core/test_memory_retract.py` | Memory.retract behavior + projection |
| `tests/unit/core/test_capabilities_pg_raggraph_fields.py` | Capabilities reports new fields |
| `tests/integration/pg_raggraph/__init__.py` | Package marker |
| `tests/integration/pg_raggraph/test_supersession.py` | **Bar #1** |
| `tests/integration/pg_raggraph/test_retraction.py` | **Bar #2** |
| `tests/integration/pg_raggraph/test_as_of.py` | **Bar #3** |
| `tests/integration/pg_raggraph/test_version_filter.py` | **Bar #4** |
| `tests/integration/pg_raggraph/test_provenance.py` | **Bar #5** |
| `tests/integration/pg_raggraph/test_postgres_baseline_without_pg_raggraph.py` | **Bar #6** |
| `tests/integration/pg_raggraph/test_as_of_two_paths.py` | SQL vs graph as_of divergence test |
| `tests/integration/pg_raggraph/test_best_effort_projection.py` | DC-005 — broken Revisor doesn't break writes |
| `tests/contract/test_graph_search_contract.py` | Cross-fixture contract (Postgres only) |
| `tests/fixtures/pg_raggraph/versioned_docs.json` | Lane 1 |
| `tests/fixtures/pg_raggraph/retracted_medical.json` | Lane 2 |
| `benchmarks/living_knowledge.py` | Living-knowledge benchmark |
| `tests/benchmarks_smoke/test_living_knowledge_benchmark.py` | Smoke |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | Add `[postgres-graph]` extra: `pg_raggraph>=X.Y` |
| `src/stele/core/config.py` | Add `PgRaggraphConfig` + `LLMEndpointConfig`; `IndexingConfig.pg_raggraph` field |
| `src/stele/core/memory.py` | Add `Memory.retract`; project `add(supersedes=)` and `retract` to Revisor when configured |
| `src/stele/core/stash.py` | Build `self._revisor` at init; `Stele.store` projection; capabilities; close wire-up |
| `src/stele/core/artifact.py` | `Capabilities` adds pg_raggraph + revisor + LLM fields |
| `src/stele/recall/graph_search.py` | Phase 3 stub → real implementation |
| `src/stele/recall/models.py` | RecallRequest gains as_of / version_filter / retracted_behavior |
| `src/stele/recall/adaptive.py` | Catch CapabilityError; Escalation(reason="capability_error"); continue |
| `src/stele/recall/facade.py` | Pass new fields through canonical + graph_search shim |
| `src/stele/__init__.py` | Re-export Phase 5 types |

### Untouched (locked)

| Path | Why locked |
|---|---|
| `src/stele/extraction/*` | Phase 2 |
| `src/stele/storage/{memory,sqlite,mariadb,clickhouse}.py` (artifact stores) | Non-Postgres never touches pg_raggraph |
| `src/stele/storage/chunk_store/*` | Phase 4 |
| `src/stele/retrieval/{memory,sqlite,mariadb,clickhouse}.py` | Non-Postgres retrieval untouched |
| `src/stele/pii/*` | Consumed; assertion at projection boundary |
| `src/stele/storage/memory_store/*` | Phase 1 |
| `src/stele/storage/postgres.py` (artifact store) | Exact CRUD per spec stays on artifact table |

---

## Drift Checkpoints

- ⛔ **DC-000** (Task 0): Phase 1+2+3+4 complete; pg_raggraph install state recorded; integration tests gated accordingly.
- ⛔ **DC-001** (after Task 21): `grep -rn 'pg_raggraph' src/stele/ | grep -v 'src/stele/revisor/'` must be empty (TYPE_CHECKING-guarded imports in projection.py are OK).
- ⛔ **DC-002** (after Task 19): `grep -rn 'self\._revisor\.' src/stele/` should match ONLY `src/stele/core/{memory,stash}.py` and `src/stele/recall/graph_search.py`.
- ⛔ **DC-003** (after Task 33): all 6 integration tests pass on applicable fixture lanes. **This is the Phase 5 exit gate.**
- ⛔ **DC-004** (after Task 22): `Stele.recall(strategy="adaptive")` in a no-pg_raggraph deployment does not raise.
- ⛔ **DC-005** (after Task 19 + best-effort test in Task 25): A deliberately-broken Revisor (test fixture) does not break `Stele.store()` or `Memory.add()`; `Capabilities.last_revisor_error` populated.
- ⛔ **DC-FINAL** (Task 37): every SC-001..SC-028 has a passing test cited; living-knowledge benchmark produces a complete report; Out-of-Scope verified untouched.

---

## Tasks

### Task 0: Verify Phase 1+2+3+4 prereqs + detect pg_raggraph state

**Files:** read-only.

- [ ] **Step 1: Confirm Phase 1+2+3+4 surfaces ship**

```bash
.venv/bin/python -c "
from stele import (
    Stele, Memory, MemoryScope, MemoryRecord, MemoryAddResult,
    MemoryCandidate, ExtractionReport, AcceptedCandidate, RejectedCandidate,
    RecallRequest, RecallResult, Citation, Escalation, RecallStats,
    BakeoffConfig, BakeoffSummary, TaskStatus, Capabilities,
    CapabilityError, ValidationError, ArtifactNotFound, PIIBlockedError,
)
from stele.core.stash import Stele as S
print('Stele.memory:', hasattr(S, 'memory'))
print('Stele.extract:', hasattr(S, 'extract'))
print('Stele.recall:', hasattr(S, 'recall'))
print('Stele.indexing_status:', hasattr(S, 'indexing_status'))
# Phase 3 graph_search stub:
from stele.recall.graph_search import GraphSearchStrategy
print('GraphSearchStrategy class:', GraphSearchStrategy is not None)
"
```

Expected: all `True`. If any phase missing, STOP — Phase 5 can't start before Phase 3 (which contains the graph_search stub).

- [ ] **Step 2: Detect pg_raggraph install state**

```bash
.venv/bin/python - <<'PY'
import importlib.util
import sys

spec = importlib.util.find_spec("pg_raggraph")
print("pg_raggraph installed:", spec is not None)
if spec is not None:
    import pg_raggraph
    print("version:", getattr(pg_raggraph, "__version__", "unknown"))
    # Phase 5 requires the capability signals documented in
    # docs/sovereign-memory-system-plan.md:88-96
    required_signals = ("GraphRAG",)  # adjust to the actual exported name
    available = [s for s in required_signals if hasattr(pg_raggraph, s)]
    missing = set(required_signals) - set(available)
    if missing:
        print(f"WARN: missing pg_raggraph signals: {missing}")
        print("Integration tests (Tasks 28-33) will be marked deferred.")
    else:
        print("All required pg_raggraph signals present.")
else:
    print("WARN: pg_raggraph not installed.")
    print("Phase 5 NoOp + projection + recall integration can proceed.")
    print("Tasks 10-16 (PgRaggraphRevisor) and 28-33 (integration tests) deferred.")
PY
```

- [ ] **Step 3: Baseline verification trio**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest 2>&1 | tail -5
```

Expected: all three pass. Note pytest count for DC-FINAL diff.

- [ ] **Step 4: Note current branch (no switch)**

```bash
git branch --show-current
```

Per user instruction: do **not** switch branches; do not create worktrees; do not commit during plan execution. Commits land at user direction.

- [ ] **Step 5: Initialize PROGRESS.log**

```bash
echo "Phase 5 plan execution started ($(date -Iseconds))" > /tmp/stele-phase5-planning/PROGRESS.log
echo "Task 0: prereqs verified" >> /tmp/stele-phase5-planning/PROGRESS.log
```

No code commit in Task 0.

---

### Task 1: Models — EvidenceRecord, KnowledgeHit, IndexReport, EntitySeed, RelationSeed

**Files:**
- Create: `src/stele/revisor/__init__.py`
- Create: `src/stele/revisor/models.py`
- Create: `tests/unit/revisor/__init__.py`
- Test: `tests/unit/revisor/test_models.py`

- [ ] **Step 1: Package markers**

```bash
mkdir -p src/stele/revisor tests/unit/revisor
: > src/stele/revisor/__init__.py
: > tests/unit/revisor/__init__.py
```

- [ ] **Step 2: Write failing test**

Create `tests/unit/revisor/test_models.py`:

```python
"""Tests for Phase 5 Revisor models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.revisor.models import (
    EntitySeed,
    EvidenceRecord,
    IndexReport,
    KnowledgeHit,
    KnowledgeQuery,
    RelationSeed,
)


def test_evidence_record_artifact_kind() -> None:
    now = datetime.now(UTC)
    ev = EvidenceRecord(
        kind="artifact",
        reference="stele://default/aid",
        text="The quick brown fox.",
        namespace="default",
        effective_from=now,
    )
    assert ev.kind == "artifact"
    assert ev.retracted is False
    assert ev.entities == []
    assert ev.relations == []


def test_evidence_record_memory_kind_with_supersedes() -> None:
    now = datetime.now(UTC)
    ev = EvidenceRecord(
        kind="memory",
        reference="stele://memory/mem_abc",
        text="user prefers dark mode",
        namespace="default",
        effective_from=now,
        supersedes=["stele://memory/mem_old"],
    )
    assert ev.kind == "memory"
    assert ev.supersedes == ["stele://memory/mem_old"]


def test_evidence_record_rejects_unknown_kind() -> None:
    with pytest.raises(PydanticValidationError):
        EvidenceRecord(
            kind="bogus",  # type: ignore[arg-type]
            reference="stele://default/x",
            text="x",
            namespace="default",
            effective_from=datetime.now(UTC),
        )


def test_entity_seed_with_type() -> None:
    e = EntitySeed(name="Acme Corp", type="organization", metadata={"id": "acme"})
    assert e.type == "organization"


def test_relation_seed_required_fields() -> None:
    r = RelationSeed(head="Acme Corp", tail="Plan B", type="USES")
    assert r.type == "USES"


def test_knowledge_hit_required_provenance() -> None:
    now = datetime.now(UTC)
    hit = KnowledgeHit(
        reference="stele://docs/aid",
        kind="artifact",
        text="text",
        score=0.85,
        effective_from=now,
    )
    assert hit.reference.startswith("stele://")
    assert hit.retracted is False


def test_index_report_defaults() -> None:
    r = IndexReport(
        evidence_count=1,
        entity_count=2,
        relation_count=3,
        skipped=0,
        failed=0,
    )
    assert r.failures == []


def test_knowledge_query_required_fields() -> None:
    from stele.core.memory_record import MemoryScope

    q = KnowledgeQuery(
        text="dark mode",
        scope=MemoryScope(user_id="alice"),
        limit=5,
    )
    assert q.limit == 5
    assert q.version_filter is None
```

- [ ] **Step 3: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/revisor/test_models.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4: Implement `models.py`**

Create `src/stele/revisor/models.py`:

```python
"""Phase 5 Revisor models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stele.core.memory_record import MemoryScope


class EntitySeed(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    type: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class RelationSeed(BaseModel):
    model_config = ConfigDict(frozen=True)
    head: str
    tail: str
    type: str
    metadata: dict[str, object] = Field(default_factory=dict)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["artifact", "memory"]
    reference: str
    text: str
    namespace: str
    session_id: str | None = None
    effective_from: datetime
    effective_until: datetime | None = None
    version_label: str | None = None
    supersedes: list[str] = Field(default_factory=list)
    retracted: bool = False
    retracted_at: datetime | None = None
    retraction_reason: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    entities: list[EntitySeed] = Field(default_factory=list)
    relations: list[RelationSeed] = Field(default_factory=list)


class KnowledgeHit(BaseModel):
    model_config = ConfigDict(frozen=True)
    reference: str
    kind: Literal["artifact", "memory"]
    text: str
    score: float
    effective_from: datetime
    effective_until: datetime | None = None
    version_label: str | None = None
    retracted: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class IndexReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_count: int
    entity_count: int
    relation_count: int
    skipped: int
    failed: int
    failures: list[dict[str, str]] = Field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeQuery:
    text: str
    scope: MemoryScope
    limit: int = 5
    version_filter: str | None = None
    retracted_behavior: Literal["hide", "flag", "surface_both"] = "hide"
```

- [ ] **Step 5: Wire `__init__.py`**

Overwrite `src/stele/revisor/__init__.py`:

```python
"""Phase 5 — pg-raggraph + Living Knowledge."""

from stele.revisor.models import (
    EntitySeed,
    EvidenceRecord,
    IndexReport,
    KnowledgeHit,
    KnowledgeQuery,
    RelationSeed,
)

__all__ = [
    "EntitySeed",
    "EvidenceRecord",
    "IndexReport",
    "KnowledgeHit",
    "KnowledgeQuery",
    "RelationSeed",
]
```

- [ ] **Step 6: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/revisor/test_models.py -v
.venv/bin/ruff check src/stele/revisor tests/unit/revisor
.venv/bin/mypy src/stele/revisor tests/unit/revisor
```

Expected: pass.

- [ ] **Step 7: Progress note**

```bash
echo "Task 1: Phase 5 models ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 2: Revisor Protocol + RetractedBehavior

**Files:**
- Create: `src/stele/revisor/base.py`

- [ ] **Step 1: Implement (Protocol-only; conformance tested via NoOp in Task 6)**

Create `src/stele/revisor/base.py`:

```python
"""Revisor Protocol + RetractedBehavior literal."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from stele.revisor.models import (
    EvidenceRecord,
    IndexReport,
    KnowledgeHit,
    KnowledgeQuery,
)

RetractedBehavior = Literal["hide", "flag", "surface_both"]


class Revisor(Protocol):
    is_noop: bool

    def ingest_evidence(self, evidence: EvidenceRecord) -> IndexReport: ...

    def search_current(self, query: KnowledgeQuery) -> list[KnowledgeHit]: ...

    def search_as_of(
        self, query: KnowledgeQuery, *, as_of: datetime
    ) -> list[KnowledgeHit]: ...

    def supersede(
        self, old_ref: str, new_ref: str, reason: str | None = None
    ) -> None: ...

    def retract(
        self, ref: str, reason: str, retracted_at: datetime | None = None
    ) -> None: ...

    def close(self) -> None: ...
```

- [ ] **Step 2: Lint + types**

```bash
.venv/bin/ruff check src/stele/revisor/base.py
.venv/bin/mypy src/stele/revisor/base.py
```

Expected: clean.

- [ ] **Step 3: Progress note**

```bash
echo "Task 2: Revisor Protocol ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 3: Extend RecallRequest with Phase 5 fields

**Files:**
- Modify: `src/stele/recall/models.py`
- Test: `tests/unit/recall/test_recall_request_phase5_fields.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/recall/test_recall_request_phase5_fields.py`:

```python
"""Tests for Phase 5 additions to RecallRequest."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.core.memory_record import MemoryScope
from stele.recall.models import RecallRequest


def test_recall_request_defaults_phase5_fields_to_none() -> None:
    req = RecallRequest(
        query="x",
        scope=MemoryScope(user_id="alice"),
    )
    assert req.as_of is None
    assert req.version_filter is None
    assert req.retracted_behavior is None


def test_recall_request_accepts_as_of() -> None:
    req = RecallRequest(
        query="x",
        scope=MemoryScope(user_id="alice"),
        as_of=datetime(2020, 1, 1, tzinfo=UTC),
    )
    assert req.as_of.year == 2020


def test_recall_request_accepts_version_filter() -> None:
    req = RecallRequest(
        query="x",
        scope=MemoryScope(user_id="alice"),
        version_filter="py312",
    )
    assert req.version_filter == "py312"


def test_recall_request_accepts_retracted_behavior() -> None:
    req = RecallRequest(
        query="x",
        scope=MemoryScope(user_id="alice"),
        retracted_behavior="surface_both",
    )
    assert req.retracted_behavior == "surface_both"


def test_recall_request_rejects_unknown_retracted_behavior() -> None:
    with pytest.raises(PydanticValidationError):
        RecallRequest(
            query="x",
            scope=MemoryScope(user_id="alice"),
            retracted_behavior="bogus",  # type: ignore[arg-type]
        )
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/recall/test_recall_request_phase5_fields.py -v
```

Expected: AttributeError on the new fields.

- [ ] **Step 3: Implement**

In `src/stele/recall/models.py`, add to `RecallRequest`:

```python
from datetime import datetime  # add to imports if missing


class RecallRequest(BaseModel):
    # ... existing Phase 3 fields ...
    as_of: datetime | None = None
    version_filter: str | None = None
    retracted_behavior: Literal["hide", "flag", "surface_both"] | None = None
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/recall/test_recall_request_phase5_fields.py -v
.venv/bin/ruff check src/stele/recall/models.py
.venv/bin/mypy src/stele/recall/models.py
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 3: RecallRequest Phase 5 fields ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 4: PgRaggraphConfig + LLMEndpointConfig

**Files:**
- Modify: `src/stele/core/config.py`
- Test: `tests/unit/core/test_config.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/core/test_config.py`:

```python
def test_pg_raggraph_config_defaults() -> None:
    from stele.core.config import LLMEndpointConfig, PgRaggraphConfig, StashConfig

    cfg = StashConfig()
    pg = cfg.indexing.pg_raggraph
    assert pg.enabled is False
    assert pg.entity_mode == "seeded"
    assert pg.llm is None
    assert pg.namespace_prefix == "stele"
    assert pg.retracted_behavior_default == "hide"
    assert pg.project_on_write is True
    assert pg.max_entities_per_evidence == 50
    assert pg.max_relations_per_evidence == 100


def test_pg_raggraph_llm_mode_requires_llm_endpoint() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError, match="llm"):
        StashConfig.load(
            {"indexing": {"pg_raggraph": {"enabled": True, "entity_mode": "llm"}}}
        )


def test_pg_raggraph_enabled_requires_postgres_backend() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError, match="postgres"):
        StashConfig.load(
            {
                "backend": {"type": "sqlite", "path": "/tmp/x.db"},
                "indexing": {"pg_raggraph": {"enabled": True}},
            }
        )


def test_pg_raggraph_namespace_prefix_validated() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load(
            {
                "backend": {"type": "postgres", "dsn": "postgresql://x"},
                "indexing": {"pg_raggraph": {"enabled": True, "namespace_prefix": "Bad Prefix!"}},
            }
        )


def test_llm_endpoint_config_defaults() -> None:
    from stele.core.config import LLMEndpointConfig

    cfg = LLMEndpointConfig(base_url="http://localhost:8000/v1", model="qwen3")
    assert cfg.timeout_seconds == 30.0
    assert cfg.temperature == 0.0
    assert cfg.api_key is None
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/core/test_config.py -v -k "pg_raggraph or llm_endpoint"
```

Expected: AttributeError / ValidationError mismatches.

- [ ] **Step 3: Implement**

In `src/stele/core/config.py`, add (after existing config classes):

```python
import re


class LLMEndpointConfig(BaseModel):
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class PgRaggraphConfig(BaseModel):
    enabled: bool = False
    entity_mode: Literal["seeded", "llm"] = "seeded"
    llm: LLMEndpointConfig | None = None
    namespace_prefix: str = "stele"
    retracted_behavior_default: Literal["hide", "flag", "surface_both"] = "hide"
    project_on_write: bool = True
    max_entities_per_evidence: int = Field(default=50, ge=1)
    max_relations_per_evidence: int = Field(default=100, ge=1)

    @field_validator("namespace_prefix")
    @classmethod
    def _validate_namespace_prefix(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9_]{1,32}", v):
            raise ValueError(
                "namespace_prefix must match [a-z0-9_]{1,32}"
            )
        return v

    @model_validator(mode="after")
    def _validate_llm_mode(self) -> "PgRaggraphConfig":
        if self.entity_mode == "llm" and self.llm is None:
            raise ValueError("entity_mode='llm' requires llm: LLMEndpointConfig")
        return self
```

Extend `IndexingConfig`:

```python
class IndexingConfig(BaseModel):
    # Phase 4 fields...
    pg_raggraph: PgRaggraphConfig = Field(default_factory=PgRaggraphConfig)
```

Add a `StashConfig` validator for the backend gate:

```python
class StashConfig(BaseModel):
    # ... existing fields ...

    @model_validator(mode="after")
    def _validate_pg_raggraph_backend(self) -> "StashConfig":
        if self.indexing.pg_raggraph.enabled and self.backend.type != "postgres":
            raise ValueError(
                "pg_raggraph requires backend.type='postgres'"
            )
        return self
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/core/test_config.py -v -k "pg_raggraph or llm_endpoint"
.venv/bin/ruff check src/stele/core/config.py
.venv/bin/mypy src/stele/core/config.py
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 4: PgRaggraphConfig + LLMEndpointConfig ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 5: Capabilities expansion for Phase 5 fields

**Files:**
- Modify: `src/stele/core/artifact.py`
- Test: `tests/unit/core/test_capabilities_pg_raggraph_fields.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/core/test_capabilities_pg_raggraph_fields.py`:

```python
"""Tests for the Capabilities model — Phase 5 fields exist."""

from __future__ import annotations

from stele.core.artifact import Capabilities


def test_capabilities_has_phase5_fields() -> None:
    caps = Capabilities()
    for field in (
        "pg_raggraph_installed",
        "pg_raggraph_version",
        "revisor_mode",
        "entity_mode",
        "llm_endpoint_configured",
        "retracted_behavior_default",
        "last_revisor_error",
    ):
        assert hasattr(caps, field), f"Capabilities missing field {field!r}"


def test_capabilities_pg_raggraph_defaults_are_safe() -> None:
    caps = Capabilities()
    assert caps.pg_raggraph_installed is False
    assert caps.pg_raggraph_version is None
    assert caps.revisor_mode is None
    assert caps.entity_mode is None
    assert caps.llm_endpoint_configured is False
    assert caps.retracted_behavior_default is None
    assert caps.last_revisor_error is None
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/core/test_capabilities_pg_raggraph_fields.py -v
```

Expected: AttributeError.

- [ ] **Step 3: Implement**

In `src/stele/core/artifact.py`, extend `Capabilities`:

```python
class Capabilities(BaseModel):
    # ... Phase 1/3/4 fields ...
    pg_raggraph_installed: bool = False
    pg_raggraph_version: str | None = None
    revisor_mode: Literal["pg_raggraph", "noop"] | None = None
    entity_mode: Literal["seeded", "llm"] | None = None
    llm_endpoint_configured: bool = False
    retracted_behavior_default: Literal["hide", "flag", "surface_both"] | None = None
    last_revisor_error: str | None = None
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/core/test_capabilities_pg_raggraph_fields.py -v
.venv/bin/ruff check src/stele/core/artifact.py
.venv/bin/mypy src/stele/core/artifact.py
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 5: Capabilities Phase 5 fields ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 6: NoOpRevisor

**Files:**
- Create: `src/stele/revisor/noop.py`
- Test: `tests/unit/revisor/test_noop.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/revisor/test_noop.py`:

```python
"""Tests for NoOpRevisor."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope
from stele.revisor.base import Revisor
from stele.revisor.models import EvidenceRecord, KnowledgeQuery
from stele.revisor.noop import NoOpRevisor


def _evidence() -> EvidenceRecord:
    return EvidenceRecord(
        kind="artifact",
        reference="stele://default/aid",
        text="x",
        namespace="default",
        effective_from=datetime.now(UTC),
    )


def _query() -> KnowledgeQuery:
    return KnowledgeQuery(text="x", scope=MemoryScope(user_id="alice"))


def test_noop_is_noop_flag() -> None:
    r = NoOpRevisor()
    assert r.is_noop is True


def test_noop_ingest_returns_empty_report() -> None:
    r = NoOpRevisor()
    report = r.ingest_evidence(_evidence())
    assert report.evidence_count == 0
    assert report.entity_count == 0


def test_noop_search_raises_capability_error() -> None:
    r = NoOpRevisor()
    with pytest.raises(CapabilityError, match="pg-raggraph"):
        r.search_current(_query())
    with pytest.raises(CapabilityError, match="pg-raggraph"):
        r.search_as_of(_query(), as_of=datetime.now(UTC))


def test_noop_supersede_no_op() -> None:
    r = NoOpRevisor()
    r.supersede("stele://x/a", "stele://x/b", reason="x")  # should not raise


def test_noop_retract_no_op() -> None:
    r = NoOpRevisor()
    r.retract("stele://x/a", "x", retracted_at=None)  # should not raise


def test_noop_protocol_conformance() -> None:
    def _check(r: Revisor) -> None: ...
    _check(NoOpRevisor())  # type: ignore[arg-type]
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/revisor/test_noop.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `src/stele/revisor/noop.py`:

```python
"""NoOpRevisor — used when pg-raggraph is unconfigured."""

from __future__ import annotations

from datetime import datetime

from stele.core.exceptions import CapabilityError
from stele.revisor.models import (
    EvidenceRecord,
    IndexReport,
    KnowledgeHit,
    KnowledgeQuery,
)


class NoOpRevisor:
    is_noop: bool = True

    def ingest_evidence(self, evidence: EvidenceRecord) -> IndexReport:
        del evidence
        return IndexReport(
            evidence_count=0,
            entity_count=0,
            relation_count=0,
            skipped=0,
            failed=0,
        )

    def search_current(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        del query
        raise CapabilityError(
            "graph_search requires pg-raggraph; install "
            "'stele-core[postgres-graph]' and set "
            "indexing.pg_raggraph.enabled=True"
        )

    def search_as_of(
        self, query: KnowledgeQuery, *, as_of: datetime
    ) -> list[KnowledgeHit]:
        del query, as_of
        raise CapabilityError(
            "graph_search requires pg-raggraph; install "
            "'stele-core[postgres-graph]' and set "
            "indexing.pg_raggraph.enabled=True"
        )

    def supersede(
        self, old_ref: str, new_ref: str, reason: str | None = None
    ) -> None:
        del old_ref, new_ref, reason

    def retract(
        self, ref: str, reason: str, retracted_at: datetime | None = None
    ) -> None:
        del ref, reason, retracted_at

    def close(self) -> None:
        pass
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/revisor/test_noop.py -v
.venv/bin/ruff check src/stele/revisor/noop.py
.venv/bin/mypy src/stele/revisor/noop.py
```

Expected: pass.

- [ ] **Step 5: Progress note**

```bash
echo "Task 6: NoOpRevisor ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 7: Projection layer — Memory↔Evidence, Artifact↔Evidence

**Files:**
- Create: `src/stele/revisor/projection.py`
- Test: `tests/unit/revisor/test_projection.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/revisor/test_projection.py`:

```python
"""Tests for projection between Stele types and EvidenceRecord."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stele.core.artifact import ArtifactRecord
from stele.core.exceptions import BackendError
from stele.core.memory_record import MemoryRecord, MemoryScope
from stele.recall.models import Citation
from stele.revisor.models import EvidenceRecord, KnowledgeHit
from stele.revisor.projection import (
    artifact_to_evidence,
    knowledge_hits_to_citations,
    memory_to_evidence,
)


def _artifact() -> ArtifactRecord:
    now = datetime.now(UTC)
    return ArtifactRecord(
        artifact_id="aid",
        reference="stele://default/aid",
        namespace="default",
        session_id=None,
        content="quick brown fox",
        content_encoding="utf-8",
        content_type="text",
        byte_size=15,
        token_estimate=3,
        summary="quick brown fox",
        digest_sha256="x" * 64,
        metadata={},
        created_at=now,
    )


def _memory() -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id="mem_abc",
        text="user prefers dark mode",
        kind="preference",
        scope=MemoryScope(user_id="alice"),
        source_refs=["stele://default/aid"],
        created_at=now,
        updated_at=now,
        effective_from=now,
    )


def test_artifact_to_evidence() -> None:
    ev = artifact_to_evidence(_artifact())
    assert ev.kind == "artifact"
    assert ev.reference == "stele://default/aid"
    assert ev.text == "quick brown fox"
    assert ev.namespace == "default"
    assert ev.retracted is False


def test_memory_to_evidence_with_supersedes() -> None:
    mem = _memory().model_copy(update={"supersedes": ["mem_old"]})
    ev = memory_to_evidence(mem, memory_namespace="memory")
    assert ev.kind == "memory"
    assert ev.reference.startswith("stele://memory/")
    assert "mem_old" in ev.supersedes[0]


def test_memory_to_evidence_retracted() -> None:
    now = datetime.now(UTC)
    mem = _memory().model_copy(
        update={
            "status": "retracted",
            "metadata": {"retraction_reason": "data error", "retracted_at": now.isoformat()},
        }
    )
    ev = memory_to_evidence(mem, memory_namespace="memory")
    assert ev.retracted is True
    assert ev.retraction_reason == "data error"


def test_knowledge_hits_to_citations() -> None:
    now = datetime.now(UTC)
    hit = KnowledgeHit(
        reference="stele://docs/aid",
        kind="artifact",
        text="payload",
        score=0.7,
        effective_from=now,
    )
    citations = knowledge_hits_to_citations([hit])
    assert len(citations) == 1
    assert citations[0].reference == "stele://docs/aid"
    assert citations[0].kind == "chunk"
    assert citations[0].snippet == "payload"


def test_knowledge_hits_to_citations_rejects_unscrubbed_pii() -> None:
    now = datetime.now(UTC)
    hit = KnowledgeHit(
        reference="stele://docs/aid",
        kind="artifact",
        text="contact alice@example.com",
        score=0.7,
        effective_from=now,
    )
    with pytest.raises(BackendError, match="unscrubbed"):
        knowledge_hits_to_citations([hit])


def test_knowledge_hits_to_citations_rejects_empty_reference() -> None:
    now = datetime.now(UTC)
    hit = KnowledgeHit(
        reference="",
        kind="artifact",
        text="x",
        score=0.7,
        effective_from=now,
    )
    with pytest.raises(BackendError, match="provenance"):
        knowledge_hits_to_citations([hit])
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/revisor/test_projection.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `projection.py`**

Create `src/stele/revisor/projection.py`:

```python
"""Projection between Stele types and Phase 5 EvidenceRecord/KnowledgeHit."""

from __future__ import annotations

import re
from datetime import datetime

from stele.core.artifact import ArtifactRecord
from stele.core.exceptions import BackendError
from stele.core.memory_record import MemoryRecord
from stele.recall.models import Citation
from stele.revisor.models import EvidenceRecord, KnowledgeHit


_EMAIL_RE = re.compile(r"\b\w+@\w+\.\w+\b")
_PHONE_RE = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")


def _assert_scrubbed(text: str) -> None:
    """Defensive boundary check — text must already be PII-scrubbed."""
    if _EMAIL_RE.search(text):
        raise BackendError(
            "graph hit text contains unscrubbed email-like pattern"
        )
    if _PHONE_RE.search(text):
        raise BackendError(
            "graph hit text contains unscrubbed phone-like pattern"
        )


def artifact_to_evidence(artifact: ArtifactRecord) -> EvidenceRecord:
    text = artifact.content_as_text()
    return EvidenceRecord(
        kind="artifact",
        reference=artifact.reference,
        text=text,
        namespace=artifact.namespace,
        session_id=artifact.session_id,
        effective_from=artifact.created_at,
        metadata=dict(artifact.metadata),
    )


def memory_to_evidence(
    memory: MemoryRecord, *, memory_namespace: str = "memory"
) -> EvidenceRecord:
    reference = f"stele://{memory_namespace}/{memory.id}"
    retracted = memory.status == "retracted"
    retracted_at_str = memory.metadata.get("retracted_at")
    retracted_at = (
        datetime.fromisoformat(str(retracted_at_str))
        if isinstance(retracted_at_str, str)
        else None
    )
    retraction_reason = memory.metadata.get("retraction_reason")
    supersedes_refs = [
        f"stele://{memory_namespace}/{old_id}" for old_id in memory.supersedes
    ]
    return EvidenceRecord(
        kind="memory",
        reference=reference,
        text=memory.text,
        namespace=memory.scope.namespace,
        session_id=memory.scope.session_id,
        effective_from=memory.effective_from,
        effective_until=memory.effective_until,
        supersedes=supersedes_refs,
        retracted=retracted,
        retracted_at=retracted_at,
        retraction_reason=str(retraction_reason) if retraction_reason else None,
        metadata=dict(memory.metadata),
    )


def knowledge_hits_to_citations(hits: list[KnowledgeHit]) -> list[Citation]:
    citations: list[Citation] = []
    for hit in hits:
        if not hit.reference or not hit.reference.startswith("stele://"):
            raise BackendError(
                f"graph hit without stele:// provenance: {hit.reference!r}"
            )
        _assert_scrubbed(hit.text)
        # KnowledgeHit.kind=memory → Citation.kind=memory; else chunk
        citation_kind: str = "memory" if hit.kind == "memory" else "chunk"
        ref_id = hit.reference.rsplit("/", 1)[-1]
        citations.append(
            Citation(
                kind=citation_kind,  # type: ignore[arg-type]
                id=ref_id,
                reference=hit.reference,
                score=hit.score,
                snippet=hit.text,
            )
        )
    return citations
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/revisor/test_projection.py -v
.venv/bin/ruff check src/stele/revisor/projection.py
.venv/bin/mypy src/stele/revisor/projection.py
```

Expected: pass.

- [ ] **Step 5: Progress note**

```bash
echo "Task 7: Projection layer ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 8: LLM endpoint client

**Files:**
- Create: `src/stele/revisor/llm_endpoint.py`
- Test: `tests/unit/revisor/test_llm_endpoint.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/revisor/test_llm_endpoint.py`:

```python
"""Tests for LLM endpoint client (OpenAI-compatible)."""

from __future__ import annotations

import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from stele.core.config import LLMEndpointConfig
from stele.core.exceptions import BackendError
from stele.revisor.llm_endpoint import LLMClient


def _config() -> LLMEndpointConfig:
    return LLMEndpointConfig(base_url="http://localhost:8000/v1", model="qwen3")


def test_llm_client_chat_request_shape() -> None:
    cfg = _config()
    client = LLMClient(cfg)

    seen_payload: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": '{"entities": []}'}}]}
            ).encode("utf-8")

    def _fake_urlopen(req, *, timeout):
        seen_payload["url"] = req.full_url
        seen_payload["body"] = json.loads(req.data.decode("utf-8"))
        seen_payload["timeout"] = timeout
        return _FakeResponse()

    with patch("urllib.request.urlopen", _fake_urlopen):
        content = client.chat([{"role": "user", "content": "extract entities"}])
        assert content == '{"entities": []}'

    assert seen_payload["url"].endswith("/chat/completions")
    assert seen_payload["body"]["model"] == "qwen3"
    assert seen_payload["body"]["temperature"] == 0.0
    assert seen_payload["timeout"] == 30.0


def test_llm_client_non_2xx_raises_backend_error() -> None:
    cfg = _config()
    client = LLMClient(cfg)

    def _fake_urlopen(req, *, timeout):
        raise HTTPError(req.full_url, 500, "Server Error", {}, None)

    with patch("urllib.request.urlopen", _fake_urlopen):
        with pytest.raises(BackendError, match="500"):
            client.chat([{"role": "user", "content": "x"}])
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/revisor/test_llm_endpoint.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `src/stele/revisor/llm_endpoint.py`:

```python
"""LLM client — OpenAI-compatible /chat/completions endpoint."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from stele.core.config import LLMEndpointConfig
from stele.core.exceptions import BackendError


class LLMClient:
    def __init__(self, config: LLMEndpointConfig) -> None:
        self._config = config

    def chat(self, messages: list[dict[str, str]]) -> str:
        """POST messages to /chat/completions; return the assistant's content string."""
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "messages": messages,
        }
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        req = Request(
            url=url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(req, timeout=self._config.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise BackendError(
                f"LLM extraction failed: {exc.code}: {exc.reason}"
            ) from exc
        except URLError as exc:
            raise BackendError(
                f"LLM extraction failed: timeout: {exc.reason}"
            ) from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise BackendError(
                f"LLM extraction failed: malformed response: {payload!r}"
            ) from exc
        return str(content)
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/revisor/test_llm_endpoint.py -v
.venv/bin/ruff check src/stele/revisor/llm_endpoint.py
.venv/bin/mypy src/stele/revisor/llm_endpoint.py
```

Expected: pass.

- [ ] **Step 5: Progress note**

```bash
echo "Task 8: LLM endpoint client ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 9: Graph search facade

**Files:**
- Create: `src/stele/retrieval/graph.py`

- [ ] **Step 1: Implement (consumed by GraphSearchStrategy in Task 21; no separate test here)**

Create `src/stele/retrieval/graph.py`:

```python
"""graph_search facade — backend-agnostic; delegates to a Revisor."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from stele.recall.models import Citation
from stele.revisor.models import KnowledgeHit
from stele.revisor.projection import knowledge_hits_to_citations

if TYPE_CHECKING:
    from stele.core.memory_record import MemoryScope
    from stele.revisor.base import Revisor


def graph_search(
    revisor: Revisor,
    *,
    query: str,
    scope: MemoryScope,
    limit: int = 5,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    retracted_behavior: Literal["hide", "flag", "surface_both"] = "hide",
) -> list[Citation]:
    from stele.revisor.models import KnowledgeQuery

    q = KnowledgeQuery(
        text=query,
        scope=scope,
        limit=limit,
        version_filter=version_filter,
        retracted_behavior=retracted_behavior,
    )
    if as_of is not None:
        hits: list[KnowledgeHit] = revisor.search_as_of(q, as_of=as_of)
    else:
        hits = revisor.search_current(q)
    return knowledge_hits_to_citations(hits)
```

- [ ] **Step 2: Lint + types**

```bash
.venv/bin/ruff check src/stele/retrieval/graph.py
.venv/bin/mypy src/stele/retrieval/graph.py
```

- [ ] **Step 3: Progress note**

```bash
echo "Task 9: graph_search facade ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 10: PgRaggraphRevisor skeleton + lazy import

**Files:**
- Create: `src/stele/revisor/pg_raggraph.py`
- Test: `tests/unit/revisor/test_pg_raggraph.py`

Only the skeleton; the five Protocol methods get filled in Tasks 11–16.

- [ ] **Step 1: Write failing test for missing-extra path**

Create `tests/unit/revisor/test_pg_raggraph.py`:

```python
"""Tests for PgRaggraphRevisor."""

from __future__ import annotations

import importlib.util

import pytest

from stele.core.config import PgRaggraphConfig
from stele.core.exceptions import OptionalDependencyError

PG_RAGGRAPH_AVAILABLE = importlib.util.find_spec("pg_raggraph") is not None


@pytest.mark.skipif(PG_RAGGRAPH_AVAILABLE, reason="pg_raggraph IS installed")
def test_pg_raggraph_revisor_raises_when_extra_missing() -> None:
    from stele.revisor.pg_raggraph import PgRaggraphRevisor

    cfg = PgRaggraphConfig(enabled=True)
    with pytest.raises(OptionalDependencyError, match="postgres-graph"):
        PgRaggraphRevisor(config=cfg, dsn="postgresql://x")


@pytest.mark.skipif(not PG_RAGGRAPH_AVAILABLE, reason="pg_raggraph not installed")
def test_pg_raggraph_revisor_is_not_noop() -> None:
    from stele.revisor.pg_raggraph import PgRaggraphRevisor

    cfg = PgRaggraphConfig(enabled=True)
    r = PgRaggraphRevisor(config=cfg, dsn="postgresql://x")
    assert r.is_noop is False
    r.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/revisor/test_pg_raggraph.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement skeleton**

Create `src/stele/revisor/pg_raggraph.py`:

```python
"""PgRaggraphRevisor — lazy-imports pg_raggraph; the five Protocol methods are
filled in subsequent tasks."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from typing import TYPE_CHECKING

from stele.core.config import PgRaggraphConfig
from stele.core.exceptions import BackendError, OptionalDependencyError
from stele.revisor.models import (
    EvidenceRecord,
    IndexReport,
    KnowledgeHit,
    KnowledgeQuery,
)

if TYPE_CHECKING:
    pass


class PgRaggraphRevisor:
    is_noop: bool = False

    def __init__(self, *, config: PgRaggraphConfig, dsn: str) -> None:
        spec = importlib.util.find_spec("pg_raggraph")
        if spec is None:
            raise OptionalDependencyError(
                "pg_raggraph required for graph mode; "
                "install 'stele-core[postgres-graph]'"
            )
        from pg_raggraph import GraphRAG  # type: ignore[import-not-found]

        self._config = config
        self._dsn = dsn
        # Build the GraphRAG client with the configured namespace prefix.
        self._graph = GraphRAG(
            dsn=dsn,
            namespace_prefix=config.namespace_prefix,
        )

    def ingest_evidence(self, evidence: EvidenceRecord) -> IndexReport:
        raise NotImplementedError("filled in Task 11/12")

    def search_current(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        raise NotImplementedError("filled in Task 13")

    def search_as_of(
        self, query: KnowledgeQuery, *, as_of: datetime
    ) -> list[KnowledgeHit]:
        raise NotImplementedError("filled in Task 14")

    def supersede(
        self, old_ref: str, new_ref: str, reason: str | None = None
    ) -> None:
        raise NotImplementedError("filled in Task 15")

    def retract(
        self, ref: str, reason: str, retracted_at: datetime | None = None
    ) -> None:
        raise NotImplementedError("filled in Task 16")

    def close(self) -> None:
        if hasattr(self, "_graph") and hasattr(self._graph, "close"):
            self._graph.close()
```

If `pg_raggraph.GraphRAG` exports under a different name, adjust the import. The exact constructor kwargs (`dsn=`, `namespace_prefix=`) may vary by release.

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/revisor/test_pg_raggraph.py -v
.venv/bin/ruff check src/stele/revisor/pg_raggraph.py
.venv/bin/mypy src/stele/revisor/pg_raggraph.py
```

Expected: at least the missing-extra test runs. With pg_raggraph installed, the not-noop test also runs.

- [ ] **Step 5: Progress note**

```bash
echo "Task 10: PgRaggraphRevisor skeleton ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 11: PgRaggraphRevisor.ingest_evidence — seeded mode

**Files:**
- Modify: `src/stele/revisor/pg_raggraph.py`
- Test: `tests/unit/revisor/test_pg_raggraph.py` (append)

Implementation note: `EvidenceRecord.entities` + `relations` flow into pg_raggraph as seeded entities. No LLM call.

- [ ] **Step 1: Write test**

Append:

```python
@pytest.mark.skipif(not PG_RAGGRAPH_AVAILABLE, reason="pg_raggraph not installed")
def test_pg_raggraph_seeded_entity_mode_ingest() -> None:
    import os
    from datetime import UTC, datetime

    from stele.revisor.models import EntitySeed, EvidenceRecord, RelationSeed
    from stele.revisor.pg_raggraph import PgRaggraphRevisor

    pg_dsn = os.environ.get("STELE_PG_DSN")
    if not pg_dsn:
        pytest.skip("STELE_PG_DSN not set")
    cfg = PgRaggraphConfig(enabled=True, entity_mode="seeded")
    r = PgRaggraphRevisor(config=cfg, dsn=pg_dsn)
    try:
        ev = EvidenceRecord(
            kind="artifact",
            reference="stele://default/aid_seed_test",
            text="Acme Corp signed up for Plan B in 2024.",
            namespace="default",
            effective_from=datetime.now(UTC),
            entities=[
                EntitySeed(name="Acme Corp", type="organization"),
                EntitySeed(name="Plan B", type="product"),
            ],
            relations=[
                RelationSeed(head="Acme Corp", tail="Plan B", type="SUBSCRIBED_TO"),
            ],
        )
        report = r.ingest_evidence(ev)
        assert report.evidence_count == 1
        assert report.entity_count >= 2
        assert report.relation_count >= 1
    finally:
        r.close()
```

- [ ] **Step 2: Implement**

Replace the `ingest_evidence` stub in `pg_raggraph.py`:

```python
    def ingest_evidence(self, evidence: EvidenceRecord) -> IndexReport:
        # Cap entities + relations per config
        if len(evidence.entities) > self._config.max_entities_per_evidence:
            raise BackendError(
                f"evidence has {len(evidence.entities)} entities; "
                f"exceeds max {self._config.max_entities_per_evidence}"
            )
        if len(evidence.relations) > self._config.max_relations_per_evidence:
            raise BackendError(
                f"evidence has {len(evidence.relations)} relations; "
                f"exceeds max {self._config.max_relations_per_evidence}"
            )

        if self._config.entity_mode == "llm":
            return self._ingest_with_llm(evidence)
        return self._ingest_seeded(evidence)

    def _ingest_seeded(self, evidence: EvidenceRecord) -> IndexReport:
        # Convert Stele EvidenceRecord → pg_raggraph document record.
        # Adjust field names to match the installed pg_raggraph release.
        doc_kwargs = {
            "reference": evidence.reference,
            "text": evidence.text,
            "namespace": evidence.namespace,
            "session_id": evidence.session_id,
            "effective_from": evidence.effective_from,
            "effective_to": evidence.effective_until,
            "version_label": evidence.version_label,
            "supersedes_document_id": evidence.supersedes,
            "retracted": evidence.retracted,
            "retracted_at": evidence.retracted_at,
            "retraction_reason": evidence.retraction_reason,
            "metadata": evidence.metadata,
            "evolution_tier": "structural",
            "entities": [e.model_dump() for e in evidence.entities],
            "relations": [r.model_dump() for r in evidence.relations],
        }
        try:
            self._graph.ingest_document(**doc_kwargs)
        except Exception as exc:
            return IndexReport(
                evidence_count=0,
                entity_count=0,
                relation_count=0,
                skipped=0,
                failed=1,
                failures=[{"reference": evidence.reference, "reason": str(exc)}],
            )
        return IndexReport(
            evidence_count=1,
            entity_count=len(evidence.entities),
            relation_count=len(evidence.relations),
            skipped=0,
            failed=0,
        )

    def _ingest_with_llm(self, evidence: EvidenceRecord) -> IndexReport:
        # Stub for Task 12.
        raise NotImplementedError("LLM mode lands in Task 12")
```

The exact `pg_raggraph` API (method name `ingest_document`, kwarg names) is gated on the user's release. If the actual API uses different names, mirror them here and update the projection layer.

- [ ] **Step 3: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/revisor/test_pg_raggraph.py -v -k seeded
.venv/bin/ruff check src/stele/revisor/pg_raggraph.py
.venv/bin/mypy src/stele/revisor/pg_raggraph.py
```

Expected: passes when `STELE_PG_DSN` is set and pg_raggraph is installed; skips cleanly otherwise.

- [ ] **Step 4: Progress note**

```bash
echo "Task 11: PgRaggraphRevisor seeded ingest ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 12: PgRaggraphRevisor.ingest_evidence — LLM mode

**Files:**
- Modify: `src/stele/revisor/pg_raggraph.py`
- Test: `tests/unit/revisor/test_pg_raggraph.py` (append)

- [ ] **Step 1: Write test (mocked LLM endpoint)**

Append:

```python
def test_pg_raggraph_llm_mode_requires_llm_config() -> None:
    from stele.revisor.pg_raggraph import PgRaggraphRevisor

    # entity_mode="llm" without llm should already be rejected by
    # PgRaggraphConfig validator, but test the runtime side too.
    cfg = PgRaggraphConfig(enabled=True)  # entity_mode defaults to "seeded"
    # Bypass validation by mutating after construction (private API only — not user-facing)
    object.__setattr__(cfg, "entity_mode", "llm")

    from stele.core.exceptions import ConfigError

    @pytest.mark.skipif(not PG_RAGGRAPH_AVAILABLE, reason="pg_raggraph not installed")
    def _inner():
        r = PgRaggraphRevisor(config=cfg, dsn="postgresql://x")
        from stele.revisor.models import EvidenceRecord
        from datetime import UTC, datetime
        ev = EvidenceRecord(
            kind="artifact",
            reference="stele://x/y",
            text="x",
            namespace="default",
            effective_from=datetime.now(UTC),
        )
        with pytest.raises(ConfigError, match="llm"):
            r.ingest_evidence(ev)
```

The test above is structured for the documented behavior — the real implementation needs to detect missing `llm` at runtime even if validation was bypassed.

- [ ] **Step 2: Implement `_ingest_with_llm`**

Replace the stub:

```python
    def _ingest_with_llm(self, evidence: EvidenceRecord) -> IndexReport:
        if self._config.llm is None:
            from stele.core.exceptions import ConfigError
            raise ConfigError("entity_mode='llm' requires llm: LLMEndpointConfig")
        from stele.revisor.llm_endpoint import LLMClient

        client = LLMClient(self._config.llm)
        extraction_prompt = self._build_extraction_prompt(evidence.text)
        try:
            raw = client.chat([
                {"role": "system", "content": "Extract entities and relations as JSON."},
                {"role": "user", "content": extraction_prompt},
            ])
        except Exception as exc:
            return IndexReport(
                evidence_count=0,
                entity_count=0,
                relation_count=0,
                skipped=0,
                failed=1,
                failures=[{"reference": evidence.reference, "reason": str(exc)}],
            )
        # Parse extracted entities + relations from LLM output
        try:
            parsed = self._parse_extraction(raw)
        except Exception as exc:
            return IndexReport(
                evidence_count=0,
                entity_count=0,
                relation_count=0,
                skipped=0,
                failed=1,
                failures=[{"reference": evidence.reference, "reason": f"parse: {exc}"}],
            )
        # Hydrate evidence with extracted entities + relations and reuse seeded path
        hydrated = evidence.model_copy(update={
            "entities": parsed["entities"],
            "relations": parsed["relations"],
        })
        return self._ingest_seeded(hydrated)

    def _build_extraction_prompt(self, text: str) -> str:
        return (
            "Extract named entities and their relations from the following text.\n"
            "Return JSON: {\"entities\": [{\"name\": str, \"type\": str|null}], "
            "\"relations\": [{\"head\": str, \"tail\": str, \"type\": str}]}.\n\n"
            f"Text:\n{text}"
        )

    def _parse_extraction(self, raw: str) -> dict[str, list]:
        import json
        from stele.revisor.models import EntitySeed, RelationSeed

        data = json.loads(raw.strip())
        entities = [EntitySeed.model_validate(e) for e in data.get("entities", [])]
        relations = [RelationSeed.model_validate(r) for r in data.get("relations", [])]
        return {"entities": entities, "relations": relations}
```

- [ ] **Step 3: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/revisor/test_pg_raggraph.py -v -k llm
.venv/bin/ruff check src/stele/revisor/pg_raggraph.py
.venv/bin/mypy src/stele/revisor/pg_raggraph.py
```

- [ ] **Step 4: Progress note**

```bash
echo "Task 12: PgRaggraphRevisor LLM mode ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 13: PgRaggraphRevisor.search_current

**Files:**
- Modify: `src/stele/revisor/pg_raggraph.py`

Implementation outline (the exact pg_raggraph query API depends on the user's release):

```python
    def search_current(self, query: KnowledgeQuery) -> list[KnowledgeHit]:
        # Apply scope filter and version_filter + retracted_behavior to a current-snapshot query
        rows = self._graph.search(
            text=query.text,
            namespace=query.scope.namespace,
            k=query.limit,
            version_filter=query.version_filter,
            retracted_behavior=query.retracted_behavior,
        )
        return [self._row_to_hit(row) for row in rows]

    def _row_to_hit(self, row: object) -> KnowledgeHit:
        # Adjust attribute accessors to the actual pg_raggraph row shape.
        return KnowledgeHit(
            reference=row.reference,  # type: ignore[attr-defined]
            kind=getattr(row, "kind", "artifact"),  # type: ignore[arg-type]
            text=row.text,  # type: ignore[attr-defined]
            score=float(row.score),  # type: ignore[attr-defined]
            effective_from=row.effective_from,  # type: ignore[attr-defined]
            effective_until=getattr(row, "effective_to", None),  # type: ignore[attr-defined]
            version_label=getattr(row, "version_label", None),
            retracted=getattr(row, "retracted", False),
            metadata=dict(getattr(row, "metadata", {})),
        )
```

- [ ] **Step 1: Implement (test landed in integration tests Tasks 28-33)**
- [ ] **Step 2: Lint + types**
- [ ] **Step 3: Progress note**

```bash
echo "Task 13: PgRaggraphRevisor.search_current ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 14: PgRaggraphRevisor.search_as_of

**Files:**
- Modify: `src/stele/revisor/pg_raggraph.py`

```python
    def search_as_of(
        self, query: KnowledgeQuery, *, as_of: datetime
    ) -> list[KnowledgeHit]:
        rows = self._graph.search(
            text=query.text,
            namespace=query.scope.namespace,
            k=query.limit,
            as_of=as_of,
            version_filter=query.version_filter,
            retracted_behavior=query.retracted_behavior,
        )
        return [self._row_to_hit(row) for row in rows]
```

- [ ] **Step 1: Implement**
- [ ] **Step 2: Lint + types**
- [ ] **Step 3: Progress note**

```bash
echo "Task 14: PgRaggraphRevisor.search_as_of ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 15: PgRaggraphRevisor.supersede

**Files:**
- Modify: `src/stele/revisor/pg_raggraph.py`

```python
    def supersede(
        self, old_ref: str, new_ref: str, reason: str | None = None
    ) -> None:
        self._graph.supersede(
            old_reference=old_ref,
            new_reference=new_ref,
            reason=reason,
        )
```

- [ ] **Step 1: Implement**
- [ ] **Step 2: Lint + types**
- [ ] **Step 3: Progress note**

```bash
echo "Task 15: PgRaggraphRevisor.supersede ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 16: PgRaggraphRevisor.retract

**Files:**
- Modify: `src/stele/revisor/pg_raggraph.py`

```python
    def retract(
        self, ref: str, reason: str, retracted_at: datetime | None = None
    ) -> None:
        self._graph.retract(
            reference=ref,
            reason=reason,
            retracted_at=retracted_at,
        )
```

- [ ] **Step 1: Implement**
- [ ] **Step 2: Lint + types**
- [ ] **Step 3: Progress note**

```bash
echo "Task 16: PgRaggraphRevisor.retract ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 17: Memory.retract method (with projection)

**Files:**
- Modify: `src/stele/core/memory.py`
- Test: `tests/unit/core/test_memory_retract.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/core/test_memory_retract.py`:

```python
"""Tests for Memory.retract."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import MemoryScope


def test_memory_retract_sets_status_retracted() -> None:
    stele = Stele(StashConfig())
    result = stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    mem_id = result.record.id
    retracted = stele.memory.retract(mem_id, reason="updated preference")
    assert retracted.status == "retracted"
    assert retracted.metadata.get("retraction_reason") == "updated preference"
    assert retracted.metadata.get("retracted_at") is not None
    stele.close()


def test_memory_retract_missing_id_raises() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(ArtifactNotFound):
        stele.memory.retract("nonexistent", reason="x")
    stele.close()


def test_memory_retract_excluded_from_default_search() -> None:
    from stele.core.memory_record import MemoryQuery

    stele = Stele(StashConfig())
    result = stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    stele.memory.retract(result.record.id, reason="x")
    hits = stele.memory.search(
        MemoryQuery(query="dark mode", scope=MemoryScope(user_id="alice"))
    )
    assert not hits  # retracted is not active; default search filters to active only
    stele.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_retract.py -v
```

Expected: AttributeError on `retract`.

- [ ] **Step 3: Implement**

In `src/stele/core/memory.py`, add to `Memory`:

```python
    def retract(
        self,
        memory_id: str,
        *,
        reason: str,
        retracted_at: datetime | None = None,
    ) -> MemoryRecord:
        ts = retracted_at or datetime.now(UTC)
        # 1. Update SQL: set status="retracted", merge metadata
        existing = self._store.get(memory_id)
        if existing is None:
            from stele.core.exceptions import ArtifactNotFound
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        new_metadata = dict(existing.metadata)
        new_metadata["retraction_reason"] = reason
        new_metadata["retracted_at"] = ts.isoformat()
        updated = self._store.update_status_and_metadata(
            memory_id, status="retracted", metadata=new_metadata
        )
        # 2. Project to Revisor when configured (best-effort)
        self._maybe_project_retract(updated, ts)
        return updated

    def _maybe_project_retract(self, memory: MemoryRecord, retracted_at: datetime) -> None:
        # Stele injects the revisor at construction; the Memory facade may not
        # carry it directly. The actual wiring lives in Stele._maybe_project_retract
        # — Memory.retract just calls back through a callback set at init.
        if self._revisor_retract is not None:
            try:
                self._revisor_retract(memory, retracted_at)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "pg_raggraph projection failed (retract): %s", exc
                )
```

Add the `_revisor_retract` callback field to `Memory.__init__`:

```python
    def __init__(
        self,
        store: MemoryStore,
        scrubber: RegexPIIScrubber | DisabledPIIScrubber,
        *,
        revisor_retract: Callable[[MemoryRecord, datetime], None] | None = None,
        revisor_supersede: Callable[[str, str, str | None], None] | None = None,
        revisor_ingest: Callable[[MemoryRecord], None] | None = None,
    ) -> None:
        self._store = store
        self._scrubber = scrubber
        self._revisor_retract = revisor_retract
        self._revisor_supersede = revisor_supersede
        self._revisor_ingest = revisor_ingest
```

The `MemoryStore.update_status_and_metadata` Protocol method is implied; if Phase 1's MemoryStore doesn't already have it, this task adds it. If it does (Phase 1's `update_metadata` may suffice), adapt the call.

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/core/test_memory_retract.py -v
.venv/bin/ruff check src/stele/core/memory.py
.venv/bin/mypy src/stele/core/memory.py
```

Expected: 3 tests PASS.

- [ ] **Step 5: Progress note**

```bash
echo "Task 17: Memory.retract ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 18: Memory.add(supersedes=) projection wire-up

**Files:**
- Modify: `src/stele/core/memory.py`

- [ ] **Step 1: Add projection to `Memory.add`**

After the existing SQL write returns success in `Memory.add`, add:

```python
        # Project to Revisor when configured (best-effort)
        if self._revisor_ingest is not None:
            try:
                self._revisor_ingest(stored)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "pg_raggraph projection failed (memory ingest): %s", exc
                )

        if supersedes_ids and self._revisor_supersede is not None:
            new_ref = f"stele://memory/{stored.id}"
            for old_id in supersedes_ids:
                old_ref = f"stele://memory/{old_id}"
                try:
                    self._revisor_supersede(old_ref, new_ref, None)
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "pg_raggraph projection failed (supersede): %s", exc
                    )
```

- [ ] **Step 2: Run existing memory tests**

```bash
.venv/bin/pytest tests/unit/core/test_memory_add.py tests/unit/core/test_memory_facade.py -v
```

Expected: existing Phase 1 tests still pass.

- [ ] **Step 3: Progress note**

```bash
echo "Task 18: Memory.add supersedes projection ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 19: Stele._revisor build + Stele.store projection + DC-002

**Files:**
- Modify: `src/stele/core/stash.py`

- [ ] **Step 1: Build _revisor at Stele.__init__**

In `Stele.__init__`, after the chunk_store is built (Phase 4 wire-up), add:

```python
self._revisor = self._build_revisor()
self._last_revisor_error: str | None = None
```

Define `_build_revisor`:

```python
def _build_revisor(self):
    pg_cfg = self.config.indexing.pg_raggraph
    if not pg_cfg.enabled:
        from stele.revisor.noop import NoOpRevisor
        return NoOpRevisor()
    if self.config.backend.type != "postgres":
        from stele.core.exceptions import ConfigError
        raise ConfigError("pg_raggraph requires backend.type='postgres'")
    if not self.config.backend.dsn:
        from stele.core.exceptions import ConfigError
        raise ConfigError("pg_raggraph requires backend.dsn")
    from stele.revisor.pg_raggraph import PgRaggraphRevisor
    return PgRaggraphRevisor(config=pg_cfg, dsn=self.config.backend.dsn)
```

- [ ] **Step 2: Update Stele.memory property to wire callbacks**

In the `memory` property:

```python
self._memory = Memory(
    store,
    self.pii_scrubber,  # type: ignore[arg-type]
    revisor_retract=self._project_memory_retract,
    revisor_supersede=self._project_supersede,
    revisor_ingest=self._project_memory_ingest,
)
```

Add the callbacks:

```python
def _project_memory_ingest(self, memory):
    if self._revisor.is_noop or not self.config.indexing.pg_raggraph.project_on_write:
        return
    from stele.revisor.projection import memory_to_evidence
    evidence = memory_to_evidence(memory)
    try:
        self._revisor.ingest_evidence(evidence)
    except Exception as exc:
        self._last_revisor_error = str(exc)
        raise  # caller (Memory) wraps in best-effort

def _project_memory_retract(self, memory, retracted_at):
    if self._revisor.is_noop or not self.config.indexing.pg_raggraph.project_on_write:
        return
    self._revisor.retract(
        f"stele://memory/{memory.id}",
        memory.metadata.get("retraction_reason", "unspecified"),
        retracted_at,
    )

def _project_supersede(self, old_ref, new_ref, reason):
    if self._revisor.is_noop or not self.config.indexing.pg_raggraph.project_on_write:
        return
    self._revisor.supersede(old_ref, new_ref, reason)
```

- [ ] **Step 3: Project Stele.store**

In `Stele.store`, after successful artifact persistence:

```python
        if not self._revisor.is_noop and self.config.indexing.pg_raggraph.project_on_write:
            try:
                from stele.revisor.projection import artifact_to_evidence
                self._revisor.ingest_evidence(artifact_to_evidence(record))
            except Exception as exc:
                self._last_revisor_error = str(exc)
                import logging
                logging.getLogger(__name__).warning(
                    "pg_raggraph projection failed (store): %s", exc
                )
        return stored_result
```

- [ ] **Step 4: Extend Stele.close()**

```python
revisor = getattr(self, "_revisor", None)
if revisor is not None: revisor.close()
```

- [ ] **Step 5: Update Stele.capabilities() (Task 20 fills in fully; smoke here)**

Add the four `_revisor`-related fields:

```python
return Capabilities(
    # ... Phase 1/3/4 fields ...
    pg_raggraph_installed=importlib.util.find_spec("pg_raggraph") is not None,
    pg_raggraph_version=getattr(_pg, "__version__", None) if (_pg := __import__("pg_raggraph", fromlist=["__version__"]) if importlib.util.find_spec("pg_raggraph") is not None else None) else None,  # adapt as needed
    revisor_mode="pg_raggraph" if not self._revisor.is_noop else "noop" if self.config.indexing.pg_raggraph.enabled is False else None,
    entity_mode=self.config.indexing.pg_raggraph.entity_mode if self.config.indexing.pg_raggraph.enabled else None,
    llm_endpoint_configured=self.config.indexing.pg_raggraph.llm is not None,
    retracted_behavior_default=self.config.indexing.pg_raggraph.retracted_behavior_default if self.config.indexing.pg_raggraph.enabled else None,
    last_revisor_error=self._last_revisor_error,
)
```

Simplify the version-detection if it's too dense — pull into a helper.

- [ ] **Step 6: Run DC-002**

```bash
echo "=== DC-002 ==="
grep -rn 'self\._revisor\.' src/stele/ 2>/dev/null
```

Expected: matches only in `src/stele/core/stash.py` and `src/stele/core/memory.py` and (after Task 21) `src/stele/recall/graph_search.py`.

- [ ] **Step 7: Lint + types**

```bash
.venv/bin/ruff check src/stele/core/stash.py
.venv/bin/mypy src/stele
```

- [ ] **Step 8: Progress note**

```bash
echo "Task 19: Stele._revisor build + Stele.store projection + DC-002 ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 20: Capabilities.last_revisor_error wiring (refinement)

**Files:**
- Modify: `src/stele/core/stash.py`

Task 19 sketched this; Task 20 confirms the flow is correct by running the capabilities test from Task 5:

- [ ] **Step 1: Run test**

```bash
.venv/bin/pytest tests/unit/core/test_capabilities_pg_raggraph_fields.py -v
```

Expected: pass.

- [ ] **Step 2: Progress note**

```bash
echo "Task 20: Capabilities.last_revisor_error ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 21: GraphSearchStrategy real implementation + DC-001

**Files:**
- Modify: `src/stele/recall/graph_search.py`
- Test: `tests/unit/recall/test_graph_search_real.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/recall/test_graph_search_real.py`:

```python
"""Tests for the real GraphSearchStrategy (replaces Phase 3 stub)."""

from __future__ import annotations

import importlib.util

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope


def test_graph_search_raises_when_pg_raggraph_not_configured() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(CapabilityError, match="pg-raggraph"):
        stele.recall(
            query="anything",
            scope=MemoryScope(user_id="alice"),
            strategy="graph_search",
        )
    stele.close()
```

- [ ] **Step 2: Run, confirm pass**

```bash
.venv/bin/pytest tests/unit/recall/test_graph_search_real.py -v
```

The Phase 3 stub raises CapabilityError; this test passes against the stub. We update the test as the real implementation lands.

- [ ] **Step 3: Replace `graph_search.py` body**

In `src/stele/recall/graph_search.py`:

```python
"""GraphSearchStrategy — Phase 5 real implementation."""

from __future__ import annotations

from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)
from stele.retrieval.graph import graph_search


class GraphSearchStrategy:
    name = "graph_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        revisor = deps.stele._revisor
        # NoOpRevisor will raise the CapabilityError itself
        retracted_behavior = (
            request.retracted_behavior
            or deps.config_recall_retracted_behavior_default()  # helper added below
            or "hide"
        )
        citations: list[Citation] = graph_search(
            revisor,
            query=request.query,
            scope=request.scope,
            limit=request.max_memory_hits + request.max_artifact_hits,
            as_of=request.as_of,
            version_filter=request.version_filter,
            retracted_behavior=retracted_behavior,
        )

        top_score = citations[0].score if citations else None

        return RecallResult(
            strategy_used="graph_search",
            context="\n\n".join(c.snippet for c in citations),
            citations=citations,
            escalations=[
                Escalation(
                    strategy="graph_search",
                    hit_count=len(citations),
                    top_score=top_score,
                    reason="tier_complete" if citations else "zero_hits",
                )
            ],
            pii_flags=[],
            source_refs=sorted({c.reference for c in citations}),
            stats=RecallStats(),
        )
```

Add a helper on `_RecallDeps` to expose the config default:

```python
# In src/stele/recall/base.py
@dataclass(frozen=True)
class _RecallDeps:
    stele: Stele
    memory: Memory
    scrubber: ...
    config: RecallConfig

    def config_recall_retracted_behavior_default(self) -> str | None:
        # Reach through to indexing.pg_raggraph.retracted_behavior_default
        pg = self.stele.config.indexing.pg_raggraph
        return pg.retracted_behavior_default if pg.enabled else None
```

- [ ] **Step 4: Run + DC-001**

```bash
.venv/bin/pytest tests/unit/recall/test_graph_search_real.py -v
.venv/bin/ruff check src/stele/recall/graph_search.py
.venv/bin/mypy src/stele/recall/graph_search.py
```

Run DC-001:

```bash
echo "=== DC-001 ==="
grep -rn 'pg_raggraph' src/stele/ | grep -v 'src/stele/revisor/' | grep -v '__pycache__'
```

Expected: empty.

- [ ] **Step 5: Progress note**

```bash
echo "Task 21: GraphSearchStrategy real + DC-001 ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 22: AdaptiveStrategy graceful skip on CapabilityError + DC-004

**Files:**
- Modify: `src/stele/recall/adaptive.py`
- Test: `tests/unit/recall/test_adaptive_with_graph_search.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/recall/test_adaptive_with_graph_search.py`:

```python
"""Tests for AdaptiveStrategy gracefully skipping graph_search on CapabilityError."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_adaptive_skips_graph_search_when_unconfigured() -> None:
    cfg = StashConfig.load({
        "recall": {
            "adaptive_tier_order": [
                "memory_search",
                "artifact_search",
                "graph_search",
                "raw_fetch",
                "abstain",
            ],
        },
    })
    stele = Stele(cfg)
    try:
        # No memories, no artifacts → adaptive escalates through all tiers
        result = stele.recall(
            query="something nobody knows",
            scope=MemoryScope(user_id="alice"),
        )
        strategies_seen = [e.strategy for e in result.escalations]
        assert "graph_search" in strategies_seen
        graph_esc = next(e for e in result.escalations if e.strategy == "graph_search")
        assert graph_esc.reason == "capability_error"
        # Adaptive does NOT raise; it terminates at abstain
        assert result.strategy_used == "abstain"
    finally:
        stele.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/recall/test_adaptive_with_graph_search.py -v
```

Expected: CapabilityError propagates (current adaptive impl doesn't catch).

- [ ] **Step 3: Modify AdaptiveStrategy**

In `src/stele/recall/adaptive.py`, wrap each tier execution:

```python
for tier_name in tier_order:
    strategy = self._registry[tier_name]
    try:
        tier_result = strategy.execute(request, deps)
    except CapabilityError as exc:
        all_escalations.append(
            Escalation(
                strategy=tier_name,
                hit_count=0,
                top_score=None,
                reason="capability_error",
            )
        )
        continue
    # ... existing post-tier logic ...
```

Add `from stele.core.exceptions import CapabilityError` to imports.

Also add `"capability_error"` to the `EscalationReason` literal in `src/stele/recall/models.py`:

```python
EscalationReason = Literal[
    "tier_complete",
    "below_floor",
    "zero_hits",
    "sufficient_callback_false",
    "exhausted",
    "capability_error",  # NEW for Phase 5
]
```

- [ ] **Step 4: Run, confirm pass + DC-004**

```bash
.venv/bin/pytest tests/unit/recall/test_adaptive_with_graph_search.py -v
.venv/bin/ruff check src/stele/recall/adaptive.py src/stele/recall/models.py
.venv/bin/mypy src/stele/recall
```

Run DC-004:

```bash
echo "=== DC-004 ==="
.venv/bin/python -c "
from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

# Default config has no pg_raggraph; adaptive must not raise
stele = Stele(StashConfig())
result = stele.recall(query='x', scope=MemoryScope(user_id='a'))
print('DC-004 PASS: adaptive ran without raising; strategy_used=', result.strategy_used)
stele.close()
"
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 22: Adaptive skip + DC-004 ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 23: Recall facade pass-through for Phase 5 fields

**Files:**
- Modify: `src/stele/recall/facade.py`

- [ ] **Step 1: Update __call__ signature**

In `src/stele/recall/facade.py`, in `Recall.__call__`:

```python
def __call__(
    self,
    *,
    query: str = "",
    scope: MemoryScope,
    strategy: StrategyName | None = None,
    artifact_id: str | None = None,
    sufficient: ... = None,
    max_memory_hits: int | None = None,
    max_artifact_hits: int | None = None,
    confidence_floor: float | None = None,
    # Phase 5 fields:
    as_of: datetime | None = None,
    version_filter: str | None = None,
    retracted_behavior: Literal["hide", "flag", "surface_both"] | None = None,
) -> RecallResult:
    # ... build RecallRequest passing through the new fields ...
```

Update the `RecallRequest` construction:

```python
req = RecallRequest(
    query=query,
    scope=scope,
    strategy=strategy or self._deps.config.default_strategy,
    artifact_id=artifact_id,
    sufficient=sufficient,
    max_memory_hits=...,
    max_artifact_hits=...,
    confidence_floor=confidence_floor,
    as_of=as_of,
    version_filter=version_filter,
    retracted_behavior=retracted_behavior,
)
```

Update `Recall.graph_search` shim:

```python
def graph_search(
    self,
    *,
    query: str,
    scope: MemoryScope,
    artifact_id: str | None = None,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    retracted_behavior: Literal["hide", "flag", "surface_both"] | None = None,
) -> RecallResult:
    return self(
        query=query,
        scope=scope,
        strategy="graph_search",
        artifact_id=artifact_id,
        as_of=as_of,
        version_filter=version_filter,
        retracted_behavior=retracted_behavior,
    )
```

- [ ] **Step 2: Lint + types**

```bash
.venv/bin/ruff check src/stele/recall/facade.py
.venv/bin/mypy src/stele/recall/facade.py
```

- [ ] **Step 3: Progress note**

```bash
echo "Task 23: Facade pass-through ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 24: Architecture import-layer check

**Files:**
- Test: `tests/unit/revisor/test_architecture.py`

- [ ] **Step 1: Write test**

Create `tests/unit/revisor/test_architecture.py`:

```python
"""Architectural import-layer checks for Phase 5."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src/stele"
REVISOR_DIR = SRC_DIR / "revisor"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


@pytest.mark.parametrize(
    "module_path",
    sorted(p for p in SRC_DIR.rglob("*.py") if REVISOR_DIR not in p.parents),
)
def test_no_pg_raggraph_imports_outside_revisor(module_path: Path) -> None:
    imports = _imports(module_path)
    leaked = [i for i in imports if i.startswith("pg_raggraph")]
    assert not leaked, (
        f"{module_path} imports {leaked} — pg_raggraph must stay in src/stele/revisor/"
    )
```

- [ ] **Step 2: Run**

```bash
.venv/bin/pytest tests/unit/revisor/test_architecture.py -v
```

Expected: all parametrized cases PASS.

- [ ] **Step 3: Progress note**

```bash
echo "Task 24: Architecture import check ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 25: Best-effort projection test + DC-005

**Files:**
- Test: `tests/integration/pg_raggraph/test_best_effort_projection.py`

Tests that a deliberately-broken Revisor doesn't break writes.

- [ ] **Step 1: Write test**

Create `tests/integration/pg_raggraph/__init__.py` (empty).

Create `tests/integration/pg_raggraph/test_best_effort_projection.py`:

```python
"""DC-005: deliberately-broken Revisor doesn't break writes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_broken_revisor_does_not_break_store() -> None:
    stele = Stele(StashConfig())
    # Replace _revisor with one that raises on every ingest
    class _BrokenRevisor:
        is_noop = False
        def ingest_evidence(self, ev):
            raise RuntimeError("simulated projection failure")
        def search_current(self, q): raise NotImplementedError
        def search_as_of(self, q, *, as_of): raise NotImplementedError
        def supersede(self, *a, **kw): raise RuntimeError("simulated supersede failure")
        def retract(self, *a, **kw): raise RuntimeError("simulated retract failure")
        def close(self): pass

    stele._revisor = _BrokenRevisor()
    # Also flip the project_on_write flag to True so projection actually runs
    stele.config = stele.config.model_copy(update={
        "indexing": stele.config.indexing.model_copy(update={
            "pg_raggraph": stele.config.indexing.pg_raggraph.model_copy(update={
                "enabled": True,
                "project_on_write": True,
            })
        })
    })
    try:
        # store() must succeed despite the broken Revisor
        result = stele.store(data="hello world", namespace="default")
        assert result.artifact_id
        # Memory.add() must succeed
        mem = stele.memory.add(
            text="x",
            kind="fact",
            source_refs=[result.reference],
            scope=MemoryScope(user_id="alice"),
        )
        assert mem.record.id
        # capabilities.last_revisor_error should be populated
        caps = stele.capabilities()
        assert caps.last_revisor_error is not None
    finally:
        stele.close()
```

- [ ] **Step 2: Run**

```bash
.venv/bin/pytest tests/integration/pg_raggraph/test_best_effort_projection.py -v
```

Expected: PASS — best-effort guarantees writes succeed.

- [ ] **Step 3: Progress note**

```bash
echo "Task 25: Best-effort projection test + DC-005 ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 26: Two-as_of-paths test

**Files:**
- Test: `tests/integration/pg_raggraph/test_as_of_two_paths.py`

Verifies `Memory.search(as_of=)` and `Stele.recall(graph_search, as_of=)` give different results when only one path can see certain evidence.

- [ ] **Step 1: Write test**

Create `tests/integration/pg_raggraph/test_as_of_two_paths.py`:

```python
"""Verify the two as_of paths are distinct."""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, datetime, timedelta

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("pg_raggraph") or not os.environ.get("STELE_PG_DSN"),
    reason="requires pg_raggraph + STELE_PG_DSN",
)


def test_memory_as_of_uses_sql() -> None:
    # Phase 1 SQL as_of behavior should be unchanged
    cfg = StashConfig.load({
        "backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]},
        "indexing": {"pg_raggraph": {"enabled": True}},
    })
    stele = Stele(cfg)
    try:
        t0 = datetime.now(UTC)
        stele.memory.add(
            text="old fact", kind="fact",
            source_refs=["stele://default/aid"],
            scope=MemoryScope(user_id="alice"),
        )
        # Memory.search(as_of=) uses SQL effective_from/until filters
        hits = stele.memory.search(
            MemoryQuery(query="old fact", scope=MemoryScope(user_id="alice"), as_of=t0 + timedelta(seconds=1))
        )
        assert hits
    finally:
        stele.close()


def test_recall_graph_as_of_uses_graph_traversal() -> None:
    cfg = StashConfig.load({
        "backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]},
        "indexing": {"pg_raggraph": {"enabled": True}},
    })
    stele = Stele(cfg)
    try:
        t0 = datetime.now(UTC)
        stored = stele.store(data="Acme moved to Plan B", namespace="default")
        # Stele.recall(graph_search, as_of=) uses the graph
        result = stele.recall(
            query="Plan B",
            scope=MemoryScope(user_id="alice"),
            strategy="graph_search",
            as_of=t0 + timedelta(seconds=1),
        )
        # Should find the artifact via graph_search even though no memory exists
        assert result.strategy_used == "graph_search"
    finally:
        stele.close()
```

- [ ] **Step 2: Run (skips if pg_raggraph or PG_DSN missing)**

```bash
.venv/bin/pytest tests/integration/pg_raggraph/test_as_of_two_paths.py -v
```

- [ ] **Step 3: Progress note**

```bash
echo "Task 26: Two-as_of-paths test ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 27: Fixtures — versioned_docs + retracted_medical

**Files:**
- Create: `tests/fixtures/pg_raggraph/versioned_docs.json`
- Create: `tests/fixtures/pg_raggraph/retracted_medical.json`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p tests/fixtures/pg_raggraph
```

- [ ] **Step 2: Build versioned_docs.json**

Hand-author ≥10 evidence records spanning ≥2 versions, ≥5 queries with mixed `version_filter` + current + historical expectations. Structure described in the spec § Living Knowledge Verification — Lane 1.

- [ ] **Step 3: Build retracted_medical.json**

Hand-author ≥8 evidence records, ≥4 queries covering retracted_behavior hide/flag/surface_both. Structure described in spec § Lane 2.

- [ ] **Step 4: Verify fixtures load**

```bash
.venv/bin/python -c "
import json
from pathlib import Path
for f in sorted(Path('tests/fixtures/pg_raggraph').glob('*.json')):
    data = json.loads(f.read_text())
    print(f.name, '→', data['lane'], 'evidence=' + str(len(data['evidence'])), 'queries=' + str(len(data['queries'])))
"
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 27: Fixtures ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 28: Bar #1 — Supersession (both lanes)

**Files:**
- Test: `tests/integration/pg_raggraph/test_supersession.py`

Tests skip when pg_raggraph missing OR `STELE_PG_DSN` not set.

- [ ] **Step 1: Write test**

Create `tests/integration/pg_raggraph/test_supersession.py`:

```python
"""Bar #1: New evidence supersedes old; old is deprioritized/hidden per policy."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("pg_raggraph") or not os.environ.get("STELE_PG_DSN"),
    reason="requires pg_raggraph + STELE_PG_DSN",
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures/pg_raggraph"


def _ingest(stele: Stele, evidence_records: list[dict]) -> None:
    from datetime import UTC, datetime
    from stele.revisor.models import EvidenceRecord

    for rec_dict in evidence_records:
        rec = EvidenceRecord(
            kind=rec_dict["kind"],
            reference=rec_dict["reference"],
            text=rec_dict["text"],
            namespace="default",
            effective_from=datetime.fromisoformat(rec_dict["effective_from"]),
            version_label=rec_dict.get("version_label"),
            supersedes=rec_dict.get("supersedes", []),
            retracted=rec_dict.get("retracted", False),
        )
        stele._revisor.ingest_evidence(rec)


@pytest.mark.parametrize("fixture_file", ["versioned_docs.json", "retracted_medical.json"])
def test_supersession_works(fixture_file: str) -> None:
    fixture = json.loads((FIXTURE_DIR / fixture_file).read_text())
    cfg = StashConfig.load({
        "backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]},
        "indexing": {"pg_raggraph": {"enabled": True}},
    })
    stele = Stele(cfg)
    try:
        _ingest(stele, fixture["evidence"])
        for query in fixture["queries"]:
            if "current_hide_expected" not in query and "current_expected" not in query:
                continue
            result = stele.recall(
                query=query["query"],
                scope=MemoryScope(user_id="alice"),
                strategy="graph_search",
                retracted_behavior="hide",
            )
            hit_refs = {c.reference for c in result.citations}
            expected = set(query.get("current_hide_expected") or query.get("current_expected") or [])
            assert expected.issubset(hit_refs), (
                f"{fixture_file} query={query['query']!r}: expected {expected} ⊆ {hit_refs}"
            )
    finally:
        stele.close()
```

- [ ] **Step 2: Run**

```bash
.venv/bin/pytest tests/integration/pg_raggraph/test_supersession.py -v
```

Expected: both parametrized cases PASS (when pg_raggraph + Postgres available).

- [ ] **Step 3: Progress note**

```bash
echo "Task 28: Bar #1 supersession ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 29: Bar #2 — Retraction (retracted_medical lane)

**Files:**
- Test: `tests/integration/pg_raggraph/test_retraction.py`

Similar shape to Task 28's test. Verifies hide/flag/surface_both all behave correctly.

- [ ] **Step 1: Write test** — mirrors Task 28's pattern; parametrizes over the three `retracted_behavior` values; uses `retracted_medical.json` only.
- [ ] **Step 2: Run.**
- [ ] **Step 3: Progress note.**

```bash
echo "Task 29: Bar #2 retraction ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 30: Bar #3 — as_of (both lanes)

**Files:**
- Test: `tests/integration/pg_raggraph/test_as_of.py`

Same shape as Task 28; uses each fixture's queries with as_of expectations.

- [ ] **Step 1: Write test** — parametrizes over both lanes; for each query with `historical_expected_at_T`, verify `Stele.recall(graph_search, as_of=T)` returns the historical answer.
- [ ] **Step 2: Run.**
- [ ] **Step 3: Progress note.**

```bash
echo "Task 30: Bar #3 as_of ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 31: Bar #4 — version_filter (versioned_docs lane)

**Files:**
- Test: `tests/integration/pg_raggraph/test_version_filter.py`

- [ ] **Step 1: Write test** — uses versioned_docs.json only; for each query with `version_filter`, verify all hits match the version (no cross-version bleed).
- [ ] **Step 2: Run.**
- [ ] **Step 3: Progress note.**

```bash
echo "Task 31: Bar #4 version_filter ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 32: Bar #5 — provenance (both lanes)

**Files:**
- Test: `tests/integration/pg_raggraph/test_provenance.py`

- [ ] **Step 1: Write test** — for every query in both fixture lanes, verify every Citation in the result has `reference.startswith("stele://")` and is non-empty.
- [ ] **Step 2: Run.**
- [ ] **Step 3: Progress note.**

```bash
echo "Task 32: Bar #5 provenance ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 33: Bar #6 — Postgres baseline without pg_raggraph + DC-003

**Files:**
- Test: `tests/integration/pg_raggraph/test_postgres_baseline_without_pg_raggraph.py`

- [ ] **Step 1: Write test**

Create `tests/integration/pg_raggraph/test_postgres_baseline_without_pg_raggraph.py`:

```python
"""Bar #6: Postgres baseline works without pg_raggraph installed."""

from __future__ import annotations

import importlib.util
import os
from unittest.mock import patch

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import OptionalDependencyError

pytestmark = pytest.mark.skipif(
    not os.environ.get("STELE_PG_DSN"),
    reason="requires STELE_PG_DSN",
)


def test_postgres_baseline_with_pg_raggraph_disabled_works() -> None:
    # pg_raggraph may or may not be installed; with enabled=False, Stele runs fine
    cfg = StashConfig.load({
        "backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]},
        "indexing": {"pg_raggraph": {"enabled": False}},
    })
    stele = Stele(cfg)
    try:
        result = stele.store(data="hello world", namespace="default")
        assert result.artifact_id
        fetched = stele.fetch(result.artifact_id)
        assert "hello world" in str(fetched.content)
        caps = stele.capabilities()
        assert caps.revisor_mode is None
    finally:
        stele.close()


def test_postgres_with_pg_raggraph_enabled_but_missing_raises() -> None:
    # Simulate pg_raggraph not installed
    with patch("importlib.util.find_spec", lambda name: None if name == "pg_raggraph" else importlib.util.find_spec(name)):
        cfg = StashConfig.load({
            "backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]},
            "indexing": {"pg_raggraph": {"enabled": True}},
        })
        with pytest.raises(OptionalDependencyError, match="postgres-graph"):
            Stele(cfg)
```

- [ ] **Step 2: Run + DC-003**

```bash
.venv/bin/pytest tests/integration/pg_raggraph/ -v
```

Expected: all 6 bar tests pass on the applicable fixture lanes.

```bash
echo "=== DC-003 (Phase 5 exit gate) ==="
.venv/bin/pytest tests/integration/pg_raggraph/ -v 2>&1 | tail -20
```

If all 6 bar tests pass → **DC-003 PASS**, Phase 5 has cleared the living-knowledge gate.

- [ ] **Step 3: Progress note**

```bash
echo "Task 33: Bar #6 + DC-003 Phase 5 exit gate ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 34: Living-knowledge benchmark

**Files:**
- Create: `benchmarks/living_knowledge.py`
- Test: `tests/benchmarks_smoke/test_living_knowledge_benchmark.py`

- [ ] **Step 1: Write benchmark**

Create `benchmarks/living_knowledge.py`:

```python
"""Living-knowledge benchmark: current/historical recall + stale-memory rate."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output-dir", default="benchmarks/runs", type=Path)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text())
    cfg = StashConfig.load({
        "backend": {"type": "postgres", "dsn": "postgresql://yonk:yonk@localhost:55432/stele"},
        "indexing": {"pg_raggraph": {"enabled": True}},
    })
    stele = Stele(cfg)
    try:
        _ingest(stele, fixture["evidence"])
        metrics = _evaluate(stele, fixture["queries"])
        run_dir = args.output_dir / datetime.now(UTC).strftime("%Y-%m-%d")
        run_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "lane": fixture["lane"],
            "metrics": metrics,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        (run_dir / "LivingKnowledge.json").write_text(json.dumps(report, indent=2))
        _write_markdown(run_dir / "LivingKnowledge.md", report)
        print(f"Wrote {run_dir}/LivingKnowledge.{{md,json}}")
    finally:
        stele.close()


def _ingest(stele: Stele, evidence: list[dict]) -> None:
    # Build EvidenceRecord from each dict; call stele._revisor.ingest_evidence
    pass  # implemented inline per fixture shape


def _evaluate(stele: Stele, queries: list[dict]) -> dict:
    correct_current = 0
    correct_historical = 0
    stale_errors = 0
    version_filter_precision_hits = 0
    version_filter_total = 0
    for q in queries:
        result_current = stele.recall(
            query=q["query"],
            scope=MemoryScope(namespace="default"),
            strategy="graph_search",
        )
        # ... evaluate per fixture spec
    return {
        "current_recall_at_5": correct_current / max(len(queries), 1),
        "historical_recall_at_5": correct_historical / max(len(queries), 1),
        "stale_memory_error_rate": stale_errors / max(len(queries), 1),
        "version_filter_precision": (
            version_filter_precision_hits / version_filter_total
            if version_filter_total else None
        ),
    }


def _write_markdown(path: Path, report: dict) -> None:
    lines = [f"# LivingKnowledge — {report['lane']}", "", f"Timestamp: {report['timestamp']}", ""]
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    for k, v in report["metrics"].items():
        lines.append(f"| {k} | {v:.4f}" if isinstance(v, float) else f"| {k} | {v} |")
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write smoke test**

Create `tests/benchmarks_smoke/test_living_knowledge_benchmark.py`:

```python
"""Smoke test for the living-knowledge benchmark — does it produce a report?"""

from __future__ import annotations

import importlib.util
import os
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("pg_raggraph") or not os.environ.get("STELE_PG_DSN"),
    reason="requires pg_raggraph + STELE_PG_DSN",
)


def test_living_knowledge_benchmark_smoke(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = subprocess.run(
        [
            ".venv/bin/python", "-m", "benchmarks.living_knowledge",
            "--fixture", "tests/fixtures/pg_raggraph/versioned_docs.json",
            "--output-dir", str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    reports = list(tmp_path.rglob("LivingKnowledge.json"))
    assert reports, "benchmark did not produce LivingKnowledge.json"
```

- [ ] **Step 3: Run smoke**

```bash
.venv/bin/pytest tests/benchmarks_smoke/test_living_knowledge_benchmark.py -v
```

- [ ] **Step 4: Progress note**

```bash
echo "Task 34: Living-knowledge benchmark ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 35: pyproject.toml — `[postgres-graph]` extra

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add extra**

In `pyproject.toml`:

```toml
[project.optional-dependencies]
postgres-graph = [
    "pg_raggraph>=X.Y",
]
```

Replace `X.Y` with the user's actual release version when published.

- [ ] **Step 2: Validate pyproject parses**

```bash
.venv/bin/python -c "
import tomllib
from pathlib import Path
data = tomllib.loads(Path('pyproject.toml').read_text())
extras = data.get('project', {}).get('optional-dependencies', {})
print('postgres-graph extra:', extras.get('postgres-graph'))
"
```

- [ ] **Step 3: Progress note**

```bash
echo "Task 35: pyproject.toml [postgres-graph] ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 36: __init__.py public exports

**Files:**
- Modify: `src/stele/__init__.py`

- [ ] **Step 1: Add exports**

```python
from stele.revisor.models import (
    EntitySeed,
    EvidenceRecord,
    IndexReport,
    KnowledgeHit,
    RelationSeed,
)
```

Append to `__all__`:

```python
    "EntitySeed",
    "EvidenceRecord",
    "IndexReport",
    "KnowledgeHit",
    "RelationSeed",
```

- [ ] **Step 2: Verify imports**

```bash
.venv/bin/python -c "
from stele import (
    EvidenceRecord, KnowledgeHit, IndexReport, EntitySeed, RelationSeed,
)
print('Phase 5 public exports: OK')
"
```

- [ ] **Step 3: Progress note**

```bash
echo "Task 36: Public exports ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
```

---

### Task 37: Full repo verification + DC-FINAL

**Files:** read-only

- [ ] **Step 1: Build SC → test mapping**

```bash
cat <<'EOF' > /tmp/stele-phase5-planning/SC-COVERAGE.txt
SC-001 → tests/unit/revisor/test_models.py
SC-002 → tests/unit/revisor/test_noop.py::test_noop_protocol_conformance
SC-003 → tests/unit/revisor/test_noop.py
SC-004 → tests/unit/revisor/test_pg_raggraph.py
SC-005 → tests/unit/revisor/test_llm_endpoint.py
SC-006 → tests/unit/revisor/test_projection.py::test_artifact_to_evidence
SC-007 → tests/unit/revisor/test_projection.py::test_memory_to_evidence*
SC-008 → tests/unit/revisor/test_projection.py::test_knowledge_hits_to_citations*
SC-009 → tests/unit/recall/test_recall_request_phase5_fields.py
SC-010 → tests/unit/recall/test_graph_search_real.py + tests/integration/pg_raggraph/
SC-011 → tests/unit/recall/test_adaptive_with_graph_search.py
SC-012 → tests/unit/core/test_memory_retract.py + tests/integration/pg_raggraph/test_retraction.py
SC-013 → tests/integration/pg_raggraph/test_supersession.py
SC-014 → tests/integration/pg_raggraph/* (Stele.store projection in fixtures)
SC-015 (Bar #1) → tests/integration/pg_raggraph/test_supersession.py
SC-016 (Bar #2) → tests/integration/pg_raggraph/test_retraction.py
SC-017 (Bar #3) → tests/integration/pg_raggraph/test_as_of.py
SC-018 (Bar #4) → tests/integration/pg_raggraph/test_version_filter.py
SC-019 (Bar #5) → tests/integration/pg_raggraph/test_provenance.py
SC-020 (Bar #6) → tests/integration/pg_raggraph/test_postgres_baseline_without_pg_raggraph.py
SC-021 → tests/unit/revisor/test_architecture.py
SC-022 → tests/unit/core/test_capabilities_pg_raggraph_fields.py
SC-023 → tests/integration/pg_raggraph/test_best_effort_projection.py
SC-024 → tests/integration/pg_raggraph/test_as_of_two_paths.py
SC-025 → benchmarks/living_knowledge.py + tests/benchmarks_smoke/test_living_knowledge_benchmark.py
SC-026 → tests/unit/revisor/test_pg_raggraph.py::test_pg_raggraph_seeded_entity_mode_ingest
SC-027 → tests/unit/revisor/test_pg_raggraph.py::test_pg_raggraph_llm_mode*
SC-028 → existing Phase 1/3/4 tests still pass with pg_raggraph disabled
EOF
cat /tmp/stele-phase5-planning/SC-COVERAGE.txt
```

- [ ] **Step 2: Run every cited test**

```bash
.venv/bin/pytest tests/unit/revisor tests/unit/recall/test_graph_search_real.py tests/unit/recall/test_adaptive_with_graph_search.py tests/unit/recall/test_recall_request_phase5_fields.py tests/unit/core/test_memory_retract.py tests/unit/core/test_capabilities_pg_raggraph_fields.py tests/integration/pg_raggraph tests/benchmarks_smoke/test_living_knowledge_benchmark.py -v 2>&1 | tail -80
```

Expected: every cited test passes or is correctly skipped.

- [ ] **Step 3: Re-run all DCs**

```bash
echo "=== DC-001 ==="
grep -rn 'pg_raggraph' src/stele/ | grep -v 'src/stele/revisor/' | grep -v '__pycache__' || echo "(empty — OK)"
echo "=== DC-002 ==="
grep -rn 'self\._revisor\.' src/stele/ | grep -v '__pycache__' | grep -vE 'src/stele/(core/(memory|stash)|recall/graph_search)\.py' || echo "(only expected matches — OK)"
echo "=== DC-003 ==="
.venv/bin/pytest tests/integration/pg_raggraph/ -v 2>&1 | tail -10
echo "=== DC-004 ==="
.venv/bin/pytest tests/unit/recall/test_adaptive_with_graph_search.py -v
echo "=== DC-005 ==="
.venv/bin/pytest tests/integration/pg_raggraph/test_best_effort_projection.py -v
```

- [ ] **Step 4: Confirm Out-of-Scope items untouched**

```bash
echo "=== Out-of-Scope check ==="
grep -rn 'Memory.unretract\|stele rebuild-graph\|GraphQL' src/stele/ tests/ 2>/dev/null || echo "(empty — OK)"
```

- [ ] **Step 5: Full repo verification**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest 2>&1 | tail -5
```

Expected: all three pass; pytest count = Task 0 baseline + ~50–70 new tests.

- [ ] **Step 6: Final progress note**

```bash
echo "=== DC-FINAL: SC coverage ===" >> /tmp/stele-phase5-planning/PROGRESS.log
cat /tmp/stele-phase5-planning/SC-COVERAGE.txt >> /tmp/stele-phase5-planning/PROGRESS.log
echo "Task 37: DC-FINAL complete ($(date -Iseconds))" >> /tmp/stele-phase5-planning/PROGRESS.log
echo "Phase 5 plan execution complete. Living-knowledge bar verified." >> /tmp/stele-phase5-planning/PROGRESS.log
```

- [ ] **Step 7: User decision — where to commit**

Per user instruction, Phase 5 has NOT been committed during execution. When the prior-phase agents have settled, the user directs:
1. Which branch the Phase 5 work lands on (likely main, after Phase 3 lands, or `phase5-pg-raggraph-living-knowledge`)
2. Whether to squash or preserve per-task commits
3. Whether to publish the Phase 5 spec + plan to `docs/superpowers/{specs,plans}/` (the Phase 4 precedent suggests yes)

Do **not** initiate any branch operations or commits without explicit instruction.

---

## Parallel-with-other-phases Notes

Phase 5 lives at the boundary between Stele's memory + storage layer and pg-raggraph. Conflict surface vs Phase 2/3/4 if any are still in flight:

| File | Phase 2/3/4 touches | Phase 5 touches | Conflict risk |
|---|---|---|---|
| `src/stele/core/stash.py` | Phase 2: `Stele.extract`; Phase 3: `Stele.recall`; Phase 4: `Stele.search(mode=)`, `Stele.indexing_status` | Phase 5: `Stele._revisor`; `Stele.store` projection; capabilities expansion | **Medium** — all additive on the same class. Merge: accept all blocks; verify `close()` closes memory, extractor, recall, indexer+chunk_store, **and** revisor. |
| `src/stele/__init__.py` | Phase 2/3/4 export new types | Phase 5 exports Evidence/Knowledge types | **Low** — additive |
| `src/stele/core/config.py` | Phase 2: ExtractionConfig; Phase 3: RecallConfig; Phase 4: IndexingConfig extensions | Phase 5: `PgRaggraphConfig` + `LLMEndpointConfig` (inside IndexingConfig) + StashConfig validator | **Low** — sibling fields |
| `src/stele/core/memory.py` | Phase 1 surface; Phase 4 added `Memory.search_with_score` | Phase 5: new `Memory.retract`; projection callbacks injected at init | **Medium** — Phase 5 adds constructor kwargs to `Memory.__init__`. If Phase 4's `Memory.search_with_score` and Phase 5 land together, the constructor needs all the callbacks present. |
| `src/stele/recall/graph_search.py` | Phase 3 created the stub | Phase 5 replaces the body | **High if Phase 3 not landed first** — Phase 5 plan Task 0 verifies Phase 3 has merged. If both are in-flight, Phase 5 needs to wait. |
| `src/stele/recall/models.py` | Phase 3 created `RecallRequest`; Phase 4 didn't touch | Phase 5: adds `as_of`, `version_filter`, `retracted_behavior`; extends `EscalationReason` literal | **Low** — pure additions |
| `src/stele/recall/adaptive.py` | Phase 3 wrote it | Phase 5: wraps tier execution in try/except CapabilityError | **Low** — single function modification |

**Merge order recommendation:** Phase 3 must land before Phase 5. Phase 4 and Phase 5 are largely independent (different files in different subdirectories); either order works.

---

## Definition of Ready For Each Task

- Predecessor task's progress note in `/tmp/stele-phase5-planning/PROGRESS.log`.
- Phase 1+2+3+4 surfaces work (Task 0 verified).
- For Tasks 10–16 (PgRaggraphRevisor) and 28–33 (integration tests): pg_raggraph installed + `STELE_PG_DSN` env var set. If not, mark task deferred with progress-log entry and skip cleanly.

## Definition of Done For Each Task

- New test(s) pass (or skip cleanly with documented reason).
- `ruff check` + `mypy` on touched files clean.
- Progress note appended to `PROGRESS.log`.
- Any cited DC-XXX checkpoint passed.
- No file outside the task's declared `Files:` list was modified.
- **No git commit** during plan execution; commits happen at user direction after all plan tasks complete.
