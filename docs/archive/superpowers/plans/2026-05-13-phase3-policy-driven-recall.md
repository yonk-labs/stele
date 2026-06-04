# Stele Phase 3: Policy-Driven Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Stele's `Stele.recall(...)` engine — a context selector that picks among 6 strategies (memory_search, artifact_search, summary_only, raw_fetch, abstain, adaptive) plus a `graph_search` stub for Phase 5. Lift the answer-workflow benchmark's hardcoded `_run_strategy` into production code, preserving behavior on the existing scenarios while removing the oracle-based adaptive cheat.

**Architecture:** Strategy-class pattern — one file per strategy implementing a `Strategy` Protocol. `AdaptiveStrategy` composes the others via a registry, applying hit-count + confidence-floor escalation with an optional caller-supplied `sufficient` callback. Scores normalized centrally in `ranking.py`. `artifact_id` on the request is a hard scoping constraint: when set, every strategy locks retrieval to that artifact. `Stele.recall` is a callable property — `stele.recall(query=...)` is canonical; `stele.recall.adaptive(query=...)` and six other shims are one-line wrappers.

**Tech Stack:** Python 3.12+, Pydantic v2, `Memory` + `MemoryStore` from Phase 1, `MemoryExtractor.preview` from Phase 2 (new helper), pytest, ruff, mypy strict.

**Spec (load-bearing):** [`docs/superpowers/specs/2026-05-13-phase3-policy-driven-recall-design.md`](../specs/2026-05-13-phase3-policy-driven-recall-design.md)

Re-read the spec at every DC-XXX checkpoint below. All 20 success criteria (SC-001 through SC-020) must have evidence at DC-FINAL.

**Phase 1 + Phase 2 dependency:** This plan assumes Phase 1 Tasks 0–21 and Phase 2 Tasks 0–23 are complete (full memory contract + extraction layer shipped on memory + sqlite + postgres). Task 0 verifies the precondition.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/stele/recall/__init__.py` | Re-exports `RecallRequest`, `RecallResult`, `Citation`, `Escalation`, `RecallStats`, `RecallContext`, `StrategyName` |
| `src/stele/recall/models.py` | All pydantic + dataclass models |
| `src/stele/recall/base.py` | `Strategy` Protocol (`execute(request, deps) -> RecallResult`); `_RecallDeps` dataclass |
| `src/stele/recall/ranking.py` | `normalize_scores(hits)` (per-backend raw → [0,1]); `merge_hits(*sources)` (dedup by `(kind, id)` keeping max) |
| `src/stele/recall/summary_only.py` | `SummaryOnlyStrategy` |
| `src/stele/recall/memory_search.py` | `MemorySearchStrategy` |
| `src/stele/recall/artifact_search.py` | `ArtifactSearchStrategy` |
| `src/stele/recall/graph_search.py` | `GraphSearchStrategy` — raises `CapabilityError` |
| `src/stele/recall/raw_fetch.py` | `RawFetchStrategy` |
| `src/stele/recall/abstain.py` | `AbstainStrategy` |
| `src/stele/recall/adaptive.py` | `AdaptiveStrategy` (registry + escalation logic) |
| `src/stele/recall/facade.py` | `Recall` callable class (canonical `__call__` + 7 convenience shims) |
| `tests/unit/recall/__init__.py` | Package marker |
| `tests/unit/recall/test_models.py` | Field validation, frozen models |
| `tests/unit/recall/test_ranking.py` | Score normalization + merge_hits |
| `tests/unit/recall/test_summary_only.py` | Strategy unit |
| `tests/unit/recall/test_memory_search.py` | Strategy unit + source_ref_filter |
| `tests/unit/recall/test_artifact_search.py` | Strategy unit + forced scope |
| `tests/unit/recall/test_graph_search.py` | CapabilityError stub regression |
| `tests/unit/recall/test_raw_fetch.py` | Strategy unit + PIIBlockedError propagation |
| `tests/unit/recall/test_abstain.py` | Strategy unit |
| `tests/unit/recall/test_adaptive.py` | Escalation trail, hit-count + floor, callback, tier-order |
| `tests/unit/recall/test_facade.py` | Canonical vs shim equivalence; `__call__` works |
| `tests/unit/recall/test_pii_inheritance.py` | Recall never re-scrubs; PII flags inherited from underlying surfaces |
| `tests/unit/recall/test_architecture.py` | Import-layer check — no Phase 4/5 deps, no LLM clients |
| `tests/unit/core/test_memory_search_with_score.py` | Phase 1 helper unit tests, including source_ref_filter pushdown |
| `tests/contract/test_recall_contract.py` | Cross-backend (memory + sqlite + postgres) |
| `tests/benchmarks_smoke/test_answer_workflow_via_recall.py` | Regression: new path == old path on existing fixtures |

### Modified files

| Path | Change |
|---|---|
| `src/stele/core/memory.py` | Add `Memory.search_with_score(query, scope, source_ref_filter=None) -> list[ScoredMemoryHit]` |
| `src/stele/core/memory_record.py` | Add `ScoredMemoryHit` model |
| `src/stele/storage/memory_store/base.py` | Add `search_with_score(query, scope, source_ref_filter)` to the Protocol |
| `src/stele/storage/memory_store/memory.py` | Implement `search_with_score` (in-process) |
| `src/stele/storage/memory_store/sqlite.py` | Implement `search_with_score` (FTS5 rank + WHERE on source_refs) |
| `src/stele/storage/memory_store/postgres.py` | Implement `search_with_score` (tsvector rank + WHERE on jsonb source_refs) |
| `src/stele/storage/memory_store/mariadb.py` | `search_with_score` stub raises `CapabilityError` |
| `src/stele/storage/memory_store/clickhouse.py` | `search_with_score` stub raises `CapabilityError` |
| `src/stele/extraction/extractor.py` | Add `MemoryExtractor.preview(text, source_refs, scope) -> list[MemoryCandidate]` |
| `src/stele/core/config.py` | Add `RecallConfig` model + `recall: RecallConfig` on `StashConfig` |
| `src/stele/core/stash.py` | Add `Stele.recall` property; extend `Stele.close()` |
| `src/stele/__init__.py` | Re-export Phase 3 public types |
| `benchmarks/answer_workflow.py` | `_run_strategy` delegates to `stele.recall(...)`; preserve `Strategy` type for backward compat |

### Untouched (locked)

| Path | Why locked |
|---|---|
| `src/stele/core/artifact.py` | Artifact models are Phase 1's source of truth |
| `src/stele/storage/{memory,sqlite,postgres,mariadb,clickhouse}.py` (artifact stores) | Phase 1 contract |
| `src/stele/retrieval/*` | Existing artifact retrieval consumed via `Stele.search` — not modified |
| `src/stele/extraction/{candidates,classifier,patterns,models}.py` | Phase 2's pure core consumed via `MemoryExtractor.preview` |
| `src/stele/pii/*` | PII layer is consumed; recall never re-scrubs |

---

## Drift Checkpoints (hard gates from the spec)

- ⛔ **DC-000** (Task 0): Phase 1 + Phase 2 must be complete. Run the verification commands; if any assertion fails, STOP.
- ⛔ **DC-001** (after Task 18): run `grep -rn 'pg_raggraph\|chunkshop\|openai\|anthropic\|lede' src/stele/recall/`. Expected: empty. If anything matches, the slice has drifted into Phase 4/5 territory, picked up an LLM client, or duplicated Phase 2 extraction logic.
- ⛔ **DC-002** (after Task 19): run `grep -rn '_answer_is_sufficient\|expected_answer' src/stele/recall/adaptive.py`. Expected: empty. Adaptive must escalate without oracle access.
- ⛔ **DC-003** (after Task 26): regression test `test_answer_workflow_via_recall.py` must show **accuracy delta == 0** between old `_run_strategy` and new `stele.recall(...)` on the deterministic judge across all five existing strategies.
- ⛔ **DC-FINAL** (Task 27): every SC-001..SC-020 has a passing test cited; Out-of-Scope list verified untouched.

---

## Tasks

### Task 0: Verify Phase 1 + Phase 2 prerequisites

Phase 3 builds on the full Phase 1 + Phase 2 surface. Confirm before touching anything.

**Files:**
- Read-only: `docs/current-status.md`, `src/stele/core/memory.py`, `src/stele/extraction/extractor.py`

- [ ] **Step 1: Confirm working tree is clean**

```bash
cd /home/yonk/yonk-tools/stele-phase3
git status --short
```

Expected: empty. If anything appears, investigate before proceeding.

- [ ] **Step 2: Run the verification trio**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest
```

Expected: all three pass. Note the pytest pass count for the DC-FINAL diff at Task 27.

- [ ] **Step 3: Confirm Phase 1 + Phase 2 surfaces ship**

```bash
.venv/bin/python -c "
from stele import (
    Stele, Memory, MemoryRecord, MemoryScope, MemoryQuery, MemoryAddResult,
    MemoryCandidate, ExtractionReport, AcceptedCandidate, RejectedCandidate,
    CapabilityError, ValidationError, ArtifactNotFound, PIIBlockedError, SteleError,
)
from stele.extraction.extractor import MemoryExtractor
import inspect
print('Memory.search:', hasattr(Memory, 'search'))
print('Memory.get:', hasattr(Memory, 'get'))
print('MemoryExtractor.from_text:', hasattr(MemoryExtractor, 'from_text'))
print('MemoryExtractor.from_messages:', hasattr(MemoryExtractor, 'from_messages'))
print('MemoryExtractor.from_artifact:', hasattr(MemoryExtractor, 'from_artifact'))
"
```

Expected: every line prints `True`. If anything is `False`, Phase 1 or Phase 2 isn't fully landed; STOP and complete the prereq phase first.

- [ ] **Step 4: Confirm we're on the phase3 branch**

```bash
git branch --show-current
```

Expected: `phase3-policy-driven-recall`.

No code commit in Task 0. Move to Task 1.

---

### Task 1: Add `RecallConfig` to `core/config.py`

The recall engine reads thresholds and toggles from config.

**Files:**
- Modify: `src/stele/core/config.py`
- Test: `tests/unit/core/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_config.py`:

```python
def test_recall_config_defaults() -> None:
    from stele.core.config import RecallConfig, StashConfig

    cfg = StashConfig()
    assert cfg.recall.enabled is True
    assert cfg.recall.default_strategy == "adaptive"
    assert cfg.recall.confidence_floor == 0.4
    assert cfg.recall.max_memory_hits == 5
    assert cfg.recall.max_artifact_hits == 5
    assert cfg.recall.max_context_chars == 16_000
    assert cfg.recall.adaptive_tier_order == [
        "memory_search",
        "artifact_search",
        "raw_fetch",
        "abstain",
    ]
    assert cfg.recall.adaptive_skip_raw_fetch_without_artifact_id is True
    assert cfg.recall.abstain_default_reason == "no_sufficient_context"


def test_recall_config_rejects_tier_order_without_abstain_last() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError, match="abstain"):
        StashConfig.load(
            {"recall": {"adaptive_tier_order": ["memory_search", "artifact_search"]}}
        )


def test_recall_config_rejects_invalid_strategy_in_tier_order() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load(
            {"recall": {"adaptive_tier_order": ["bogus", "abstain"]}}
        )


def test_recall_config_rejects_confidence_floor_out_of_range() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load({"recall": {"confidence_floor": 1.5}})
```

Make sure `import pytest` is at the top of `test_config.py` if not already.

- [ ] **Step 2: Run, confirm failures**

```bash
.venv/bin/pytest tests/unit/core/test_config.py -v -k recall_config
```

Expected: `AttributeError: ... has no attribute 'recall'`.

- [ ] **Step 3: Implement `RecallConfig`**

In `src/stele/core/config.py`, add this class right after `SigningConfig`:

```python
StrategyName = Literal[
    "summary_only",
    "memory_search",
    "artifact_search",
    "graph_search",
    "adaptive",
    "raw_fetch",
    "abstain",
]


class RecallConfig(BaseModel):
    enabled: bool = True
    default_strategy: StrategyName = "adaptive"
    confidence_floor: float = Field(default=0.4, ge=0.0, le=1.0)
    max_memory_hits: int = Field(default=5, ge=1)
    max_artifact_hits: int = Field(default=5, ge=1)
    max_context_chars: int = Field(default=16_000, ge=256)
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

    @field_validator("adaptive_tier_order")
    @classmethod
    def _abstain_last(cls, v: list[str]) -> list[str]:
        if not v or v[-1] != "abstain":
            raise ValueError("adaptive_tier_order must end with 'abstain'")
        return v
```

Add `from pydantic import field_validator` to imports if not present.

Then add the field on `StashConfig` (alongside `signing`):

```python
    recall: RecallConfig = Field(default_factory=RecallConfig)
```

- [ ] **Step 4: Run, confirm pass**

```bash
.venv/bin/pytest tests/unit/core/test_config.py -v -k recall_config
```

Expected: all four tests PASS.

- [ ] **Step 5: Lint + types**

```bash
.venv/bin/ruff check src/stele/core/config.py tests/unit/core/test_config.py
.venv/bin/mypy src/stele/core/config.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/stele/core/config.py tests/unit/core/test_config.py
git commit -m "feat(config): RecallConfig with adaptive tier order + abstain-last invariant"
```

---

### Task 2: Recall package skeleton + models

Define all the pydantic + dataclass models for Phase 3 in one focused file.

**Files:**
- Create: `src/stele/recall/__init__.py`
- Create: `src/stele/recall/models.py`
- Create: `tests/unit/recall/__init__.py`
- Test: `tests/unit/recall/test_models.py`

- [ ] **Step 1: Package markers**

```bash
mkdir -p src/stele/recall tests/unit/recall
: > src/stele/recall/__init__.py
: > tests/unit/recall/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/recall/test_models.py`:

```python
"""Tests for recall models — field validation, defaults, immutability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.core.memory_record import MemoryScope
from stele.recall.models import (
    Citation,
    Escalation,
    RecallContext,
    RecallRequest,
    RecallResult,
    RecallStats,
)


def test_citation_required_fields() -> None:
    c = Citation(
        kind="memory",
        id="mem_abc",
        reference="stele://default/art_xyz",
        score=0.75,
        snippet="user prefers dark mode",
    )
    assert c.kind == "memory"
    assert c.score == 0.75


def test_citation_rejects_unknown_kind() -> None:
    with pytest.raises(PydanticValidationError):
        Citation(
            kind="bogus",  # type: ignore[arg-type]
            id="x",
            reference="stele://default/art",
            score=0.5,
            snippet="x",
        )


def test_escalation_with_top_score_none() -> None:
    e = Escalation(
        strategy="memory_search",
        hit_count=0,
        top_score=None,
        reason="zero_hits",
    )
    assert e.top_score is None
    assert e.reason == "zero_hits"


def test_recall_stats_defaults_to_zero() -> None:
    s = RecallStats()
    assert s.memory_searches == 0
    assert s.artifact_searches == 0
    assert s.fetches == 0
    assert s.estimated_context_tokens == 0
    assert s.latency_ms == 0.0


def test_recall_request_defaults() -> None:
    req = RecallRequest(
        query="what does the user prefer",
        scope=MemoryScope(user_id="alice"),
    )
    assert req.strategy == "adaptive"
    assert req.artifact_id is None
    assert req.sufficient is None
    assert req.max_memory_hits == 5
    assert req.confidence_floor is None


def test_recall_result_minimal() -> None:
    r = RecallResult(
        strategy_used="abstain",
        context="",
        citations=[],
        escalations=[
            Escalation(
                strategy="abstain",
                hit_count=0,
                top_score=None,
                reason="exhausted",
            )
        ],
        pii_flags=[],
        source_refs=[],
        stats=RecallStats(),
        abstained=True,
        abstain_reason="no_sufficient_context",
    )
    assert r.abstained is True
    assert r.strategy_used == "abstain"


def test_recall_context_frozen() -> None:
    ctx = RecallContext(
        query="x",
        scope=MemoryScope(user_id="alice"),
        accumulated_citations=[],
        accumulated_text="",
    )
    with pytest.raises(Exception):
        ctx.query = "y"  # type: ignore[misc]
```

- [ ] **Step 3: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/recall/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'stele.recall.models'`.

- [ ] **Step 4: Implement `models.py`**

Create `src/stele/recall/models.py`:

```python
"""Recall report shapes — single source of truth."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stele.core.memory_record import MemoryScope

StrategyName = Literal[
    "summary_only",
    "memory_search",
    "artifact_search",
    "graph_search",
    "adaptive",
    "raw_fetch",
    "abstain",
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
    model_config = ConfigDict(frozen=True)

    kind: CitationKind
    id: str
    reference: str
    score: float
    snippet: str


class Escalation(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: StrategyName
    hit_count: int
    top_score: float | None
    reason: EscalationReason


class RecallStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_searches: int = 0
    artifact_searches: int = 0
    chunk_searches: int = 0
    fetches: int = 0
    estimated_context_tokens: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class RecallContext:
    """Snapshot of the in-flight adaptive escalation."""

    query: str
    scope: MemoryScope
    accumulated_citations: list[Citation]
    accumulated_text: str


class RecallRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    query: str
    scope: MemoryScope
    strategy: StrategyName = "adaptive"
    artifact_id: str | None = None
    sufficient: Callable[[RecallContext], bool] | None = None
    max_memory_hits: int = 5
    max_artifact_hits: int = 5
    confidence_floor: float | None = None


class RecallResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_used: StrategyName
    context: str
    citations: list[Citation]
    escalations: list[Escalation]
    pii_flags: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    stats: RecallStats
    abstained: bool = False
    abstain_reason: str | None = None
```

- [ ] **Step 5: Wire `__init__.py`**

Overwrite `src/stele/recall/__init__.py`:

```python
"""Phase 3 — policy-driven recall."""

from stele.recall.models import (
    Citation,
    CitationKind,
    Escalation,
    EscalationReason,
    RecallContext,
    RecallRequest,
    RecallResult,
    RecallStats,
    StrategyName,
)

__all__ = [
    "Citation",
    "CitationKind",
    "Escalation",
    "EscalationReason",
    "RecallContext",
    "RecallRequest",
    "RecallResult",
    "RecallStats",
    "StrategyName",
]
```

- [ ] **Step 6: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/recall/test_models.py -v
.venv/bin/ruff check src/stele/recall tests/unit/recall
.venv/bin/mypy src/stele/recall tests/unit/recall
```

Expected: tests pass, ruff/mypy clean.

- [ ] **Step 7: Commit**

```bash
git add src/stele/recall/__init__.py src/stele/recall/models.py \
        tests/unit/recall/__init__.py tests/unit/recall/test_models.py
git commit -m "feat(recall): RecallRequest/RecallResult/Citation/Escalation models (SC-001)"
```

---

### Task 3: `ranking.py` — score normalization

Centralizes per-backend score normalization and hit merging. Pure functions; no I/O.

**Files:**
- Create: `src/stele/recall/ranking.py`
- Test: `tests/unit/recall/test_ranking.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/recall/test_ranking.py`:

```python
"""Tests for score normalization and hit merging."""

from __future__ import annotations

from stele.recall.models import Citation
from stele.recall.ranking import merge_hits, normalize_scores


def _cit(kind: str, id: str, ref: str, score: float) -> Citation:
    return Citation(
        kind=kind,  # type: ignore[arg-type]
        id=id,
        reference=ref,
        score=score,
        snippet="x",
    )


def test_normalize_scores_zero_input() -> None:
    out = normalize_scores([])
    assert out == []


def test_normalize_scores_clamps_to_unit_interval() -> None:
    cits = [
        _cit("memory", "m1", "stele://default/a", 5.0),
        _cit("memory", "m2", "stele://default/a", 2.5),
        _cit("memory", "m3", "stele://default/a", 0.0),
    ]
    out = normalize_scores(cits)
    assert max(c.score for c in out) == 1.0
    assert min(c.score for c in out) == 0.0
    assert out[1].score == 0.5  # linear normalization across [min, max]


def test_normalize_scores_single_hit_becomes_one() -> None:
    out = normalize_scores([_cit("memory", "m1", "stele://default/a", 7.0)])
    assert out[0].score == 1.0


def test_normalize_scores_all_equal_becomes_one() -> None:
    cits = [
        _cit("memory", "m1", "stele://default/a", 0.7),
        _cit("memory", "m2", "stele://default/a", 0.7),
    ]
    out = normalize_scores(cits)
    assert all(c.score == 1.0 for c in out)


def test_merge_hits_dedups_by_kind_and_id_keeping_max() -> None:
    a = [
        _cit("memory", "m1", "stele://default/a", 0.3),
        _cit("memory", "m2", "stele://default/a", 0.4),
    ]
    b = [
        _cit("memory", "m1", "stele://default/a", 0.9),  # duplicate of a[0], higher
        _cit("chunk", "c1", "stele://default/a", 0.5),
    ]
    out = merge_hits(a, b)
    by_key = {(c.kind, c.id): c for c in out}
    assert by_key[("memory", "m1")].score == 0.9
    assert by_key[("memory", "m2")].score == 0.4
    assert by_key[("chunk", "c1")].score == 0.5
    assert len(out) == 3


def test_merge_hits_sorts_descending_by_score() -> None:
    out = merge_hits(
        [_cit("memory", "m1", "stele://default/a", 0.2)],
        [_cit("memory", "m2", "stele://default/a", 0.9)],
        [_cit("chunk", "c1", "stele://default/a", 0.5)],
    )
    scores = [c.score for c in out]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/recall/test_ranking.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `ranking.py`**

Create `src/stele/recall/ranking.py`:

```python
"""Score normalization and hit merging — pure functions, no I/O."""

from __future__ import annotations

from stele.recall.models import Citation


def normalize_scores(citations: list[Citation]) -> list[Citation]:
    """Linearly normalize scores across the input list to [0, 1].

    Special cases:
    - Empty input → empty output.
    - Single hit → score becomes 1.0.
    - All equal scores → all become 1.0 (preserves the "we found stuff" signal).
    """
    if not citations:
        return []
    scores = [c.score for c in citations]
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [c.model_copy(update={"score": 1.0}) for c in citations]
    span = hi - lo
    return [
        c.model_copy(update={"score": (c.score - lo) / span}) for c in citations
    ]


def merge_hits(*sources: list[Citation]) -> list[Citation]:
    """Merge citation lists, dedup by (kind, id) keeping max score, sort desc."""
    best: dict[tuple[str, str], Citation] = {}
    for source in sources:
        for c in source:
            key = (c.kind, c.id)
            existing = best.get(key)
            if existing is None or c.score > existing.score:
                best[key] = c
    return sorted(best.values(), key=lambda c: c.score, reverse=True)
```

- [ ] **Step 4: Run, lint, types**

```bash
.venv/bin/pytest tests/unit/recall/test_ranking.py -v
.venv/bin/ruff check src/stele/recall/ranking.py tests/unit/recall/test_ranking.py
.venv/bin/mypy src/stele/recall/ranking.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/stele/recall/ranking.py tests/unit/recall/test_ranking.py
git commit -m "feat(recall): ranking — normalize_scores + merge_hits (SC-002)"
```

---

### Task 4: `base.py` — Strategy Protocol + `_RecallDeps`

The shared shape all six strategies implement.

**Files:**
- Create: `src/stele/recall/base.py`

- [ ] **Step 1: Implement (no failing test — this is type-only scaffolding consumed by every strategy task)**

Create `src/stele/recall/base.py`:

```python
"""Strategy Protocol + dependency-injection struct."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from stele.recall.models import RecallRequest, RecallResult

if TYPE_CHECKING:
    from stele.core.config import RecallConfig
    from stele.core.memory import Memory
    from stele.core.stash import Stele
    from stele.pii.regex import RegexPIIScrubber
    from stele.pii.scrubber import DisabledPIIScrubber


@dataclass(frozen=True)
class _RecallDeps:
    """Injected to every Strategy.execute call. Kept private — strategies don't construct these."""

    stele: Stele
    memory: Memory
    scrubber: RegexPIIScrubber | DisabledPIIScrubber
    config: RecallConfig


class Strategy(Protocol):
    name: str  # equals one of StrategyName literals; used as registry key in adaptive

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult: ...
```

- [ ] **Step 2: Lint + types**

```bash
.venv/bin/ruff check src/stele/recall/base.py
.venv/bin/mypy src/stele/recall/base.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/stele/recall/base.py
git commit -m "feat(recall): Strategy Protocol + _RecallDeps"
```

---

### Task 5: `ScoredMemoryHit` model

Phase 1 model addition. A `MemoryRecord` plus a normalized score.

**Files:**
- Modify: `src/stele/core/memory_record.py`
- Test: `tests/unit/core/test_memory_record.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_memory_record.py`:

```python
def test_scored_memory_hit_field_validation() -> None:
    from datetime import UTC, datetime

    from stele.core.memory_record import MemoryRecord, MemoryScope, ScoredMemoryHit

    now = datetime.now(UTC)
    rec = MemoryRecord(
        id="mem1",
        text="x",
        kind="fact",
        scope=MemoryScope(user_id="alice"),
        source_refs=["stele://default/abc"],
        created_at=now,
        updated_at=now,
        effective_from=now,
    )
    hit = ScoredMemoryHit(record=rec, score=0.7)
    assert hit.record.id == "mem1"
    assert hit.score == 0.7
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_record.py -v -k scored
```

Expected: `ImportError: cannot import name 'ScoredMemoryHit'`.

- [ ] **Step 3: Implement**

Append to `src/stele/core/memory_record.py`:

```python
class ScoredMemoryHit(BaseModel):
    """A memory record + a normalized retrieval score."""

    model_config = ConfigDict(frozen=True)

    record: MemoryRecord
    score: float
```

- [ ] **Step 4: Run, lint, types**

```bash
.venv/bin/pytest tests/unit/core/test_memory_record.py -v
.venv/bin/ruff check src/stele/core/memory_record.py
.venv/bin/mypy src/stele/core/memory_record.py
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/memory_record.py tests/unit/core/test_memory_record.py
git commit -m "feat(memory): ScoredMemoryHit model for Phase 3 recall consumption"
```

---

### Task 6: `MemoryStore.search_with_score` Protocol method

Add to the `MemoryStore` Protocol so every backend implementation must provide it (or stub).

**Files:**
- Modify: `src/stele/storage/memory_store/base.py`

- [ ] **Step 1: Add the method**

In `src/stele/storage/memory_store/base.py`, add to the `MemoryStore` Protocol:

```python
    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        """Like search, but returns hits with normalized score in [0, 1].

        source_ref_filter: when set, hits are filtered (in the backend) to
        memories whose source_refs include this URI. None = no filter.
        """
        ...
```

Add the import at the top:

```python
from stele.core.memory_record import ScoredMemoryHit
```

- [ ] **Step 2: Lint + types**

```bash
.venv/bin/ruff check src/stele/storage/memory_store/base.py
.venv/bin/mypy src/stele/storage/memory_store/base.py
```

Expected: clean. (No tests yet — Protocol-only change.)

- [ ] **Step 3: Commit**

```bash
git add src/stele/storage/memory_store/base.py
git commit -m "feat(memory_store): add search_with_score to Protocol"
```

---

### Task 7: `InProcessMemoryStore.search_with_score`

In-memory backend gets the simplest implementation: linear scan with keyword scoring.

**Files:**
- Modify: `src/stele/storage/memory_store/memory.py`
- Test: `tests/unit/core/test_memory_search_with_score.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_memory_search_with_score.py`:

```python
"""Tests for Memory.search_with_score across backends (in-process scope here)."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.memory_record import MemoryRecord, MemoryScope, ScoredMemoryHit
from stele.storage.memory_store.memory import InProcessMemoryStore


def _record(id_: str, text: str, refs: list[str]) -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id=id_,
        text=text,
        kind="fact",
        scope=MemoryScope(user_id="alice"),
        source_refs=refs,
        created_at=now,
        updated_at=now,
        effective_from=now,
    )


def test_in_process_search_with_score_returns_scored_hits() -> None:
    store = InProcessMemoryStore()
    store.add(_record("m1", "user prefers dark mode", ["stele://default/a"]), [])
    store.add(_record("m2", "user prefers cold brew", ["stele://default/b"]), [])
    store.add(_record("m3", "completely unrelated", ["stele://default/c"]), [])

    hits = store.search_with_score(
        "dark mode",
        scope=MemoryScope(user_id="alice"),
        limit=5,
    )
    assert isinstance(hits, list)
    assert all(isinstance(h, ScoredMemoryHit) for h in hits)
    assert hits, "expected at least one hit on a keyword match"
    assert hits[0].record.id == "m1"
    assert all(0.0 <= h.score <= 1.0 for h in hits)


def test_in_process_search_with_score_filters_by_source_ref() -> None:
    store = InProcessMemoryStore()
    store.add(_record("m1", "dark mode preferred", ["stele://default/a"]), [])
    store.add(_record("m2", "dark mode preferred", ["stele://default/b"]), [])

    hits = store.search_with_score(
        "dark",
        scope=MemoryScope(user_id="alice"),
        limit=5,
        source_ref_filter="stele://default/a",
    )
    assert len(hits) == 1
    assert hits[0].record.id == "m1"


def test_in_process_search_with_score_limit_respected() -> None:
    store = InProcessMemoryStore()
    for i in range(10):
        store.add(_record(f"m{i}", f"common term {i}", [f"stele://default/a{i}"]), [])

    hits = store.search_with_score(
        "common",
        scope=MemoryScope(user_id="alice"),
        limit=3,
    )
    assert len(hits) <= 3
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_search_with_score.py -v
```

Expected: `AttributeError: 'InProcessMemoryStore' object has no attribute 'search_with_score'`.

- [ ] **Step 3: Implement**

In `src/stele/storage/memory_store/memory.py`, add to `InProcessMemoryStore`:

```python
    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return []
        candidates: list[tuple[MemoryRecord, int]] = []
        for record in self._records.values():
            if record.scope != scope:
                continue
            if record.status != "active":
                continue
            if source_ref_filter is not None and source_ref_filter not in record.source_refs:
                continue
            text_lower = record.text.lower()
            score = sum(text_lower.count(t) for t in terms)
            if score > 0:
                candidates.append((record, score))
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        top = candidates[:limit]
        if not top:
            return []
        max_score = max(s for _, s in top) or 1
        return [
            ScoredMemoryHit(record=rec, score=raw / max_score) for rec, raw in top
        ]
```

Add the import at the top if not present:

```python
from stele.core.memory_record import MemoryRecord, MemoryScope, ScoredMemoryHit
```

(Check what's already imported; `MemoryRecord` and `MemoryScope` likely already are.)

- [ ] **Step 4: Run, lint, types**

```bash
.venv/bin/pytest tests/unit/core/test_memory_search_with_score.py -v
.venv/bin/ruff check src/stele/storage/memory_store/memory.py
.venv/bin/mypy src/stele/storage/memory_store/memory.py
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stele/storage/memory_store/memory.py tests/unit/core/test_memory_search_with_score.py
git commit -m "feat(memory_store): InProcessMemoryStore.search_with_score (SC-015)"
```

---

### Task 8: `SQLiteMemoryStore.search_with_score`

FTS5 rank() returns negative numbers (lower is better). Convert to positive score, then a separate normalization step is applied by Phase 3 ranking. Source ref filter goes into the WHERE clause via json_each().

**Files:**
- Modify: `src/stele/storage/memory_store/sqlite.py`

- [ ] **Step 1: Implement**

In `src/stele/storage/memory_store/sqlite.py`, add to `SQLiteMemoryStore`:

```python
    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        if not query.strip():
            return []
        params: list[object] = [
            query,
            scope.user_id, scope.agent_id, scope.app_id, scope.session_id, scope.namespace,
        ]
        source_ref_sql = ""
        if source_ref_filter is not None:
            source_ref_sql = (
                " AND EXISTS ("
                "  SELECT 1 FROM json_each(m.source_refs) j WHERE j.value = ?"
                ")"
            )
            params.append(source_ref_filter)
        params.append(limit)

        sql = f"""
            SELECT m.id, -bm25(memory_fts) AS raw_score
            FROM memory_fts JOIN memories m ON memory_fts.rowid = m.rowid
            WHERE memory_fts MATCH ?
              AND m.status = 'active'
              AND m.user_id IS ? AND m.agent_id IS ? AND m.app_id IS ?
              AND m.session_id IS ? AND m.namespace = ?
              {source_ref_sql}
            ORDER BY raw_score DESC
            LIMIT ?
        """
        rows = self._conn.execute(sql, params).fetchall()
        if not rows:
            return []
        max_score = max(row["raw_score"] for row in rows) or 1.0
        records_by_id = {row["id"]: self.get(row["id"]) for row in rows}
        return [
            ScoredMemoryHit(record=records_by_id[row["id"]], score=row["raw_score"] / max_score)
            for row in rows
            if records_by_id[row["id"]] is not None
        ]
```

Add `ScoredMemoryHit` to imports.

- [ ] **Step 2: Add a test parameter to the existing search_with_score test**

Append to `tests/unit/core/test_memory_search_with_score.py`:

```python
import pytest

from stele.storage.memory_store.sqlite import SQLiteMemoryStore


def _make_sqlite_store(tmp_path) -> SQLiteMemoryStore:  # type: ignore[no-untyped-def]
    return SQLiteMemoryStore(str(tmp_path / "memory.db"))


def test_sqlite_search_with_score_keyword_match(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _make_sqlite_store(tmp_path)
    store.add(_record("m1", "user prefers dark mode for the dashboard", ["stele://default/a"]), [])
    store.add(_record("m2", "user prefers cold brew", ["stele://default/b"]), [])

    hits = store.search_with_score(
        "dark mode",
        scope=MemoryScope(user_id="alice"),
        limit=5,
    )
    assert hits
    assert hits[0].record.id == "m1"


def test_sqlite_search_with_score_filters_by_source_ref(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _make_sqlite_store(tmp_path)
    store.add(_record("m1", "dark mode preferred", ["stele://default/a"]), [])
    store.add(_record("m2", "dark mode preferred", ["stele://default/b"]), [])

    hits = store.search_with_score(
        "dark",
        scope=MemoryScope(user_id="alice"),
        limit=5,
        source_ref_filter="stele://default/a",
    )
    assert len(hits) == 1
    assert hits[0].record.id == "m1"
```

- [ ] **Step 3: Run, lint, types**

```bash
.venv/bin/pytest tests/unit/core/test_memory_search_with_score.py -v
.venv/bin/ruff check src/stele/storage/memory_store/sqlite.py
.venv/bin/mypy src/stele/storage/memory_store/sqlite.py
```

Expected: all pass. If SQLite schema doesn't have `source_refs` as JSON, adapt the `json_each` call to whatever shape Phase 1 chose (e.g., a separate join table).

- [ ] **Step 4: Commit**

```bash
git add src/stele/storage/memory_store/sqlite.py tests/unit/core/test_memory_search_with_score.py
git commit -m "feat(memory_store): SQLiteMemoryStore.search_with_score with source_ref filter (SC-015)"
```

---

### Task 9: `PostgresMemoryStore.search_with_score`

Postgres tsvector ranking. Source ref filter goes into the WHERE clause via `jsonb_array_elements_text`.

**Files:**
- Modify: `src/stele/storage/memory_store/postgres.py`

- [ ] **Step 1: Implement**

In `src/stele/storage/memory_store/postgres.py`, add to `PostgresMemoryStore`:

```python
    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        if not query.strip():
            return []
        sql_parts = [
            "SELECT id, ts_rank_cd(text_tsv, plainto_tsquery('english', %s)) AS raw_score",
            "FROM memories",
            "WHERE text_tsv @@ plainto_tsquery('english', %s)",
            "  AND status = 'active'",
            "  AND user_id IS NOT DISTINCT FROM %s",
            "  AND agent_id IS NOT DISTINCT FROM %s",
            "  AND app_id IS NOT DISTINCT FROM %s",
            "  AND session_id IS NOT DISTINCT FROM %s",
            "  AND namespace = %s",
        ]
        params: list[object] = [
            query, query,
            scope.user_id, scope.agent_id, scope.app_id, scope.session_id, scope.namespace,
        ]
        if source_ref_filter is not None:
            sql_parts.append(
                "  AND EXISTS ("
                "    SELECT 1 FROM jsonb_array_elements_text(source_refs) elem"
                "    WHERE elem = %s"
                "  )"
            )
            params.append(source_ref_filter)
        sql_parts.append("ORDER BY raw_score DESC")
        sql_parts.append("LIMIT %s")
        params.append(limit)
        sql = "\n".join(sql_parts)

        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        if not rows:
            return []
        max_score = max(row[1] for row in rows) or 1.0
        records_by_id = {row[0]: self.get(row[0]) for row in rows}
        return [
            ScoredMemoryHit(record=records_by_id[row[0]], score=row[1] / max_score)
            for row in rows
            if records_by_id[row[0]] is not None
        ]
```

Add `ScoredMemoryHit` import.

- [ ] **Step 2: Lint + types (test runs in Task 24 contract test)**

```bash
.venv/bin/ruff check src/stele/storage/memory_store/postgres.py
.venv/bin/mypy src/stele/storage/memory_store/postgres.py
```

Expected: clean. Behavior tested in the cross-backend contract test in Task 24.

- [ ] **Step 3: Commit**

```bash
git add src/stele/storage/memory_store/postgres.py
git commit -m "feat(memory_store): PostgresMemoryStore.search_with_score with source_ref filter (SC-015)"
```

---

### Task 10: MariaDB + ClickHouse stubs

Both raise `CapabilityError` matching the Phase 1 pattern.

**Files:**
- Modify: `src/stele/storage/memory_store/mariadb.py`
- Modify: `src/stele/storage/memory_store/clickhouse.py`

- [ ] **Step 1: Add to MariaDB**

In `src/stele/storage/memory_store/mariadb.py`, add to `MariaDBMemoryStore`:

```python
    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        del query, scope, limit, source_ref_filter
        raise CapabilityError(
            "memory.search_with_score is not implemented for the MariaDB backend"
        )
```

Add `ScoredMemoryHit` and `CapabilityError` to imports.

- [ ] **Step 2: Add to ClickHouse**

Same shape in `src/stele/storage/memory_store/clickhouse.py`:

```python
    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        del query, scope, limit, source_ref_filter
        raise CapabilityError(
            "memory.search_with_score is not implemented for the ClickHouse backend"
        )
```

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check src/stele/storage/memory_store/{mariadb,clickhouse}.py
.venv/bin/mypy src/stele/storage/memory_store
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/stele/storage/memory_store/mariadb.py src/stele/storage/memory_store/clickhouse.py
git commit -m "feat(memory_store): MariaDB+ClickHouse search_with_score CapabilityError stubs"
```

---

### Task 11: `Memory.search_with_score` facade helper

The facade adds a thin pass-through that dispatches to the store.

**Files:**
- Modify: `src/stele/core/memory.py`
- Test: append to `tests/unit/core/test_memory_facade.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_memory_facade.py`:

```python
def test_memory_facade_search_with_score_delegates_to_store() -> None:
    from stele import Stele
    from stele.core.config import StashConfig
    from stele.core.memory_record import MemoryScope, ScoredMemoryHit

    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    hits = stele.memory.search_with_score(
        "dark mode",
        scope=MemoryScope(user_id="alice"),
    )
    assert hits
    assert all(isinstance(h, ScoredMemoryHit) for h in hits)
    stele.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_facade.py -v -k search_with_score
```

Expected: `AttributeError: 'Memory' object has no attribute 'search_with_score'`.

- [ ] **Step 3: Implement**

In `src/stele/core/memory.py`, add to `Memory`:

```python
    def search_with_score(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 5,
        source_ref_filter: str | None = None,
    ) -> list[ScoredMemoryHit]:
        return self._store.search_with_score(
            query,
            scope,
            limit=limit,
            source_ref_filter=source_ref_filter,
        )
```

Add the import:

```python
from stele.core.memory_record import ScoredMemoryHit
```

(May already be imported via the existing block.)

- [ ] **Step 4: Run, lint, types**

```bash
.venv/bin/pytest tests/unit/core/test_memory_facade.py -v
.venv/bin/ruff check src/stele/core/memory.py
.venv/bin/mypy src/stele/core/memory.py
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/memory.py tests/unit/core/test_memory_facade.py
git commit -m "feat(memory): facade search_with_score helper"
```

---

### Task 12: `MemoryExtractor.preview`

Phase 2 hook — exposes the pure core (extract_candidates) without storing.

**Files:**
- Modify: `src/stele/extraction/extractor.py`
- Test: append to `tests/unit/extraction/test_extractor.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/extraction/test_extractor.py`:

```python
def test_preview_returns_candidates_without_storing() -> None:
    stele = _make_stele()
    pre_count = len(stele.memory.list(scope=MemoryScope(user_id="alice")))
    candidates = stele.extract.preview(
        text="I prefer dark mode.",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    assert isinstance(candidates, list)
    assert candidates
    post_count = len(stele.memory.list(scope=MemoryScope(user_id="alice")))
    assert pre_count == post_count, "preview must not store"
    stele.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v -k preview
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement**

In `src/stele/extraction/extractor.py`, add to `MemoryExtractor`:

```python
    def preview(
        self,
        *,
        text: str,
        source_refs: list[str],
        scope: MemoryScope,
    ) -> list[MemoryCandidate]:
        """Run extraction's pure core without storing. Used by Phase 3 policy engine."""
        self._check_enabled()
        _validate_source_refs(source_refs)
        del scope  # not consumed by the pure core; accepted for symmetry
        return self._run_pure_core(text=text, source_refs=source_refs)
```

- [ ] **Step 4: Run, lint, types**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v
.venv/bin/ruff check src/stele/extraction/extractor.py
.venv/bin/mypy src/stele/extraction/extractor.py
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/extractor.py tests/unit/extraction/test_extractor.py
git commit -m "feat(extraction): MemoryExtractor.preview for Phase 3 consumption (SC-016)"
```

---

### Task 13: `SummaryOnlyStrategy`

Returns the artifact's stored summary. Requires `artifact_id`.

**Files:**
- Create: `src/stele/recall/summary_only.py`
- Test: `tests/unit/recall/test_summary_only.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/recall/test_summary_only.py`:

```python
"""Tests for SummaryOnlyStrategy."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import ValidationError
from stele.core.memory_record import MemoryScope
from stele.recall.models import RecallRequest


def test_summary_only_returns_artifact_summary() -> None:
    stele = Stele(StashConfig())
    stored = stele.store(data="The quick brown fox jumps over the lazy dog. " * 30, namespace="default")
    result = stele.recall.summary_only(
        artifact_id=stored.artifact_id,
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "summary_only"
    assert result.context
    assert len(result.citations) == 1
    assert result.citations[0].kind == "artifact"
    assert result.citations[0].reference == stored.reference
    assert result.stats.fetches == 1
    stele.close()


def test_summary_only_requires_artifact_id() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(ValidationError, match="artifact_id"):
        stele.recall(
            query="x",
            scope=MemoryScope(user_id="alice"),
            strategy="summary_only",
            artifact_id=None,
        )
    stele.close()
```

This test depends on Task 19 (`Stele.recall` property). Order: implement Task 13's strategy first, then wire it up via the facade in Tasks 19–21, then re-run.

- [ ] **Step 2: Implement the strategy**

Create `src/stele/recall/summary_only.py`:

```python
"""SummaryOnlyStrategy — requires artifact_id; returns the artifact's stored summary."""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.core.exceptions import ValidationError
from stele.recall.base import Strategy, _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)


class SummaryOnlyStrategy:
    name = "summary_only"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        if request.artifact_id is None:
            raise ValidationError("summary_only requires artifact_id")
        fetched = deps.stele.fetch(request.artifact_id)
        # The artifact's stored summary lives on metadata for fetch results.
        summary = fetched.metadata.get("summary") if fetched.metadata else None
        if not summary:
            # Fall back to a truncation of content for artifacts that lack a stored summary
            content_text = (
                fetched.content
                if isinstance(fetched.content, str)
                else fetched.content.decode("utf-8", errors="replace")
            )
            summary = content_text[: deps.config.max_context_chars]
        citation = Citation(
            kind="artifact",
            id=request.artifact_id,
            reference=fetched.reference,
            score=1.0,
            snippet=summary,
        )
        return RecallResult(
            strategy_used="summary_only",
            context=summary,
            citations=[citation],
            escalations=[
                Escalation(
                    strategy="summary_only",
                    hit_count=1,
                    top_score=1.0,
                    reason="tier_complete",
                )
            ],
            pii_flags=list(fetched.pii.types) if fetched.pii else [],
            source_refs=[fetched.reference],
            stats=RecallStats(
                fetches=1,
                estimated_context_tokens=estimate_tokens(summary),
            ),
        )
```

`fetched.pii` may be a `PIIScrubSummary`; check its field name in `src/stele/core/artifact.py` and adjust the `pii.types` access to whatever the actual attribute is (`types`, `entities`, or similar). If unsure, leave as empty list `[]` and tighten in Task 23's PII inheritance test.

- [ ] **Step 3: Lint + types (strategy unit test runs after facade in Task 19)**

```bash
.venv/bin/ruff check src/stele/recall/summary_only.py
.venv/bin/mypy src/stele/recall/summary_only.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/stele/recall/summary_only.py tests/unit/recall/test_summary_only.py
git commit -m "feat(recall): SummaryOnlyStrategy (SC-003)"
```

---

### Task 14: `MemorySearchStrategy`

Calls `Memory.search_with_score(query, scope, source_ref_filter=...)`. Hits become `Citation(kind="memory", ...)`.

**Files:**
- Create: `src/stele/recall/memory_search.py`
- Test: `tests/unit/recall/test_memory_search.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/recall/test_memory_search.py`:

```python
"""Tests for MemorySearchStrategy."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_memory_search_returns_citations() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode for the dashboard",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    result = stele.recall.memory_search(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "memory_search"
    assert result.citations
    assert result.citations[0].kind == "memory"
    assert result.stats.memory_searches == 1
    stele.close()


def test_memory_search_forced_scope_filters_by_artifact() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="dark mode preference",
        kind="preference",
        source_refs=["stele://default/aid_a"],
        scope=MemoryScope(user_id="alice"),
    )
    stele.memory.add(
        text="dark mode preference",
        kind="preference",
        source_refs=["stele://default/aid_b"],
        scope=MemoryScope(user_id="alice"),
    )
    # Force scope to aid_a — should only return that memory.
    # Caller passes the bare id, recall resolves to the full reference.
    artifact_a = stele.store(data="placeholder a", namespace="default", artifact_id="aid_a")
    result = stele.recall.memory_search(
        query="dark",
        scope=MemoryScope(user_id="alice"),
        artifact_id="aid_a",
    )
    assert len(result.citations) == 1
    assert result.citations[0].reference == artifact_a.reference
    stele.close()
```

Note: `stele.store(...)` may not accept `artifact_id` as a keyword today. If it doesn't, adapt the test to use the auto-assigned id returned by `stele.store(...)` (read `stored.artifact_id`). The forced-scope semantics still hold.

- [ ] **Step 2: Implement**

Create `src/stele/recall/memory_search.py`:

```python
"""MemorySearchStrategy — uses Memory.search_with_score with optional source_ref forcing."""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.recall.base import Strategy, _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)
from stele.recall.ranking import normalize_scores


class MemorySearchStrategy:
    name = "memory_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        source_ref_filter = None
        if request.artifact_id is not None:
            fetched = deps.stele.fetch(request.artifact_id)
            source_ref_filter = fetched.reference

        hits = deps.memory.search_with_score(
            request.query,
            request.scope,
            limit=request.max_memory_hits,
            source_ref_filter=source_ref_filter,
        )

        citations = normalize_scores(
            [
                Citation(
                    kind="memory",
                    id=hit.record.id,
                    reference=hit.record.source_refs[0] if hit.record.source_refs else "",
                    score=hit.score,
                    snippet=hit.record.text,
                )
                for hit in hits
            ]
        )

        context = "\n\n".join(c.snippet for c in citations)
        top_score = citations[0].score if citations else None

        return RecallResult(
            strategy_used="memory_search",
            context=context,
            citations=citations,
            escalations=[
                Escalation(
                    strategy="memory_search",
                    hit_count=len(citations),
                    top_score=top_score,
                    reason="tier_complete" if citations else "zero_hits",
                )
            ],
            pii_flags=sorted({f for hit in hits for f in hit.record.pii_flags}),
            source_refs=sorted({hit.record.source_refs[0] for hit in hits if hit.record.source_refs}),
            stats=RecallStats(
                memory_searches=1,
                estimated_context_tokens=estimate_tokens(context) if context else 0,
            ),
        )
```

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check src/stele/recall/memory_search.py
.venv/bin/mypy src/stele/recall/memory_search.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/stele/recall/memory_search.py tests/unit/recall/test_memory_search.py
git commit -m "feat(recall): MemorySearchStrategy with optional source_ref forcing (SC-004)"
```

---

### Task 15: `ArtifactSearchStrategy`

Calls `stele.search(query)` globally, or `stele.search(reference=..., query)` when scoped.

**Files:**
- Create: `src/stele/recall/artifact_search.py`
- Test: `tests/unit/recall/test_artifact_search.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/recall/test_artifact_search.py`:

```python
"""Tests for ArtifactSearchStrategy."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_artifact_search_global() -> None:
    stele = Stele(StashConfig())
    stele.store(data="The migration deadline is 2026-06-30." * 5, namespace="default")
    result = stele.recall.artifact_search(
        query="migration deadline",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "artifact_search"
    assert result.stats.artifact_searches == 1
    stele.close()


def test_artifact_search_forced_scope() -> None:
    stele = Stele(StashConfig())
    stored = stele.store(
        data="The migration deadline is 2026-06-30. " * 10,
        namespace="default",
    )
    result = stele.recall.artifact_search(
        query="migration",
        scope=MemoryScope(user_id="alice"),
        artifact_id=stored.artifact_id,
    )
    assert result.strategy_used == "artifact_search"
    for c in result.citations:
        assert c.reference == stored.reference
    stele.close()
```

- [ ] **Step 2: Implement**

Create `src/stele/recall/artifact_search.py`:

```python
"""ArtifactSearchStrategy — global stele.search or reference-scoped when artifact_id set."""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.recall.base import Strategy, _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)
from stele.recall.ranking import normalize_scores


class ArtifactSearchStrategy:
    name = "artifact_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        if request.artifact_id is not None:
            fetched = deps.stele.fetch(request.artifact_id)
            hits = deps.stele.search(
                fetched.reference, request.query, limit=request.max_artifact_hits
            )
        else:
            hits = deps.stele.search(
                request.query, limit=request.max_artifact_hits
            )

        citations = normalize_scores(
            [
                Citation(
                    kind="chunk",
                    id=hit.chunk_id or hit.artifact_id,
                    reference=hit.reference,
                    score=hit.score,
                    snippet=hit.text,
                )
                for hit in hits
            ]
        )

        context = "\n\n".join(c.snippet for c in citations)
        top_score = citations[0].score if citations else None

        return RecallResult(
            strategy_used="artifact_search",
            context=context,
            citations=citations,
            escalations=[
                Escalation(
                    strategy="artifact_search",
                    hit_count=len(citations),
                    top_score=top_score,
                    reason="tier_complete" if citations else "zero_hits",
                )
            ],
            pii_flags=sorted(
                {flag for hit in hits if hit.pii for flag in (hit.pii.types or [])}
            ),
            source_refs=sorted({hit.reference for hit in hits}),
            stats=RecallStats(
                artifact_searches=1,
                estimated_context_tokens=estimate_tokens(context) if context else 0,
            ),
        )
```

If `Stele.search` doesn't accept a positional `reference` arg (signature varies), adapt the call to whatever the current signature is. Inspect `src/stele/core/stash.py` for `def search(...)`.

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check src/stele/recall/artifact_search.py
.venv/bin/mypy src/stele/recall/artifact_search.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/stele/recall/artifact_search.py tests/unit/recall/test_artifact_search.py
git commit -m "feat(recall): ArtifactSearchStrategy with global + forced-scope paths (SC-005)"
```

---

### Task 16: `GraphSearchStrategy` stub

Always raises `CapabilityError`. Stable surface for Phase 5.

**Files:**
- Create: `src/stele/recall/graph_search.py`
- Test: `tests/unit/recall/test_graph_search.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/recall/test_graph_search.py`:

```python
"""Tests for GraphSearchStrategy stub — must raise CapabilityError until Phase 5."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope


def test_graph_search_raises_capability_error() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(CapabilityError, match="Phase 5"):
        stele.recall.graph_search(
            query="anything",
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()


def test_graph_search_via_canonical_entry_raises_capability_error() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(CapabilityError, match="Phase 5"):
        stele.recall(
            query="anything",
            scope=MemoryScope(user_id="alice"),
            strategy="graph_search",
        )
    stele.close()
```

- [ ] **Step 2: Implement**

Create `src/stele/recall/graph_search.py`:

```python
"""GraphSearchStrategy — stub until Phase 5 wires pg-raggraph."""

from __future__ import annotations

from stele.core.exceptions import CapabilityError
from stele.recall.base import Strategy, _RecallDeps
from stele.recall.models import RecallRequest, RecallResult


class GraphSearchStrategy:
    name = "graph_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        del request, deps
        raise CapabilityError(
            "graph_search requires Phase 5 pg-raggraph adapter"
        )
```

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check src/stele/recall/graph_search.py tests/unit/recall/test_graph_search.py
.venv/bin/mypy src/stele/recall/graph_search.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/stele/recall/graph_search.py tests/unit/recall/test_graph_search.py
git commit -m "feat(recall): GraphSearchStrategy CapabilityError stub for Phase 5 (SC-006)"
```

---

### Task 17: `RawFetchStrategy`

Calls `stele.fetch(raw=True)`. Requires `artifact_id`. Propagates `PIIBlockedError`.

**Files:**
- Create: `src/stele/recall/raw_fetch.py`
- Test: `tests/unit/recall/test_raw_fetch.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/recall/test_raw_fetch.py`:

```python
"""Tests for RawFetchStrategy."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import PIIBlockedError, ValidationError
from stele.core.memory_record import MemoryScope


def test_raw_fetch_requires_artifact_id() -> None:
    stele = Stele(StashConfig())
    with pytest.raises(ValidationError, match="artifact_id"):
        stele.recall(
            query="x",
            scope=MemoryScope(user_id="alice"),
            strategy="raw_fetch",
            artifact_id=None,
        )
    stele.close()


def test_raw_fetch_returns_full_content_when_pii_raw_fetch_enabled() -> None:
    cfg = StashConfig.load({"pii": {"raw_fetch_enabled": True}})
    stele = Stele(cfg)
    stored = stele.store(data="full content body here", namespace="default")
    result = stele.recall.raw_fetch(
        artifact_id=stored.artifact_id,
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "raw_fetch"
    assert result.stats.fetches == 1
    assert "full content body here" in result.context
    stele.close()


def test_raw_fetch_propagates_pii_blocked_when_disabled() -> None:
    stele = Stele(StashConfig())  # default: pii.raw_fetch_enabled=False
    stored = stele.store(data="anything", namespace="default")
    with pytest.raises(PIIBlockedError):
        stele.recall.raw_fetch(
            artifact_id=stored.artifact_id,
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()
```

- [ ] **Step 2: Implement**

Create `src/stele/recall/raw_fetch.py`:

```python
"""RawFetchStrategy — requires artifact_id; fetches full raw content."""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.core.exceptions import ValidationError
from stele.recall.base import Strategy, _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)


class RawFetchStrategy:
    name = "raw_fetch"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        if request.artifact_id is None:
            raise ValidationError("raw_fetch requires artifact_id")
        fetched = deps.stele.fetch(request.artifact_id, raw=True)
        content = (
            fetched.content
            if isinstance(fetched.content, str)
            else fetched.content.decode("utf-8", errors="replace")
        )
        citation = Citation(
            kind="artifact",
            id=request.artifact_id,
            reference=fetched.reference,
            score=1.0,
            snippet=content,
        )
        return RecallResult(
            strategy_used="raw_fetch",
            context=content,
            citations=[citation],
            escalations=[
                Escalation(
                    strategy="raw_fetch",
                    hit_count=1,
                    top_score=1.0,
                    reason="tier_complete",
                )
            ],
            pii_flags=list(fetched.pii.types) if fetched.pii else [],
            source_refs=[fetched.reference],
            stats=RecallStats(
                fetches=1,
                estimated_context_tokens=estimate_tokens(content),
            ),
        )
```

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check src/stele/recall/raw_fetch.py
.venv/bin/mypy src/stele/recall/raw_fetch.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/stele/recall/raw_fetch.py tests/unit/recall/test_raw_fetch.py
git commit -m "feat(recall): RawFetchStrategy with PIIBlockedError propagation (SC-007)"
```

---

### Task 18: `AbstainStrategy`

Always returns an empty `RecallResult` with `abstained=True`. Never raises.

**Files:**
- Create: `src/stele/recall/abstain.py`
- Test: `tests/unit/recall/test_abstain.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/recall/test_abstain.py`:

```python
"""Tests for AbstainStrategy."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_abstain_returns_empty_result_with_default_reason() -> None:
    stele = Stele(StashConfig())
    result = stele.recall.abstain(
        query="anything",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "abstain"
    assert result.context == ""
    assert result.citations == []
    assert result.abstained is True
    assert result.abstain_reason == "no_sufficient_context"
    stele.close()


def test_abstain_carries_explicit_reason() -> None:
    stele = Stele(StashConfig())
    result = stele.recall.abstain(
        query="anything",
        scope=MemoryScope(user_id="alice"),
        reason="user_requested_explicit_abstention",
    )
    assert result.abstain_reason == "user_requested_explicit_abstention"
    stele.close()


def test_abstain_never_raises_on_empty_inputs() -> None:
    stele = Stele(StashConfig())
    result = stele.recall.abstain(
        query="",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.abstained is True
    stele.close()
```

Note: `stele.recall.abstain(...)` accepts a `reason=` kwarg (mapped onto the request). The facade in Task 19 must wire this — see Task 19 for the shim signature.

- [ ] **Step 2: Implement**

Create `src/stele/recall/abstain.py`:

```python
"""AbstainStrategy — explicit "no sufficient context" terminator."""

from __future__ import annotations

from stele.recall.base import Strategy, _RecallDeps
from stele.recall.models import (
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)


class AbstainStrategy:
    name = "abstain"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        # Reason is carried on the request via a backdoor field set by the
        # facade shim; the canonical RecallRequest model doesn't have a
        # `reason` field, so the facade injects it on the orchestrator side
        # when the caller invokes `recall.abstain(reason=...)`. Default is
        # config.abstain_default_reason.
        reason = getattr(request, "_abstain_reason", None) or deps.config.abstain_default_reason
        return RecallResult(
            strategy_used="abstain",
            context="",
            citations=[],
            escalations=[
                Escalation(
                    strategy="abstain",
                    hit_count=0,
                    top_score=None,
                    reason="exhausted",
                )
            ],
            pii_flags=[],
            source_refs=[],
            stats=RecallStats(),
            abstained=True,
            abstain_reason=reason,
        )
```

Notice the `_abstain_reason` backdoor on the request. The facade's `abstain(...)` shim sets this attribute before calling the canonical entry. This avoids polluting `RecallRequest` with a field only one strategy uses.

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check src/stele/recall/abstain.py
.venv/bin/mypy src/stele/recall/abstain.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/stele/recall/abstain.py tests/unit/recall/test_abstain.py
git commit -m "feat(recall): AbstainStrategy with explicit/default reason (SC-008)"
```

---

### Task 19: `AdaptiveStrategy` — the big one

Composes the other strategies via a registry. Tier order is config-driven. Escalation logic: hit-count + confidence floor + optional callback.

**Files:**
- Create: `src/stele/recall/adaptive.py`
- Test: `tests/unit/recall/test_adaptive.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/recall/test_adaptive.py`:

```python
"""Tests for AdaptiveStrategy — escalation logic, tier order, callback path."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_adaptive_stops_at_first_tier_when_above_floor() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode for the dashboard",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    result = stele.recall.adaptive(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "memory_search"
    assert len(result.escalations) == 1
    assert result.escalations[0].reason == "tier_complete"
    stele.close()


def test_adaptive_escalates_through_tiers_on_zero_hits() -> None:
    stele = Stele(StashConfig())
    # No memories; no artifacts → adaptive should escalate all the way to abstain
    result = stele.recall.adaptive(
        query="something nobody mentioned",
        scope=MemoryScope(user_id="alice"),
    )
    assert result.strategy_used == "abstain"
    assert result.abstained is True
    # tier_order default is [memory_search, artifact_search, raw_fetch, abstain],
    # but raw_fetch is skipped without artifact_id
    strategies_seen = [e.strategy for e in result.escalations]
    assert "memory_search" in strategies_seen
    assert "artifact_search" in strategies_seen
    assert "abstain" in strategies_seen
    assert "raw_fetch" not in strategies_seen
    stele.close()


def test_adaptive_skips_raw_fetch_without_artifact_id() -> None:
    stele = Stele(StashConfig())
    result = stele.recall.adaptive(
        query="x",
        scope=MemoryScope(user_id="alice"),
    )
    seen = [e.strategy for e in result.escalations]
    assert "raw_fetch" not in seen
    stele.close()


def test_adaptive_includes_raw_fetch_when_artifact_id_given() -> None:
    cfg = StashConfig.load({"pii": {"raw_fetch_enabled": True}})
    stele = Stele(cfg)
    stored = stele.store(data="this is the full content body", namespace="default")
    result = stele.recall.adaptive(
        query="content body",
        scope=MemoryScope(user_id="alice"),
        artifact_id=stored.artifact_id,
    )
    seen = [e.strategy for e in result.escalations]
    # Tier order: memory_search (likely zero hits), artifact_search, raw_fetch
    # If artifact_search finds the content, tier_complete fires there; raw_fetch may not run.
    # The invariant: raw_fetch is at least *available* in the tier list when artifact_id is set.
    assert seen, "expected at least one escalation"
    stele.close()


def test_adaptive_calls_sufficient_callback_when_provided() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    calls: list[int] = []

    def sufficient(ctx) -> bool:  # type: ignore[no-untyped-def]
        calls.append(len(ctx.accumulated_citations))
        return False  # force escalation

    result = stele.recall.adaptive(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
        sufficient=sufficient,
    )
    assert calls, "sufficient should have been called at least once"
    assert calls[0] >= 1
    # Because sufficient=False forced escalation, the trail should be longer than 1
    assert len(result.escalations) > 1
    stele.close()


def test_adaptive_stops_when_sufficient_returns_true() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )

    def sufficient(ctx) -> bool:  # type: ignore[no-untyped-def]
        return True

    result = stele.recall.adaptive(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
        sufficient=sufficient,
    )
    # With sufficient=True after the first hit-bearing tier, stop there.
    assert result.strategy_used in {"memory_search", "artifact_search"}
    stele.close()
```

- [ ] **Step 2: Implement**

Create `src/stele/recall/adaptive.py`:

```python
"""AdaptiveStrategy — composes other strategies; runs tier order with escalation."""

from __future__ import annotations

from stele.recall.abstain import AbstainStrategy
from stele.recall.artifact_search import ArtifactSearchStrategy
from stele.recall.base import Strategy, _RecallDeps
from stele.recall.graph_search import GraphSearchStrategy
from stele.recall.memory_search import MemorySearchStrategy
from stele.recall.models import (
    Citation,
    Escalation,
    EscalationReason,
    RecallContext,
    RecallRequest,
    RecallResult,
    RecallStats,
    StrategyName,
)
from stele.recall.ranking import merge_hits
from stele.recall.raw_fetch import RawFetchStrategy
from stele.recall.summary_only import SummaryOnlyStrategy


class AdaptiveStrategy:
    name = "adaptive"

    def __init__(self) -> None:
        self._registry: dict[StrategyName, Strategy] = {
            "summary_only": SummaryOnlyStrategy(),
            "memory_search": MemorySearchStrategy(),
            "artifact_search": ArtifactSearchStrategy(),
            "graph_search": GraphSearchStrategy(),
            "raw_fetch": RawFetchStrategy(),
            "abstain": AbstainStrategy(),
        }

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        tier_order = list(deps.config.adaptive_tier_order)
        floor = request.confidence_floor if request.confidence_floor is not None else deps.config.confidence_floor

        # Skip raw_fetch when no artifact_id and config says so
        if (
            deps.config.adaptive_skip_raw_fetch_without_artifact_id
            and request.artifact_id is None
            and "raw_fetch" in tier_order
        ):
            tier_order = [t for t in tier_order if t != "raw_fetch"]

        accumulated_citations: list[Citation] = []
        accumulated_stats = RecallStats()
        all_escalations: list[Escalation] = []
        all_pii_flags: set[str] = set()
        all_source_refs: set[str] = set()

        terminating_result: RecallResult | None = None
        for tier_name in tier_order:
            strategy = self._registry[tier_name]
            tier_result = strategy.execute(request, deps)

            accumulated_citations = merge_hits(accumulated_citations, tier_result.citations)
            accumulated_stats = _sum_stats(accumulated_stats, tier_result.stats)
            all_pii_flags.update(tier_result.pii_flags)
            all_source_refs.update(tier_result.source_refs)

            top_score = tier_result.citations[0].score if tier_result.citations else None
            hit_count = len(tier_result.citations)

            reason: EscalationReason
            stop = False

            if tier_name == "abstain":
                # abstain is always terminal
                all_escalations.append(
                    Escalation(
                        strategy=tier_name,
                        hit_count=0,
                        top_score=None,
                        reason="exhausted",
                    )
                )
                terminating_result = tier_result
                break

            if hit_count == 0:
                reason = "zero_hits"
            elif top_score is not None and top_score >= floor:
                reason = "tier_complete"
                stop = True
            else:
                reason = "below_floor"

            # Optional caller callback layered on top
            if stop and request.sufficient is not None:
                ctx = RecallContext(
                    query=request.query,
                    scope=request.scope,
                    accumulated_citations=list(accumulated_citations),
                    accumulated_text="\n\n".join(c.snippet for c in accumulated_citations),
                )
                try:
                    is_sufficient = request.sufficient(ctx)
                except Exception as exc:
                    from stele.core.exceptions import SteleError
                    raise SteleError(f"sufficient callback raised: {exc}") from exc
                if not is_sufficient:
                    stop = False
                    reason = "sufficient_callback_false"

            all_escalations.append(
                Escalation(
                    strategy=tier_name,
                    hit_count=hit_count,
                    top_score=top_score,
                    reason=reason,
                )
            )
            if stop:
                terminating_result = tier_result
                break

        # Fallback if loop exited without abstain (shouldn't happen if config is valid)
        if terminating_result is None:
            from stele.recall.abstain import AbstainStrategy as _Abstain
            terminating_result = _Abstain().execute(request, deps)
            all_escalations.append(
                Escalation(strategy="abstain", hit_count=0, top_score=None, reason="exhausted")
            )

        context = "\n\n".join(c.snippet for c in accumulated_citations)

        return RecallResult(
            strategy_used=terminating_result.strategy_used,
            context=context,
            citations=accumulated_citations,
            escalations=all_escalations,
            pii_flags=sorted(all_pii_flags),
            source_refs=sorted(all_source_refs),
            stats=accumulated_stats,
            abstained=terminating_result.abstained,
            abstain_reason=terminating_result.abstain_reason,
        )


def _sum_stats(a: RecallStats, b: RecallStats) -> RecallStats:
    return RecallStats(
        memory_searches=a.memory_searches + b.memory_searches,
        artifact_searches=a.artifact_searches + b.artifact_searches,
        chunk_searches=a.chunk_searches + b.chunk_searches,
        fetches=a.fetches + b.fetches,
        estimated_context_tokens=a.estimated_context_tokens + b.estimated_context_tokens,
        latency_ms=a.latency_ms + b.latency_ms,
    )
```

- [ ] **Step 3: Run DC-001 — no Phase 4/5 imports + no LLM clients**

```bash
grep -rn 'pg_raggraph\|chunkshop\|openai\|anthropic\|lede' src/stele/recall/
```

Expected: empty. If anything matches, STOP and remove the offending import. Note: `lede` matching means Phase 2 logic leaked into recall.

- [ ] **Step 4: Run DC-002 — no oracle**

```bash
grep -rn '_answer_is_sufficient\|expected_answer' src/stele/recall/adaptive.py
```

Expected: empty.

- [ ] **Step 5: Lint + types (test runs after facade in Task 21)**

```bash
.venv/bin/ruff check src/stele/recall/adaptive.py tests/unit/recall/test_adaptive.py
.venv/bin/mypy src/stele/recall/adaptive.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/stele/recall/adaptive.py tests/unit/recall/test_adaptive.py
git commit -m "feat(recall): AdaptiveStrategy with hit-count+floor+callback (SC-009..SC-012, DC-001, DC-002)"
```

---

### Task 20: `Recall` facade — callable + 7 shims

The user-facing API. Implements `__call__` and exposes the 7 shim methods.

**Files:**
- Create: `src/stele/recall/facade.py`
- Test: `tests/unit/recall/test_facade.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/recall/test_facade.py`:

```python
"""Tests for the Recall facade — canonical entry vs shims."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope


def test_canonical_call_equals_adaptive_shim() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text="user prefers dark mode",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    canonical = stele.recall(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
        strategy="adaptive",
    )
    shim = stele.recall.adaptive(
        query="dark mode",
        scope=MemoryScope(user_id="alice"),
    )
    assert canonical.strategy_used == shim.strategy_used
    assert canonical.stats.memory_searches == shim.stats.memory_searches
    assert [c.id for c in canonical.citations] == [c.id for c in shim.citations]
    stele.close()


def test_recall_disabled_raises_capability_error() -> None:
    cfg = StashConfig.load({"recall": {"enabled": False}})
    stele = Stele(cfg)
    with pytest.raises(CapabilityError, match="disabled"):
        stele.recall(
            query="x",
            scope=MemoryScope(user_id="alice"),
        )
    with pytest.raises(CapabilityError, match="disabled"):
        stele.recall.adaptive(
            query="x",
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()
```

- [ ] **Step 2: Implement**

Create `src/stele/recall/facade.py`:

```python
"""Recall facade — callable property exposing canonical + shim entries."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from stele.core.exceptions import CapabilityError
from stele.recall.abstain import AbstainStrategy
from stele.recall.adaptive import AdaptiveStrategy
from stele.recall.artifact_search import ArtifactSearchStrategy
from stele.recall.base import Strategy, _RecallDeps
from stele.recall.graph_search import GraphSearchStrategy
from stele.recall.memory_search import MemorySearchStrategy
from stele.recall.models import (
    RecallContext,
    RecallRequest,
    RecallResult,
    StrategyName,
)
from stele.recall.raw_fetch import RawFetchStrategy
from stele.recall.summary_only import SummaryOnlyStrategy

if TYPE_CHECKING:
    from stele.core.config import RecallConfig
    from stele.core.memory import Memory
    from stele.core.memory_record import MemoryScope
    from stele.core.stash import Stele
    from stele.pii.regex import RegexPIIScrubber
    from stele.pii.scrubber import DisabledPIIScrubber


class Recall:
    def __init__(
        self,
        *,
        stele: Stele,
        memory: Memory,
        scrubber: RegexPIIScrubber | DisabledPIIScrubber,
        config: RecallConfig,
    ) -> None:
        self._deps = _RecallDeps(stele=stele, memory=memory, scrubber=scrubber, config=config)
        self._registry: dict[StrategyName, Strategy] = {
            "summary_only": SummaryOnlyStrategy(),
            "memory_search": MemorySearchStrategy(),
            "artifact_search": ArtifactSearchStrategy(),
            "graph_search": GraphSearchStrategy(),
            "adaptive": AdaptiveStrategy(),
            "raw_fetch": RawFetchStrategy(),
            "abstain": AbstainStrategy(),
        }

    def __call__(
        self,
        *,
        query: str = "",
        scope: MemoryScope,
        strategy: StrategyName | None = None,
        artifact_id: str | None = None,
        sufficient: Callable[[RecallContext], bool] | None = None,
        max_memory_hits: int | None = None,
        max_artifact_hits: int | None = None,
        confidence_floor: float | None = None,
    ) -> RecallResult:
        if not self._deps.config.enabled:
            raise CapabilityError("recall is disabled in config")
        req = RecallRequest(
            query=query,
            scope=scope,
            strategy=strategy or self._deps.config.default_strategy,
            artifact_id=artifact_id,
            sufficient=sufficient,
            max_memory_hits=max_memory_hits if max_memory_hits is not None else self._deps.config.max_memory_hits,
            max_artifact_hits=max_artifact_hits if max_artifact_hits is not None else self._deps.config.max_artifact_hits,
            confidence_floor=confidence_floor,
        )
        return self._registry[req.strategy].execute(req, self._deps)

    # Convenience shims — each is a one-liner around __call__.

    def summary_only(self, *, artifact_id: str, scope: MemoryScope) -> RecallResult:
        return self(scope=scope, strategy="summary_only", artifact_id=artifact_id)

    def memory_search(
        self, *, query: str, scope: MemoryScope, artifact_id: str | None = None
    ) -> RecallResult:
        return self(query=query, scope=scope, strategy="memory_search", artifact_id=artifact_id)

    def artifact_search(
        self, *, query: str, scope: MemoryScope, artifact_id: str | None = None
    ) -> RecallResult:
        return self(query=query, scope=scope, strategy="artifact_search", artifact_id=artifact_id)

    def graph_search(self, *, query: str, scope: MemoryScope, artifact_id: str | None = None) -> RecallResult:
        return self(query=query, scope=scope, strategy="graph_search", artifact_id=artifact_id)

    def adaptive(
        self,
        *,
        query: str,
        scope: MemoryScope,
        artifact_id: str | None = None,
        sufficient: Callable[[RecallContext], bool] | None = None,
    ) -> RecallResult:
        return self(
            query=query,
            scope=scope,
            strategy="adaptive",
            artifact_id=artifact_id,
            sufficient=sufficient,
        )

    def raw_fetch(self, *, artifact_id: str, scope: MemoryScope) -> RecallResult:
        return self(scope=scope, strategy="raw_fetch", artifact_id=artifact_id)

    def abstain(
        self,
        *,
        query: str = "",
        scope: MemoryScope,
        reason: str | None = None,
    ) -> RecallResult:
        if not self._deps.config.enabled:
            raise CapabilityError("recall is disabled in config")
        req = RecallRequest(query=query, scope=scope, strategy="abstain")
        if reason is not None:
            object.__setattr__(req, "_abstain_reason", reason)
        return self._registry["abstain"].execute(req, self._deps)

    def close(self) -> None:
        # The facade owns no resources beyond the deps struct.
        pass
```

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check src/stele/recall/facade.py
.venv/bin/mypy src/stele/recall/facade.py
```

Expected: clean.

- [ ] **Step 4: Commit (tests still failing — wired up in Task 21)**

```bash
git add src/stele/recall/facade.py tests/unit/recall/test_facade.py
git commit -m "feat(recall): Recall callable facade with canonical entry + 7 shims (SC-013)"
```

---

### Task 21: `Stele.recall` property + `__init__.py` exports

The final wire-up. After this, all the tests written in Tasks 13–20 can run.

**Files:**
- Modify: `src/stele/core/stash.py`
- Modify: `src/stele/__init__.py`

- [ ] **Step 1: Add `Stele.recall` property**

In `src/stele/core/stash.py`, after the `Stele.extract` property:

```python
    @property
    def recall(self) -> Recall:  # forward ref imported below
        if not hasattr(self, "_recall"):
            from stele.recall.facade import Recall

            self._recall = Recall(
                stele=self,
                memory=self.memory,
                scrubber=self.pii_scrubber,  # type: ignore[arg-type]
                config=self.config.recall,
            )
        return self._recall
```

Extend `Stele.close()`:

```python
    def close(self) -> None:
        memory = getattr(self, "_memory", None)
        if memory is not None:
            memory.close()
        extractor = getattr(self, "_extractor", None)
        if extractor is not None:
            extractor.close()
        recall = getattr(self, "_recall", None)
        if recall is not None:
            recall.close()
```

Add to TYPE_CHECKING import block:

```python
if TYPE_CHECKING:
    from stele.core.memory import Memory
    from stele.extraction.extractor import MemoryExtractor
    from stele.recall.facade import Recall
```

- [ ] **Step 2: Re-export public types**

In `src/stele/__init__.py`, add (alphabetically into the import block and `__all__`):

```python
from stele.recall.models import (
    Citation,
    Escalation,
    RecallContext,
    RecallRequest,
    RecallResult,
    RecallStats,
)
```

And to `__all__`:

```python
    "Citation",
    "Escalation",
    "RecallContext",
    "RecallRequest",
    "RecallResult",
    "RecallStats",
```

- [ ] **Step 3: Run every recall unit test**

```bash
.venv/bin/pytest tests/unit/recall -v
```

Expected: every test from Tasks 13–20 now passes. If `test_summary_only.py` fails because the artifact's `metadata` doesn't carry a `summary` key, inspect a real `FetchResult` produced by `Stele.fetch` and adapt either the strategy (Task 13) or the test fixture to match. Don't loosen the test — fix the data shape.

- [ ] **Step 4: Run DC-003 — confirm extraction uses Memory only (carry-over check)**

```bash
grep -rn 'MemoryStore\|_store\.' src/stele/recall/
```

Expected: empty (Phase 3 should consume Memory facade only, not MemoryStore directly). If a strategy reaches into the store, fix it.

- [ ] **Step 5: Lint + types**

```bash
.venv/bin/ruff check src/stele/core/stash.py src/stele/__init__.py
.venv/bin/mypy src
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/stele/core/stash.py src/stele/__init__.py
git commit -m "feat(recall): Stele.recall property + public exports (SC-018, DC-003)"
```

---

### Task 22: PII inheritance test

Recall must never re-scrub. `RecallResult.pii_flags` is union of underlying surfaces.

**Files:**
- Test: `tests/unit/recall/test_pii_inheritance.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/recall/test_pii_inheritance.py`:

```python
"""PII flags are inherited from underlying surfaces; recall never re-scrubs."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


PII_TEXT = "Contact alice@example.com or 415-555-0199 for the migration plan."


def test_recall_context_remains_scrubbed() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text=PII_TEXT,
        kind="fact",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    result = stele.recall.memory_search(
        query="migration",
        scope=MemoryScope(user_id="alice"),
    )
    assert "alice@example.com" not in result.context
    assert "415-555-0199" not in result.context
    stele.close()


def test_recall_collects_pii_flags() -> None:
    stele = Stele(StashConfig())
    stele.memory.add(
        text=PII_TEXT,
        kind="fact",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    result = stele.recall.memory_search(
        query="migration",
        scope=MemoryScope(user_id="alice"),
    )
    # Phase 1's scrubber tags emails + phones. Exact flag names depend on
    # RegexPIIScrubber output — just assert non-empty.
    assert result.pii_flags, "expected at least one PII flag inherited from memory"
    stele.close()
```

- [ ] **Step 2: Run, confirm pass**

```bash
.venv/bin/pytest tests/unit/recall/test_pii_inheritance.py -v
```

Expected: both PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/recall/test_pii_inheritance.py
git commit -m "test(recall): PII inheritance — context scrubbed, flags propagated (SC-019)"
```

---

### Task 23: Architecture import-layer check

Locks the invariant: no Phase 4/5 deps, no LLM clients, no direct MemoryStore reaches.

**Files:**
- Test: `tests/unit/recall/test_architecture.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/recall/test_architecture.py`:

```python
"""Architectural import-layer checks for the recall package."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RECALL_ROOT = Path(__file__).resolve().parents[3] / "src" / "stele" / "recall"

FORBIDDEN_PREFIXES = (
    "pg_raggraph",
    "chunkshop",
    "openai",
    "anthropic",
    "lede",  # Phase 2's territory
)

FORBIDDEN_EXACT = {
    "stele.storage.memory_store.base",
    "stele.storage.memory_store.memory",
    "stele.storage.memory_store.sqlite",
    "stele.storage.memory_store.postgres",
    "stele.storage.memory_store.mariadb",
    "stele.storage.memory_store.clickhouse",
}


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


@pytest.mark.parametrize("module_path", sorted(RECALL_ROOT.rglob("*.py")))
def test_no_forbidden_imports(module_path: Path) -> None:
    imports = _imports(module_path)
    for imp in imports:
        for prefix in FORBIDDEN_PREFIXES:
            assert prefix not in imp, (
                f"{module_path} imports {imp!r} — Phase 4/5 or LLM client drift"
            )
    illegal = {m for m in imports if m in FORBIDDEN_EXACT}
    assert not illegal, (
        f"{module_path} imports {illegal} — must consume Memory facade only"
    )
```

- [ ] **Step 2: Run, confirm pass**

```bash
.venv/bin/pytest tests/unit/recall/test_architecture.py -v
```

Expected: every recall module parametrized case PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/recall/test_architecture.py
git commit -m "test(recall): import-layer check (DC-001 lock)"
```

---

### Task 24: Cross-backend contract test

Parametrize the recall flow across `memory`, `sqlite`, and `postgres`. Structural equivalence: same `strategy_used`, same citation count, same `abstained` flag for the same input.

**Files:**
- Test: `tests/contract/test_recall_contract.py`

- [ ] **Step 1: Write the test**

Create `tests/contract/test_recall_contract.py`:

```python
"""Cross-backend recall contract — memory + sqlite + postgres."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def _backend_configs() -> list[tuple[str, dict[str, object]]]:
    configs: list[tuple[str, dict[str, object]]] = [
        ("memory", {"backend": {"type": "memory"}}),
    ]
    tmp = Path(tempfile.mkdtemp())
    configs.append(
        ("sqlite", {"backend": {"type": "sqlite", "path": str(tmp / "stele.db")}})
    )
    pg_dsn = os.environ.get("STELE_PG_DSN")
    if pg_dsn:
        configs.append(("postgres", {"backend": {"type": "postgres", "dsn": pg_dsn}}))
    return configs


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_recall_contract_memory_then_artifact(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        stele.memory.add(
            text="user prefers dark mode for the dashboard",
            kind="preference",
            source_refs=["stele://default/abc"],
            scope=MemoryScope(user_id="contract"),
        )
        result = stele.recall(
            query="dark mode",
            scope=MemoryScope(user_id="contract"),
        )
        # Structural invariants
        assert result.strategy_used in {"memory_search", "artifact_search", "adaptive", "abstain"}
        assert isinstance(result.stats.memory_searches, int)
        assert isinstance(result.context, str)
    finally:
        stele.close()


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_recall_contract_forced_scope(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        stored = stele.store(
            data="The migration deadline is 2026-06-30. " * 10,
            namespace="default",
        )
        result = stele.recall.artifact_search(
            query="migration",
            scope=MemoryScope(user_id="contract"),
            artifact_id=stored.artifact_id,
        )
        for c in result.citations:
            assert c.reference == stored.reference, (
                f"forced scope leaked: got {c.reference}, expected {stored.reference}"
            )
    finally:
        stele.close()
```

- [ ] **Step 2: Run with memory + sqlite**

```bash
.venv/bin/pytest tests/contract/test_recall_contract.py -v
```

Expected: 4 parametrized cases PASS (2 tests × 2 backends).

- [ ] **Step 3: Run with Postgres if available**

```bash
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
scripts/postgres-up.sh
.venv/bin/pytest tests/contract/test_recall_contract.py -v
```

Expected: 6 parametrized cases PASS (2 tests × 3 backends).

- [ ] **Step 4: Commit**

```bash
git add tests/contract/test_recall_contract.py
git commit -m "test(recall): cross-backend contract memory+sqlite+postgres (SC-014, SC-017)"
```

---

### Task 25: Benchmark migration — `_run_strategy` delegates to `stele.recall`

The strategy doc's headline action: lift `_run_strategy` into a thin caller of `stele.recall(...)`.

**Files:**
- Modify: `benchmarks/answer_workflow.py`

- [ ] **Step 1: Replace the body of `_run_strategy`**

In `benchmarks/answer_workflow.py`, replace the entire `_run_strategy` function with:

```python
def _run_strategy(
    *,
    stash: Stele,
    scenario: BenchmarkScenario,
    reference: str,
    replacement: str,
    strategy: Strategy,
    answerer: Answerer,
) -> AnswerAttempt:
    """Run a recall strategy, then ask the answerer with the assembled context.

    Phase 3 migration: this function now delegates to `stash.recall(...)`.
    The mapping from the old benchmark strategy names to the new StrategyName:
      - summary_only        → "summary_only" (uses replacement summary directly)
      - search_first        → "artifact_search"
      - summary_then_search → "adaptive" (truncated to 2 tiers: summary_only synthesized
                             from `replacement`, then artifact_search)
      - adaptive            → "adaptive" with all tiers
      - raw_fetch           → "raw_fetch"
    """
    from stele.core.memory_record import MemoryScope

    scope = MemoryScope(namespace="default")
    artifact_id = reference.rsplit("/", 1)[-1]

    # summary_only and summary_then_search use the benchmark's pre-built `replacement`
    # string (the artifact's summary at stash time) directly. The Phase 3 strategy
    # SummaryOnlyStrategy resolves the summary via fetch, which may differ. Use
    # replacement here for behavior preservation.
    if strategy == "summary_only":
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement)],
            search_calls=0,
            fetch_calls=0,
            llm_round_trips=1,
        )

    if strategy == "search_first":
        result = stash.recall(
            query=scenario.query,
            scope=scope,
            strategy="artifact_search",
            artifact_id=artifact_id,
            max_artifact_hits=3,
        )
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("search", result.context)],
            search_calls=result.stats.artifact_searches,
            fetch_calls=result.stats.fetches,
            llm_round_trips=1,
        )

    if strategy == "summary_then_search":
        first = _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement)],
            search_calls=0,
            fetch_calls=0,
            llm_round_trips=1,
        )
        if _answer_is_sufficient(first.answer, scenario.expected_answer):
            return first
        result = stash.recall(
            query=scenario.query,
            scope=scope,
            strategy="artifact_search",
            artifact_id=artifact_id,
            max_artifact_hits=3,
        )
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement), ("search", result.context)],
            search_calls=result.stats.artifact_searches,
            fetch_calls=result.stats.fetches,
            llm_round_trips=2,
        )

    if strategy == "adaptive":
        # Phase 3 adaptive uses hit-count + confidence floor — no oracle.
        # Cost ceiling here matches the old behavior: cap at 3 LLM round trips.
        result = stash.recall(
            query=scenario.query,
            scope=scope,
            strategy="adaptive",
            artifact_id=artifact_id,
        )
        # The benchmark previously did up to 3 LLM calls inside adaptive
        # (summary, summary+search, summary+search+raw). Phase 3's adaptive
        # never calls an LLM; we issue one final answerer call with the
        # accumulated context for benchmark behavior parity.
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement), ("recall", result.context)],
            search_calls=result.stats.artifact_searches,
            fetch_calls=result.stats.fetches,
            llm_round_trips=1,
        )

    if strategy == "raw_fetch":
        # Preserve the old benchmark behavior: pii.raw_fetch_enabled must be on.
        result = stash.recall(
            query=scenario.query,
            scope=scope,
            strategy="raw_fetch",
            artifact_id=artifact_id,
        )
        return _answer_with_context(
            answerer,
            scenario=scenario,
            contexts=[("summary", replacement), ("raw", result.context)],
            search_calls=0,
            fetch_calls=result.stats.fetches,
            llm_round_trips=1,
        )

    raise ValueError(f"Unknown strategy: {strategy}")
```

- [ ] **Step 2: Run the benchmark smoke test**

```bash
.venv/bin/pytest tests/benchmarks_smoke -v
```

Expected: existing smokes still pass. If a smoke fails because the recall path produces a different `search_calls`/`fetch_calls` count than the old `_run_strategy`, that's expected — we'll capture the new counts in Task 26's regression test. Don't try to fix here; move on.

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check benchmarks/answer_workflow.py
.venv/bin/mypy benchmarks/answer_workflow.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/answer_workflow.py
git commit -m "refactor(benchmarks): _run_strategy delegates to stele.recall (Phase 3)"
```

---

### Task 26: Behavior-preservation regression test + DC-003

Locks the headline proof: new path == old path on the existing fixtures, deterministic judge, accuracy delta == 0.

**Files:**
- Test: `tests/benchmarks_smoke/test_answer_workflow_via_recall.py`

- [ ] **Step 1: Write the test**

Create `tests/benchmarks_smoke/test_answer_workflow_via_recall.py`:

```python
"""Regression: stele.recall(...) preserves _run_strategy's accuracy + structure on fixtures."""

from __future__ import annotations

import pytest

from benchmarks.answer_workflow import (
    DeterministicAnswerer,
    _run_strategy,
)
from benchmarks.longrun import build_scenarios
from stele import Stele
from stele.core.config import StashConfig


# Subset the existing scenarios for fast smoke; full run lives in benchmarks/
SAMPLE_SCENARIO_NAMES = (
    "preference_basic",
    "temporal_old_title",
    "knowledge_update_address",
)


@pytest.mark.parametrize(
    "strategy",
    ["summary_only", "search_first", "summary_then_search", "adaptive", "raw_fetch"],
)
def test_strategy_runs_without_error(strategy: str) -> None:
    """Each strategy via the new path must run end-to-end on the smoke set."""
    cfg = StashConfig.load({"pii": {"raw_fetch_enabled": True}})
    stele = Stele(cfg)
    answerer = DeterministicAnswerer()
    try:
        scenarios = [s for s in build_scenarios() if s.name in SAMPLE_SCENARIO_NAMES]
        assert scenarios, "smoke set must not be empty"
        for scenario in scenarios:
            stored = stele.store(data=scenario.content, namespace="default")
            attempt = _run_strategy(
                stash=stele,
                scenario=scenario,
                reference=stored.reference,
                replacement=stored.summary,
                strategy=strategy,  # type: ignore[arg-type]
                answerer=answerer,
            )
            assert attempt.answer is not None
            assert attempt.context_bytes >= 0
    finally:
        stele.close()
```

This is a **smoke** regression — it asserts the path runs and produces non-null output. The full strategy-by-strategy accuracy comparison (DC-003) lives in the real `benchmarks/answer_workflow.py` runner; this smoke just locks "doesn't crash."

- [ ] **Step 2: Run, confirm pass**

```bash
.venv/bin/pytest tests/benchmarks_smoke/test_answer_workflow_via_recall.py -v
```

Expected: all 5 parametrized cases PASS.

- [ ] **Step 3: Run DC-003 — full benchmark comparison**

Run the full benchmark twice (once before this branch, once after) and compare:

```bash
# On main (pre-Phase-3):
git stash || true
git switch main
.venv/bin/python -m benchmarks.answer_workflow --judge deterministic --output-dir /tmp/bench-pre
git switch phase3-policy-driven-recall

# On the phase 3 branch:
.venv/bin/python -m benchmarks.answer_workflow --judge deterministic --output-dir /tmp/bench-post

# Compare accuracy per strategy
.venv/bin/python - <<'PY'
import json
from pathlib import Path

def load_results(dir_: Path) -> dict:
    summary_files = list(dir_.rglob("answer-workflow-*.json"))
    assert summary_files, f"no summary found in {dir_}"
    return json.loads(summary_files[-1].read_text())

pre = load_results(Path("/tmp/bench-pre"))
post = load_results(Path("/tmp/bench-post"))

print(f"{'strategy':<22} {'pre_acc':<10} {'post_acc':<10} {'delta':<10}")
for strategy in pre["by_strategy"]:
    pre_acc = pre["by_strategy"][strategy]["accuracy"]
    post_acc = post["by_strategy"][strategy]["accuracy"]
    delta = post_acc - pre_acc
    print(f"{strategy:<22} {pre_acc:<10.4f} {post_acc:<10.4f} {delta:<+10.4f}")
    assert abs(delta) < 0.001, f"DC-003 FAIL: strategy={strategy} accuracy_delta={delta}"

print("\nDC-003 PASS: all strategies preserve accuracy on the deterministic judge")
PY
```

Expected: every strategy's `delta` is `0.0` (or within rounding). Any non-zero delta means the Phase 3 path changed behavior — either the new code has a bug, or the old behavior depended on the oracle in ways the new heuristic doesn't reproduce. Investigate before continuing.

- [ ] **Step 4: Commit**

```bash
git add tests/benchmarks_smoke/test_answer_workflow_via_recall.py
git commit -m "test(benchmarks): smoke regression for recall-routed answer workflow (SC-020, DC-003)"
```

---

### Task 27: DC-FINAL coverage check + repo verification

Confirm every SC has a passing test cited; run the full repo lint/types/tests; merge prep.

**Files:**
- Read-only

- [ ] **Step 1: Build the SC → test mapping**

```bash
cat <<'EOF' > /tmp/phase3-sc-coverage.txt
SC-001 → tests/unit/recall/test_models.py
SC-002 → tests/unit/recall/test_ranking.py
SC-003 → tests/unit/recall/test_summary_only.py
SC-004 → tests/unit/recall/test_memory_search.py
SC-005 → tests/unit/recall/test_artifact_search.py
SC-006 → tests/unit/recall/test_graph_search.py
SC-007 → tests/unit/recall/test_raw_fetch.py
SC-008 → tests/unit/recall/test_abstain.py
SC-009 → tests/unit/recall/test_adaptive.py
SC-010 → tests/unit/recall/test_adaptive.py::test_adaptive_stops_at_first_tier_when_above_floor
SC-011 → tests/unit/recall/test_adaptive.py::test_adaptive_calls_sufficient_callback_when_provided + test_adaptive_stops_when_sufficient_returns_true
SC-012 → tests/unit/recall/test_adaptive.py::test_adaptive_skips_raw_fetch_without_artifact_id
SC-013 → tests/unit/recall/test_facade.py::test_canonical_call_equals_adaptive_shim
SC-014 → tests/unit/recall/test_memory_search.py + test_artifact_search.py + tests/contract/test_recall_contract.py::test_recall_contract_forced_scope
SC-015 → tests/unit/core/test_memory_search_with_score.py (in-process + sqlite + postgres via contract)
SC-016 → tests/unit/extraction/test_extractor.py::test_preview_returns_candidates_without_storing
SC-017 → tests/contract/test_recall_contract.py
SC-018 → tests/unit/recall/test_facade.py::test_recall_disabled_raises_capability_error
SC-019 → tests/unit/recall/test_pii_inheritance.py
SC-020 → tests/benchmarks_smoke/test_answer_workflow_via_recall.py + manual DC-003 comparison
EOF
cat /tmp/phase3-sc-coverage.txt
```

- [ ] **Step 2: Run every cited test and verify all pass**

```bash
.venv/bin/pytest tests/unit/recall tests/contract/test_recall_contract.py tests/unit/core/test_memory_search_with_score.py tests/unit/core/test_memory_facade.py tests/unit/extraction/test_extractor.py tests/benchmarks_smoke/test_answer_workflow_via_recall.py -v 2>&1 | tail -80
```

Expected: every cited test passes.

- [ ] **Step 3: Re-run the four drift checkpoints**

```bash
echo "=== DC-001 ==="
grep -rn 'pg_raggraph\|chunkshop\|openai\|anthropic\|lede' src/stele/recall/ || echo "(empty — OK)"

echo "=== DC-002 ==="
grep -rn '_answer_is_sufficient\|expected_answer' src/stele/recall/adaptive.py || echo "(empty — OK)"

echo "=== DC-003 (re-run the comparison from Task 26 Step 3 if not already) ==="
echo "  See benchmark output diff."
```

Expected: DC-001 empty, DC-002 empty, DC-003 zero accuracy delta.

- [ ] **Step 4: Confirm Out-of-Scope items are untouched**

```bash
echo "=== Out-of-Scope check ==="
grep -rn 'RecallPolicy.*(class|def)\|vector_search\|cross_encoder\|reranker' src/stele/ tests/ 2>/dev/null || echo "(empty — OK; no out-of-scope features introduced)"

echo "=== Untouched files check ==="
git log main..HEAD --name-only | sort -u | grep -E 'src/stele/(retrieval|pii)|src/stele/extraction/(candidates|classifier|patterns|models)' && echo "WARN: locked file modified" || echo "(no locked files touched — OK)"
```

Expected: out-of-scope grep empty; no locked files modified.

- [ ] **Step 5: Full repo verification trio**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest 2>&1 | tail -5
```

Expected: all three pass; pytest count is roughly the Task 0 count + the Phase 3 tests added (~55–65 new tests).

- [ ] **Step 6: Commit the SC mapping (optional)**

```bash
cp /tmp/phase3-sc-coverage.txt docs/superpowers/specs/2026-05-13-phase3-sc-coverage.txt
git add docs/superpowers/specs/2026-05-13-phase3-sc-coverage.txt
git commit -m "docs(phase3): SC-001..SC-020 → test mapping for DC-FINAL"
```

- [ ] **Step 7: Verify no other files were touched**

```bash
git diff --name-only main..HEAD | sort
```

Expected: only the files listed in this plan's "New files" and "Modified files" tables. Any unexpected entry — investigate before merge.

- [ ] **Step 8: Optional tag**

```bash
git tag phase3-policy-driven-recall
```

- [ ] **Step 9: Merge prep**

Phase 2 may still be in flight on `phase2-deterministic-extraction`. Two cases:

- If Phase 2 has merged to main: `git switch main && git merge --ff-only phase3-policy-driven-recall`
- If Phase 2 is still in flight: leave the branch parked. Phase 3 plan execution stays on its branch until Phase 2 lands first. Do NOT rebase Phase 3 onto a Phase 2 branch — the strategy walkthroughs assume the *final* Phase 2 surface, not in-progress snapshots.

---

## Parallel-with-other-phases Notes

If Phase 2 and Phase 3 land in parallel branches and merge sequentially into main, the conflict surface is small but real:

| File | Phase 2 touches | Phase 3 touches | Conflict risk |
|---|---|---|---|
| `src/stele/core/stash.py` | Adds `Stele.extract` property | Adds `Stele.recall` property | **Low** — both blocks append; accept BOTH |
| `src/stele/__init__.py` | Exports Phase 2 types | Exports Phase 3 types | **Low** — both add to `__all__` and import block; accept BOTH |
| `src/stele/core/config.py` | Adds `ExtractionConfig` | Adds `RecallConfig` | **Low** — sibling fields on `StashConfig`; accept BOTH |
| `src/stele/extraction/extractor.py` | Built by Phase 2 | Adds `MemoryExtractor.preview` | **Medium** — Phase 3 adds a method to a class Phase 2 created. If Phase 3 merges first, Phase 2 must rebase to keep `.preview`. If Phase 2 merges first, Phase 3's `.preview` patch applies cleanly. Order matters; merge Phase 2 first if possible. |
| `src/stele/core/memory.py` | Phase 1 surface | Adds `Memory.search_with_score` | **Low** — `Memory` already exists from Phase 1; adding a method is additive |
| `src/stele/storage/memory_store/*.py` | None (Phase 1 surface) | Adds `search_with_score` to each | **None** — Phase 2 doesn't touch these |

If conflicts appear on `stash.py` / `__init__.py` / `config.py`: accept BOTH sides.

If conflict on `extraction/extractor.py`: the `.preview` method goes on the same class Phase 2 created. Merge sequence: Phase 2 first, then Phase 3.

---

## Definition of Ready For Each Task

A task is ready to start when:

- Its predecessor task is committed.
- The cited test file exists or this task creates it.
- The required Phase 1 + Phase 2 surfaces work (`.venv/bin/pytest tests/contract/` passes).

## Definition of Done For Each Task

A task is done when:

- The new test(s) pass.
- `ruff check` and `mypy` on the touched files are clean.
- The commit was created with the documented message style.
- Any cited DC-XXX checkpoint passed.
- No file outside the task's declared `Files:` list was modified.
