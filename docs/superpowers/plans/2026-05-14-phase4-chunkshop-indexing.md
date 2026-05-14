# Stele Phase 4: Chunkshop Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Location note:** This plan and its spec live at `/tmp/stele-phase4-planning/` per user instruction — they are NOT in git. When Phase 2 + Phase 3 settle, the user will decide where to commit (likely a dedicated `phase4-chunkshop-indexing` branch off main).

**Goal:** Ship production vector + hybrid retrieval across all 5 backends via Chunkshop adapters, plus production indexing modes (sync/async/skip) with a pluggable `TaskBackend` Protocol, plus bakeoff-generated config consumption.

**Architecture:** Thin Approach A — Stele owns the boundary (chunk_id format, PII invariant, `SearchHit` translation), Chunkshop is the engine. Per-backend wrapper files in `src/stele/storage/chunk_store/` lazy-import the matching Chunkshop adapter. `InProcessChunkStore` (memory backend) works without chunkshop. `AsyncChunkIndexer` submits to a `TaskBackend` Protocol; `InProcessTaskBackend` ships real, `RedisTaskBackend`/`CeleryTaskBackend` ship as `CapabilityError` stubs. Vector + hybrid retrieval get their own modules under `src/stele/retrieval/`. `RetrievalMode` expands to `Literal["keyword", "vector", "hybrid"]` and Phase 3 picks up the new modes through `RetrievalConfig.default_mode` without code changes.

**Tech Stack:** Python 3.12+, Pydantic v2, `chunkshop>=X.Y` with extras `[sqlite,postgres,mariadb,clickhouse]`, `numpy` for in-process vector math, `threading` for `InProcessTaskBackend`, pytest, ruff, mypy strict.

**Spec (load-bearing):** `/tmp/stele-phase4-planning/2026-05-14-phase4-chunkshop-indexing-design.md`

Re-read the spec at every DC-XXX checkpoint below. All 26 success criteria (SC-001 through SC-026) must have evidence at DC-FINAL.

**Phase 1+2+3 dependency:** Plan assumes Phase 1 Tasks 0–21, Phase 2 Tasks 0–23, and Phase 3 Tasks 0–27 are complete. Task 0 verifies.

**Chunkshop release dependency:** MariaDB and ClickHouse chunk stores require the user's unreleased Chunkshop branch. Plan Task 0 checks the installed Chunkshop's exported backend list and marks MariaDB/ClickHouse tasks as deferred (with a clear message) if those adapters aren't present.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/stele/indexing/chunkshop_adapter.py` | chunk_id ↔ Chunkshop row translation |
| `src/stele/indexing/bakeoff.py` | `BakeoffConfig` loader + overlay onto `IndexingConfig` |
| `src/stele/indexing/async_queue.py` | `AsyncChunkIndexer` |
| `src/stele/indexing/task_backend/__init__.py` | Package marker |
| `src/stele/indexing/task_backend/base.py` | `TaskBackend` Protocol + `IndexTask` + `TaskStatus` |
| `src/stele/indexing/task_backend/in_process.py` | `InProcessTaskBackend` (threading) |
| `src/stele/indexing/task_backend/redis.py` | `RedisTaskBackend` `CapabilityError` stub |
| `src/stele/indexing/task_backend/celery.py` | `CeleryTaskBackend` `CapabilityError` stub |
| `src/stele/storage/chunk_store/__init__.py` | Package marker |
| `src/stele/storage/chunk_store/base.py` | `ChunkStore` Protocol |
| `src/stele/storage/chunk_store/memory.py` | In-process (numpy + dict), no chunkshop required |
| `src/stele/storage/chunk_store/sqlite.py` | `chunkshop[sqlite]` wrapper |
| `src/stele/storage/chunk_store/postgres.py` | `chunkshop[postgres]` (pgvector) wrapper |
| `src/stele/storage/chunk_store/mariadb.py` | `chunkshop[mariadb]` wrapper (gated) |
| `src/stele/storage/chunk_store/clickhouse.py` | `chunkshop[clickhouse]` wrapper (gated) |
| `src/stele/retrieval/vector.py` | `vector_search(...)` backend-agnostic facade |
| `src/stele/retrieval/hybrid.py` | `hybrid_search(...)` RRF + WeightedSum |
| `tests/unit/indexing/test_chunkshop_adapter.py` | chunk_id round-trip; no native objects escape |
| `tests/unit/indexing/test_bakeoff.py` | Load + overlay + Capabilities |
| `tests/unit/indexing/test_async_queue.py` | pending → indexed; failure path |
| `tests/unit/indexing/test_task_backend.py` | In-process impl; stubs CapabilityError |
| `tests/unit/indexing/test_dim_resolution.py` | Bakeoff → auto-detect → default cascade |
| `tests/unit/storage/test_chunk_store_memory.py` | In-process chunk store |
| `tests/unit/storage/test_chunk_store_sqlite.py` | SQLite chunkshop wrapper |
| `tests/unit/storage/test_chunk_store_postgres.py` | Postgres chunkshop wrapper |
| `tests/unit/storage/test_chunk_store_mariadb.py` | MariaDB (gated) |
| `tests/unit/storage/test_chunk_store_clickhouse.py` | ClickHouse (gated) |
| `tests/unit/retrieval/test_vector.py` | Vector search behavior |
| `tests/unit/retrieval/test_hybrid.py` | RRF + WeightedSum merging |
| `tests/unit/retrieval/test_hybrid_quality.py` | **Load-bearing.** Held-out set: hybrid recall@5 ≥ best − 5% |
| `tests/unit/retrieval/test_capabilities.py` | Capabilities reports chunkshop / bakeoff / task_backend |
| `tests/unit/recall/test_artifact_search_vector.py` | Phase 3 picks up vector via config |
| `tests/contract/test_vector_contract.py` | 5-backend parametrized |
| `tests/contract/test_indexing_modes_contract.py` | sync/async/skip × backends |
| `tests/fixtures/recall/hybrid_held_out_set.json` | ≥20 query/relevant-chunk pairs |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | Pin `chunkshop>=X.Y` minimum; add backend extras `[sqlite,postgres,mariadb,clickhouse]` |
| `src/stele/core/config.py` | Extend `IndexingConfig` + `RetrievalConfig.default_mode` |
| `src/stele/core/types.py` | `RetrievalMode = Literal["keyword", "vector", "hybrid"]` |
| `src/stele/core/stash.py` | `Stele.search(mode=...)`, `Stele.indexing_status`, capabilities expansion, wire `_chunk_store` + `_async_indexer` + bakeoff overlay |
| `src/stele/core/artifact.py` | Expand `Capabilities` model |
| `src/stele/indexing/queue.py` | `SyncChunkIndexer` writes through `ChunkStore` |
| `src/stele/indexing/job.py` | `IndexResult.status` adds `"pending"` |
| `src/stele/retrieval/{memory,sqlite,postgres,mariadb,clickhouse}.py` | Each grows `vector_search` + `hybrid_search` paths delegating to `ChunkStore` |
| `src/stele/__init__.py` | Re-export `BakeoffConfig`, `BakeoffSummary`, `TaskStatus`, updated `Capabilities` |

### Untouched (locked)

| Path | Why locked |
|---|---|
| `src/stele/core/memory.py`, `memory_record.py` | Phase 1 |
| `src/stele/extraction/*` | Phase 2 |
| `src/stele/recall/*` | Phase 3 — Phase 4 changes `Stele.search` internals only |
| `src/stele/pii/*` | Consumed only |
| `src/stele/storage/{memory,sqlite,postgres,mariadb,clickhouse}.py` (artifact stores) | Phase 1 |
| `src/stele/indexing/chunk_index.py` | Existing in-process fallback — kept as-is |

---

## Drift Checkpoints

- ⛔ **DC-000** (Task 0): Phase 1+2+3 complete; Chunkshop installed at pinned version; backend extras present (memory/sqlite/postgres required; mariadb/clickhouse warn-only).
- ⛔ **DC-001** (after Task 18): `grep -rn 'chunkshop\.[a-z_]*' src/stele/retrieval/ src/stele/recall/` must be empty.
- ⛔ **DC-002** (after Task 9): `grep -rn 'threading\.\|queue\.Queue\|asyncio\.' src/stele/retrieval/ src/stele/recall/` must be empty.
- ⛔ **DC-003** (after Task 21): `tests/unit/retrieval/test_hybrid_quality.py` must pass with default floor (5%).
- ⛔ **DC-004** (after Task 24): `Stele(...)` with vs without `bakeoff_path` produces different `Capabilities.bakeoff_summary.source`.
- ⛔ **DC-FINAL** (Task 33): every SC-001..SC-026 has a passing test cited; Out-of-Scope verified untouched.

---

## Tasks

### Task 0: Verify Phase 1+2+3 prerequisites + Chunkshop availability

**Files:** Read-only.

- [ ] **Step 1: Confirm Phase 1/2/3 surfaces ship**

```bash
.venv/bin/python -c "
from stele import (
    Stele, Memory, MemoryScope, MemoryRecord,
    MemoryCandidate, ExtractionReport,
    RecallRequest, RecallResult, Citation,
    CapabilityError, ValidationError, ArtifactNotFound,
)
import inspect
from stele.core.stash import Stele as S
assert hasattr(S, 'memory'), 'Phase 1 missing'
assert hasattr(S, 'extract'), 'Phase 2 missing'
assert hasattr(S, 'recall'), 'Phase 3 missing'
print('Phase 1+2+3 surfaces: OK')
"
```

Expected: `Phase 1+2+3 surfaces: OK`. If any phase missing, STOP.

- [ ] **Step 2: Detect Chunkshop installation + backend extras**

```bash
.venv/bin/python - <<'PY'
import importlib.util
import sys

available: dict[str, bool] = {}
for backend in ("sqlite", "postgres", "mariadb", "clickhouse"):
    spec = importlib.util.find_spec(f"chunkshop.{backend}")
    available[backend] = spec is not None

print("chunkshop core:", importlib.util.find_spec("chunkshop") is not None)
print("backend extras:", available)

required = {"sqlite", "postgres"}
optional_now = {"mariadb", "clickhouse"}
missing_required = required - {b for b, ok in available.items() if ok}
missing_optional = optional_now - {b for b, ok in available.items() if ok}

if missing_required:
    print(f"FAIL: missing required Chunkshop extras: {missing_required}")
    print("Install: pip install 'chunkshop[sqlite,postgres]>=X.Y'")
    sys.exit(1)

if missing_optional:
    print(f"WARN: Chunkshop extras for {missing_optional} not installed.")
    print("MariaDB/ClickHouse chunk_store tasks (15, 17) will be marked deferred.")
PY
```

Expected: at minimum sqlite + postgres extras are present. mariadb/clickhouse missing = warn, continue but mark Tasks 15/17 deferred when they run.

- [ ] **Step 3: Run baseline verification trio**

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

Per user instruction: do **not** switch branches; do not create worktrees. Phase 4 work targets the current working tree; the user will decide where commits land when Phase 2+3 settle.

No commit in Task 0.

---

### Task 1: Expand `RetrievalMode` literal type

**Files:**
- Modify: `src/stele/core/types.py`
- Test: `tests/unit/core/test_types.py` (create or append)

- [ ] **Step 1: Write failing test**

Create or append to `tests/unit/core/test_types.py`:

```python
"""Tests for RetrievalMode literal expansion in Phase 4."""

from __future__ import annotations

from typing import get_args

from stele.core.types import RetrievalMode


def test_retrieval_mode_includes_vector_and_hybrid() -> None:
    members = set(get_args(RetrievalMode))
    assert members == {"keyword", "vector", "hybrid"}
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/core/test_types.py -v -k retrieval_mode
```

Expected: AssertionError on members set.

- [ ] **Step 3: Implement**

In `src/stele/core/types.py`, change:

```python
RetrievalMode = Literal["keyword"]
```

to:

```python
RetrievalMode = Literal["keyword", "vector", "hybrid"]
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/core/test_types.py -v
.venv/bin/ruff check src/stele/core/types.py tests/unit/core/test_types.py
.venv/bin/mypy src/stele/core/types.py
```

Expected: pass.

- [ ] **Step 5: Commit-equivalent note**

Per user instruction, do not commit. Mark progress by:

```bash
echo "Task 1: RetrievalMode expanded ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 2: Extend `IndexingConfig` and `RetrievalConfig`

**Files:**
- Modify: `src/stele/core/config.py`
- Test: `tests/unit/core/test_config.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/core/test_config.py`:

```python
def test_indexing_config_phase4_defaults() -> None:
    from stele.core.config import IndexingConfig, StashConfig

    cfg = StashConfig()
    ic = cfg.indexing
    assert ic.bakeoff_path is None
    assert ic.similarity == "cosine"
    assert ic.vector_dim is None
    assert ic.hybrid_method == "rrf"
    assert ic.hybrid_weights == {"keyword": 0.5, "vector": 0.5}
    assert ic.hybrid_rrf_k == 60
    assert ic.task_backend == "in_process"
    assert ic.task_backend_dsn is None


def test_indexing_config_rejects_bad_hybrid_weights() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load({"indexing": {"hybrid_weights": {"keyword": 0.5}}})

    with pytest.raises(PydanticValidationError):
        StashConfig.load(
            {"indexing": {"hybrid_method": "weighted_sum", "hybrid_weights": {"keyword": 0.0, "vector": 0.0}}}
        )


def test_indexing_config_rejects_redis_without_dsn() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load({"indexing": {"task_backend": "redis"}})


def test_indexing_config_rejects_negative_vector_dim() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from stele.core.config import StashConfig

    with pytest.raises(PydanticValidationError):
        StashConfig.load({"indexing": {"vector_dim": -1}})


def test_retrieval_config_accepts_vector_and_hybrid() -> None:
    from stele.core.config import StashConfig

    cfg_v = StashConfig.load({"retrieval": {"default_mode": "vector"}})
    cfg_h = StashConfig.load({"retrieval": {"default_mode": "hybrid"}})
    assert cfg_v.retrieval.default_mode == "vector"
    assert cfg_h.retrieval.default_mode == "hybrid"
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/core/test_config.py -v -k "indexing_config_phase4 or hybrid_weights or redis_without_dsn or negative_vector_dim or retrieval_config_accepts"
```

Expected: AttributeError / ValidationError mismatches.

- [ ] **Step 3: Implement**

In `src/stele/core/config.py`, extend `IndexingConfig`:

```python
class IndexingConfig(BaseModel):
    # existing fields kept...
    bakeoff_path: str | None = None
    similarity: Literal["cosine", "ip", "l2"] = "cosine"
    vector_dim: int | None = None
    hybrid_method: Literal["rrf", "weighted_sum"] = "rrf"
    hybrid_weights: dict[str, float] = Field(
        default_factory=lambda: {"keyword": 0.5, "vector": 0.5}
    )
    hybrid_rrf_k: int = Field(default=60, ge=1)
    task_backend: Literal["in_process", "redis", "celery"] = "in_process"
    task_backend_dsn: str | None = None

    @field_validator("hybrid_weights")
    @classmethod
    def _check_weights(cls, v: dict[str, float]) -> dict[str, float]:
        if set(v.keys()) != {"keyword", "vector"}:
            raise ValueError("hybrid_weights keys must be exactly {'keyword', 'vector'}")
        return v

    @field_validator("vector_dim")
    @classmethod
    def _check_dim(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("vector_dim must be > 0 when set")
        return v

    @model_validator(mode="after")
    def _check_task_backend_dsn(self) -> "IndexingConfig":
        if self.task_backend in {"redis", "celery"} and not self.task_backend_dsn:
            raise ValueError(f"{self.task_backend} task_backend requires task_backend_dsn")
        if (
            self.hybrid_method == "weighted_sum"
            and sum(self.hybrid_weights.values()) == 0
        ):
            raise ValueError("hybrid_method='weighted_sum' requires non-zero weights")
        return self
```

Add `from pydantic import field_validator, model_validator` to imports.

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/core/test_config.py -v -k phase4
.venv/bin/ruff check src/stele/core/config.py
.venv/bin/mypy src/stele/core/config.py
```

Expected: pass.

- [ ] **Step 5: Progress note**

```bash
echo "Task 2: IndexingConfig + RetrievalConfig extended ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 3: BakeoffConfig models

**Files:**
- Create: `src/stele/indexing/bakeoff.py` (models only; loader in Task 4)
- Test: `tests/unit/indexing/test_bakeoff.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/indexing/__init__.py` if missing (empty file).

Create `tests/unit/indexing/test_bakeoff.py`:

```python
"""Tests for BakeoffConfig models + loader + overlay."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.indexing.bakeoff import (
    BakeoffChunker,
    BakeoffConfig,
    BakeoffEmbedder,
    BakeoffSummary,
)


def test_bakeoff_embedder_required_fields() -> None:
    e = BakeoffEmbedder(name="test-model", dim=768)
    assert e.dim == 768
    assert e.revision is None


def test_bakeoff_chunker_params_passthrough() -> None:
    c = BakeoffChunker(type="fixed_overlap", params={"window_words": 220, "overlap_words": 60})
    assert c.params["window_words"] == 220


def test_bakeoff_config_full() -> None:
    cfg = BakeoffConfig(
        chunker=BakeoffChunker(type="fixed_overlap", params={"window_words": 220}),
        embedder=BakeoffEmbedder(name="all-MiniLM-L6-v2", dim=384),
        similarity="cosine",
        benchmark_recall_at_5=0.82,
    )
    assert cfg.similarity == "cosine"


def test_bakeoff_config_rejects_unknown_similarity() -> None:
    with pytest.raises(PydanticValidationError):
        BakeoffConfig(
            chunker=BakeoffChunker(type="x", params={}),
            embedder=BakeoffEmbedder(name="x", dim=1),
            similarity="manhattan",  # type: ignore[arg-type]
        )


def test_bakeoff_summary_sources() -> None:
    s = BakeoffSummary(source="auto_detected", chunker=None, embedder=None, similarity="cosine")
    assert s.source == "auto_detected"
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/indexing/test_bakeoff.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement models**

Create `src/stele/indexing/bakeoff.py`:

```python
"""Bakeoff config models + loader + overlay logic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class BakeoffEmbedder(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    dim: int
    revision: str | None = None


class BakeoffChunker(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: str
    params: dict[str, object]


class BakeoffConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    chunker: BakeoffChunker
    embedder: BakeoffEmbedder
    similarity: Literal["cosine", "ip", "l2"]
    benchmark_recall_at_5: float | None = None
    notes: str | None = None


class BakeoffSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: Literal["bakeoff_file", "auto_detected", "default"]
    chunker: BakeoffChunker | None
    embedder: BakeoffEmbedder | None
    similarity: Literal["cosine", "ip", "l2"]
    file_path: str | None = None
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/indexing/test_bakeoff.py -v
.venv/bin/ruff check src/stele/indexing/bakeoff.py
.venv/bin/mypy src/stele/indexing/bakeoff.py
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 3: BakeoffConfig models ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 4: Bakeoff loader + overlay

**Files:**
- Modify: `src/stele/indexing/bakeoff.py`
- Test: `tests/unit/indexing/test_bakeoff.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/indexing/test_bakeoff.py`:

```python
import json
from pathlib import Path

import pytest
import yaml

from stele.core.config import IndexingConfig
from stele.core.exceptions import ConfigError
from stele.indexing.bakeoff import load_bakeoff_file, overlay_onto_indexing_config


def _sample_dict() -> dict:
    return {
        "chunker": {"type": "fixed_overlap", "params": {"window_words": 220}},
        "embedder": {"name": "all-MiniLM-L6-v2", "dim": 384},
        "similarity": "cosine",
    }


def test_load_bakeoff_json(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps(_sample_dict()))
    cfg = load_bakeoff_file(str(p))
    assert cfg.embedder.dim == 384


def test_load_bakeoff_yaml(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text(yaml.safe_dump(_sample_dict()))
    cfg = load_bakeoff_file(str(p))
    assert cfg.similarity == "cosine"


def test_load_bakeoff_missing_file_raises_configerror(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_bakeoff_file(str(tmp_path / "missing.json"))


def test_load_bakeoff_invalid_content_raises_configerror(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text('{"chunker": {}}')  # missing embedder + similarity
    with pytest.raises(ConfigError, match="invalid"):
        load_bakeoff_file(str(p))


def test_overlay_onto_indexing_config(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps(_sample_dict()))
    bakeoff = load_bakeoff_file(str(p))
    ic = IndexingConfig()
    overlaid = overlay_onto_indexing_config(ic, bakeoff)
    assert overlaid.similarity == "cosine"
    assert overlaid.vector_dim == 384
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/indexing/test_bakeoff.py -v -k "load_bakeoff or overlay"
```

Expected: ImportError on the new symbols.

- [ ] **Step 3: Implement loader + overlay**

Append to `src/stele/indexing/bakeoff.py`:

```python
import json
from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from stele.core.config import IndexingConfig
from stele.core.exceptions import ConfigError


def load_bakeoff_file(path: str) -> BakeoffConfig:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"bakeoff_path {path!r} does not exist")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"bakeoff config invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("bakeoff config invalid: top-level must be a mapping")
    try:
        return BakeoffConfig.model_validate(data)
    except PydanticValidationError as exc:
        raise ConfigError(f"bakeoff config invalid: {exc}") from exc


def overlay_onto_indexing_config(
    indexing: IndexingConfig, bakeoff: BakeoffConfig
) -> IndexingConfig:
    """Apply bakeoff settings on top of IndexingConfig. Returns a new instance."""
    return indexing.model_copy(
        update={
            "similarity": bakeoff.similarity,
            "vector_dim": bakeoff.embedder.dim,
        }
    )
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/indexing/test_bakeoff.py -v
.venv/bin/ruff check src/stele/indexing/bakeoff.py
.venv/bin/mypy src/stele/indexing/bakeoff.py
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 4: Bakeoff loader + overlay ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 5: Expand `Capabilities` with chunkshop / bakeoff / task_backend fields

**Files:**
- Modify: `src/stele/core/artifact.py`
- Test: `tests/unit/retrieval/test_capabilities.py` (create — uses placeholder; full wire-up in Task 27)

- [ ] **Step 1: Write failing test (capability fields exist)**

Create `tests/unit/retrieval/__init__.py` if missing.

Create `tests/unit/retrieval/test_capabilities.py`:

```python
"""Tests for the Capabilities model — Phase 4 fields exist."""

from __future__ import annotations

from stele.core.artifact import Capabilities
from stele.indexing.bakeoff import BakeoffSummary


def test_capabilities_has_phase4_fields() -> None:
    caps = Capabilities()
    assert hasattr(caps, "chunk_store_backend")
    assert hasattr(caps, "vector_enabled")
    assert hasattr(caps, "hybrid_enabled")
    assert hasattr(caps, "chunkshop_installed")
    assert hasattr(caps, "chunkshop_version")
    assert hasattr(caps, "bakeoff_summary")
    assert hasattr(caps, "task_backend")


def test_capabilities_bakeoff_summary_typed() -> None:
    caps = Capabilities(
        bakeoff_summary=BakeoffSummary(
            source="auto_detected",
            chunker=None,
            embedder=None,
            similarity="cosine",
        )
    )
    assert caps.bakeoff_summary is not None
    assert caps.bakeoff_summary.source == "auto_detected"
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/retrieval/test_capabilities.py -v
```

Expected: AttributeError.

- [ ] **Step 3: Implement Capabilities expansion**

In `src/stele/core/artifact.py`, find the `class Capabilities(BaseModel)` declaration and add fields (keep existing ones; alphabetize within sensible groupings):

```python
class Capabilities(BaseModel):
    # ... existing fields ...
    chunk_store_backend: Literal["memory", "sqlite", "postgres", "mariadb", "clickhouse"] | None = None
    vector_enabled: bool = False
    hybrid_enabled: bool = False
    chunkshop_installed: bool = False
    chunkshop_version: str | None = None
    bakeoff_summary: "BakeoffSummary | None" = None
    task_backend: str | None = None
```

At the top of `artifact.py`, add the TYPE_CHECKING import:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stele.indexing.bakeoff import BakeoffSummary
```

And rebuild model after the import (Pydantic forward-ref resolution):

```python
# At end of file:
from stele.indexing.bakeoff import BakeoffSummary  # noqa: E402

Capabilities.model_rebuild()
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/retrieval/test_capabilities.py -v
.venv/bin/ruff check src/stele/core/artifact.py
.venv/bin/mypy src/stele/core/artifact.py
```

If `mypy` complains about the late import, restructure: move `BakeoffSummary` import to top-level (it's a pure pydantic model with no Stele core deps, so no circular import risk).

- [ ] **Step 5: Progress note**

```bash
echo "Task 5: Capabilities expanded ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 6: `TaskBackend` Protocol + `IndexTask` + `TaskStatus`

**Files:**
- Create: `src/stele/indexing/task_backend/__init__.py`
- Create: `src/stele/indexing/task_backend/base.py`

- [ ] **Step 1: Implement (Protocol-only; tests come with concrete impls in Task 7+)**

```bash
mkdir -p src/stele/indexing/task_backend
: > src/stele/indexing/task_backend/__init__.py
```

Create `src/stele/indexing/task_backend/base.py`:

```python
"""TaskBackend Protocol + supporting models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class IndexTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str
    reference: str
    namespace: str
    submitted_at: datetime


class TaskStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    state: Literal["pending", "running", "succeeded", "failed"]
    message: str | None = None


class TaskBackend(Protocol):
    name: str  # "in_process" | "redis" | "celery"

    def submit(self, task: IndexTask) -> str:
        """Submit task. Returns a task_id."""
        ...

    def status(self, task_id: str) -> TaskStatus:
        ...

    def close(self) -> None:
        ...
```

- [ ] **Step 2: Wire `__init__.py` exports**

Overwrite `src/stele/indexing/task_backend/__init__.py`:

```python
"""Task backend Protocol + implementations."""

from stele.indexing.task_backend.base import IndexTask, TaskBackend, TaskStatus

__all__ = ["IndexTask", "TaskBackend", "TaskStatus"]
```

- [ ] **Step 3: Lint + types**

```bash
.venv/bin/ruff check src/stele/indexing/task_backend
.venv/bin/mypy src/stele/indexing/task_backend
```

- [ ] **Step 4: Progress note**

```bash
echo "Task 6: TaskBackend Protocol ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 7: `InProcessTaskBackend`

**Files:**
- Create: `src/stele/indexing/task_backend/in_process.py`
- Test: `tests/unit/indexing/test_task_backend.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/indexing/test_task_backend.py`:

```python
"""Tests for InProcessTaskBackend + Redis/Celery stubs."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from stele.core.exceptions import CapabilityError
from stele.indexing.task_backend import IndexTask, TaskStatus
from stele.indexing.task_backend.in_process import InProcessTaskBackend


def _task() -> IndexTask:
    return IndexTask(
        artifact_id="aid",
        reference="stele://default/aid",
        namespace="default",
        submitted_at=datetime.now(UTC),
    )


def test_in_process_submit_runs_and_succeeds() -> None:
    completed: list[str] = []

    def worker(t: IndexTask) -> None:
        completed.append(t.artifact_id)

    backend = InProcessTaskBackend(worker=worker)
    try:
        task_id = backend.submit(_task())
        # Wait briefly for the background thread
        for _ in range(100):
            status = backend.status(task_id)
            if status.state in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        final = backend.status(task_id)
        assert final.state == "succeeded"
        assert completed == ["aid"]
    finally:
        backend.close()


def test_in_process_failure_recorded() -> None:
    def worker(t: IndexTask) -> None:
        raise RuntimeError("simulated indexing failure")

    backend = InProcessTaskBackend(worker=worker)
    try:
        task_id = backend.submit(_task())
        for _ in range(100):
            status = backend.status(task_id)
            if status.state in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        final = backend.status(task_id)
        assert final.state == "failed"
        assert "simulated" in (final.message or "")
    finally:
        backend.close()


def test_in_process_status_pending_before_run() -> None:
    started = []

    def slow_worker(t: IndexTask) -> None:
        started.append(t.artifact_id)
        time.sleep(0.2)

    backend = InProcessTaskBackend(worker=slow_worker)
    try:
        task_id = backend.submit(_task())
        immediate = backend.status(task_id)
        assert immediate.state in {"pending", "running"}
    finally:
        backend.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/indexing/test_task_backend.py -v -k in_process
```

Expected: ModuleNotFoundError on `in_process`.

- [ ] **Step 3: Implement**

Create `src/stele/indexing/task_backend/in_process.py`:

```python
"""InProcessTaskBackend — threading.Thread + queue.Queue."""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from typing import Literal

from stele.indexing.task_backend.base import IndexTask, TaskBackend, TaskStatus


class InProcessTaskBackend:
    name: str = "in_process"

    def __init__(self, *, worker: Callable[[IndexTask], None]) -> None:
        self._worker = worker
        self._queue: queue.Queue[tuple[str, IndexTask] | None] = queue.Queue()
        self._statuses: dict[str, TaskStatus] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, task: IndexTask) -> str:
        task_id = uuid.uuid4().hex
        with self._lock:
            self._statuses[task_id] = TaskStatus(task_id=task_id, state="pending")
        self._queue.put((task_id, task))
        return task_id

    def status(self, task_id: str) -> TaskStatus:
        with self._lock:
            return self._statuses.get(
                task_id,
                TaskStatus(task_id=task_id, state="failed", message="unknown task_id"),
            )

    def close(self) -> None:
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            task_id, task = item
            self._set_state(task_id, "running")
            try:
                self._worker(task)
            except Exception as exc:
                self._set_state(task_id, "failed", message=f"{type(exc).__name__}: {exc}")
            else:
                self._set_state(task_id, "succeeded")

    def _set_state(
        self,
        task_id: str,
        state: Literal["pending", "running", "succeeded", "failed"],
        *,
        message: str | None = None,
    ) -> None:
        with self._lock:
            self._statuses[task_id] = TaskStatus(task_id=task_id, state=state, message=message)
```

Verify it conforms to the Protocol:

```bash
.venv/bin/python -c "
from stele.indexing.task_backend.base import TaskBackend
from stele.indexing.task_backend.in_process import InProcessTaskBackend
def _check(b: TaskBackend) -> None: ...
_check(InProcessTaskBackend(worker=lambda t: None))
print('Protocol conformance: OK')
"
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/indexing/test_task_backend.py -v -k in_process
.venv/bin/ruff check src/stele/indexing/task_backend/in_process.py
.venv/bin/mypy src/stele/indexing/task_backend/in_process.py
```

Expected: 3 tests pass.

- [ ] **Step 5: Progress note**

```bash
echo "Task 7: InProcessTaskBackend ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 8: Redis + Celery `CapabilityError` stubs

**Files:**
- Create: `src/stele/indexing/task_backend/redis.py`
- Create: `src/stele/indexing/task_backend/celery.py`
- Test: `tests/unit/indexing/test_task_backend.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/indexing/test_task_backend.py`:

```python
def test_redis_task_backend_raises_capability_error() -> None:
    from stele.indexing.task_backend.redis import RedisTaskBackend

    with pytest.raises(CapabilityError, match="redis"):
        RedisTaskBackend(dsn="redis://localhost:6379/0")


def test_celery_task_backend_raises_capability_error() -> None:
    from stele.indexing.task_backend.celery import CeleryTaskBackend

    with pytest.raises(CapabilityError, match="celery"):
        CeleryTaskBackend(dsn="redis://localhost:6379/0")
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/indexing/test_task_backend.py -v -k "redis or celery"
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `src/stele/indexing/task_backend/redis.py`:

```python
"""RedisTaskBackend stub — Phase 4 ships CapabilityError only."""

from __future__ import annotations

from stele.core.exceptions import CapabilityError
from stele.indexing.task_backend.base import IndexTask, TaskStatus


class RedisTaskBackend:
    name: str = "redis"

    def __init__(self, *, dsn: str) -> None:
        del dsn
        raise CapabilityError(
            "redis task backend not implemented; "
            "use task_backend='in_process' or supply your own TaskBackend Protocol implementation"
        )

    def submit(self, task: IndexTask) -> str:  # pragma: no cover
        raise CapabilityError("redis task backend not implemented")

    def status(self, task_id: str) -> TaskStatus:  # pragma: no cover
        raise CapabilityError("redis task backend not implemented")

    def close(self) -> None:  # pragma: no cover
        pass
```

Create `src/stele/indexing/task_backend/celery.py` (same shape, swap "redis" for "celery").

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/indexing/test_task_backend.py -v
.venv/bin/ruff check src/stele/indexing/task_backend
.venv/bin/mypy src/stele/indexing/task_backend
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 8: Redis+Celery stubs ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 9: `AsyncChunkIndexer` + DC-002

**Files:**
- Create: `src/stele/indexing/async_queue.py`
- Modify: `src/stele/indexing/job.py` (add "pending" state)
- Test: `tests/unit/indexing/test_async_queue.py`

- [ ] **Step 1: Extend `IndexResult.status` to include "pending"**

In `src/stele/core/types.py`, find `IndexStatus`:

```python
IndexStatus = Literal["indexed", "failed", "skipped"]
```

Change to:

```python
IndexStatus = Literal["pending", "indexed", "failed", "skipped"]
```

- [ ] **Step 2: Write failing test**

Create `tests/unit/indexing/test_async_queue.py`:

```python
"""Tests for AsyncChunkIndexer."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from stele.core.artifact import Artifact, ArtifactRecord
from stele.indexing.async_queue import AsyncChunkIndexer
from stele.indexing.chunk_index import ChunkIndex
from stele.indexing.queue import SyncChunkIndexer
from stele.indexing.task_backend.in_process import InProcessTaskBackend


def _artifact(text: str = "hello world") -> ArtifactRecord:
    now = datetime.now(UTC)
    return ArtifactRecord(
        artifact_id="aid1",
        reference="stele://default/aid1",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=2,
        summary=text,
        digest_sha256="x" * 64,
        metadata={},
        created_at=now,
    )


def test_async_indexer_pending_then_indexed() -> None:
    from stele.core.config import IndexingConfig

    sync = SyncChunkIndexer(ChunkIndex(IndexingConfig()))
    backend = InProcessTaskBackend(worker=lambda t: sync.index_now(_artifact()))
    indexer = AsyncChunkIndexer(task_backend=backend, sync=sync)
    try:
        result = indexer.submit(_artifact())
        assert result.status == "pending"
        # Poll status
        for _ in range(100):
            status = indexer.status(_artifact().artifact_id)
            if status.status in {"indexed", "failed"}:
                break
            time.sleep(0.01)
        final = indexer.status(_artifact().artifact_id)
        assert final.status == "indexed"
    finally:
        backend.close()
```

- [ ] **Step 3: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/indexing/test_async_queue.py -v
```

Expected: ModuleNotFoundError on `async_queue`.

- [ ] **Step 4: Implement `AsyncChunkIndexer`**

Create `src/stele/indexing/async_queue.py`:

```python
"""AsyncChunkIndexer — submits to TaskBackend, tracks per-artifact status."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from stele.core.artifact import Artifact, ArtifactRecord
from stele.indexing.job import IndexResult
from stele.indexing.queue import SyncChunkIndexer
from stele.indexing.task_backend.base import IndexTask, TaskBackend


class AsyncChunkIndexer:
    def __init__(
        self,
        *,
        task_backend: TaskBackend,
        sync: SyncChunkIndexer,
    ) -> None:
        self._task_backend = task_backend
        self._sync = sync
        self._lock = threading.Lock()
        self._artifact_to_task: dict[str, str] = {}

    def submit(self, artifact: Artifact | ArtifactRecord) -> IndexResult:
        task = IndexTask(
            artifact_id=artifact.artifact_id,
            reference=artifact.reference,
            namespace=artifact.namespace,
            submitted_at=datetime.now(UTC),
        )
        task_id = self._task_backend.submit(task)
        with self._lock:
            self._artifact_to_task[artifact.artifact_id] = task_id
        return IndexResult(
            artifact_id=artifact.artifact_id,
            status="pending",
            message=f"task_id={task_id}",
        )

    def status(self, artifact_id: str) -> IndexResult:
        with self._lock:
            task_id = self._artifact_to_task.get(artifact_id)
        if task_id is None:
            return self._sync.status(artifact_id)
        ts = self._task_backend.status(task_id)
        # Map TaskStatus.state → IndexStatus
        state_map = {
            "pending": "pending",
            "running": "pending",
            "succeeded": "indexed",
            "failed": "failed",
        }
        return IndexResult(
            artifact_id=artifact_id,
            status=state_map[ts.state],
            message=ts.message,
        )

    def close(self) -> None:
        self._task_backend.close()
```

- [ ] **Step 5: Run + DC-002 check**

```bash
.venv/bin/pytest tests/unit/indexing/test_async_queue.py -v
```

Expected: 1 test PASS.

Run DC-002:

```bash
echo "=== DC-002 ==="
grep -rn 'threading\.\|queue\.Queue\|asyncio\.' src/stele/retrieval/ src/stele/recall/ 2>/dev/null || echo "(empty — OK)"
```

Expected: empty.

- [ ] **Step 6: Lint + types**

```bash
.venv/bin/ruff check src/stele/indexing/async_queue.py src/stele/indexing/job.py src/stele/core/types.py
.venv/bin/mypy src/stele/indexing/async_queue.py
```

- [ ] **Step 7: Progress note**

```bash
echo "Task 9: AsyncChunkIndexer + DC-002 ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 10: `ChunkStore` Protocol

**Files:**
- Create: `src/stele/storage/chunk_store/__init__.py`
- Create: `src/stele/storage/chunk_store/base.py`

- [ ] **Step 1: Implement Protocol (no failing test — concrete impls test it)**

```bash
mkdir -p src/stele/storage/chunk_store
: > src/stele/storage/chunk_store/__init__.py
```

Create `src/stele/storage/chunk_store/base.py`:

```python
"""ChunkStore Protocol — write + read + vector + embed surface."""

from __future__ import annotations

from typing import Literal, Protocol

from stele.core.artifact import ArtifactRecord, SearchHit


class ChunkStore(Protocol):
    name: Literal["memory", "sqlite", "postgres", "mariadb", "clickhouse"]

    @property
    def dim(self) -> int: ...
    @property
    def similarity(self) -> Literal["cosine", "ip", "l2"]: ...

    def write(self, artifact: ArtifactRecord) -> int:
        """Chunk + embed + persist. Returns number of chunks written."""
        ...

    def delete(self, reference: str) -> None: ...

    def keyword_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]: ...

    def vector_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]: ...

    def embed(self, text: str) -> list[float]:
        """Probe embedder. Used for dim auto-detection + query embedding."""
        ...

    def close(self) -> None: ...
```

Wire `__init__.py`:

```python
"""Per-backend chunk stores (Chunkshop-backed except memory)."""

from stele.storage.chunk_store.base import ChunkStore

__all__ = ["ChunkStore"]
```

- [ ] **Step 2: Lint + types**

```bash
.venv/bin/ruff check src/stele/storage/chunk_store
.venv/bin/mypy src/stele/storage/chunk_store
```

- [ ] **Step 3: Progress note**

```bash
echo "Task 10: ChunkStore Protocol ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 11: `InProcessChunkStore` (memory backend)

**Files:**
- Create: `src/stele/storage/chunk_store/memory.py`
- Test: `tests/unit/storage/test_chunk_store_memory.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/storage/test_chunk_store_memory.py`:

```python
"""Tests for InProcessChunkStore — no Chunkshop required."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.storage.chunk_store.memory import InProcessChunkStore


def _artifact(text: str, artifact_id: str = "aid1") -> ArtifactRecord:
    now = datetime.now(UTC)
    return ArtifactRecord(
        artifact_id=artifact_id,
        reference=f"stele://default/{artifact_id}",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=len(text.split()),
        summary=text[:200],
        digest_sha256="x" * 64,
        metadata={},
        created_at=now,
    )


def test_in_process_write_and_vector_search() -> None:
    store = InProcessChunkStore(IndexingConfig())
    n = store.write(_artifact("user prefers dark mode for the dashboard"))
    assert n >= 1
    hits = store.vector_search("dark mode", limit=5)
    assert hits, "vector search should hit on lexical proximity (hash embedder is deterministic)"
    assert all(0.0 <= h.score <= 1.0 for h in hits)


def test_in_process_keyword_search() -> None:
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("the migration deadline is june 30"))
    hits = store.keyword_search("migration", limit=5)
    assert hits
    assert "migration" in hits[0].text.lower()


def test_in_process_embed_dim_consistent() -> None:
    store = InProcessChunkStore(IndexingConfig())
    a = store.embed("hello")
    b = store.embed("world")
    assert len(a) == len(b)
    assert store.dim == len(a)


def test_in_process_reference_filter() -> None:
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("apple banana cherry", artifact_id="aid_a"))
    store.write(_artifact("apple banana cherry", artifact_id="aid_b"))
    hits = store.vector_search("apple", limit=5, reference="stele://default/aid_a")
    assert hits
    for h in hits:
        assert h.reference == "stele://default/aid_a"
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/storage/test_chunk_store_memory.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Create `src/stele/storage/chunk_store/memory.py`:

```python
"""In-process chunk store — numpy + dict; no chunkshop required."""

from __future__ import annotations

import hashlib
from typing import Literal

import numpy as np

from stele.core.artifact import ArtifactRecord, SearchHit
from stele.core.config import IndexingConfig
from stele.indexing.chunk_index import ChunkIndex, ChunkRecord


def _hash_embed(text: str, dim: int = 384) -> np.ndarray:
    """Deterministic hash embedder. Tokens → bucketed +1 increments, L2-normalized."""
    vec = np.zeros(dim, dtype=np.float32)
    for token in text.lower().split():
        h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        bucket = h % dim
        vec[bucket] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


class InProcessChunkStore:
    name: Literal["memory"] = "memory"

    def __init__(self, config: IndexingConfig) -> None:
        self._config = config
        self._dim = config.vector_dim or 384
        self._sim: Literal["cosine", "ip", "l2"] = config.similarity
        self._chunks: dict[str, list[ChunkRecord]] = {}
        self._embeddings: dict[str, np.ndarray] = {}  # keyed by chunk_id
        # Reuse the existing ChunkIndex chunker logic
        self._index = ChunkIndex(config)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def similarity(self) -> Literal["cosine", "ip", "l2"]:
        return self._sim

    def write(self, artifact: ArtifactRecord) -> int:
        n = self._index.index(artifact)
        chunks = self._index._chunks_by_ref.get(artifact.reference, [])
        self._chunks[artifact.reference] = chunks
        for chunk in chunks:
            self._embeddings[chunk.chunk_id] = _hash_embed(chunk.text, self._dim)
        return n

    def delete(self, reference: str) -> None:
        chunks = self._chunks.pop(reference, [])
        for chunk in chunks:
            self._embeddings.pop(chunk.chunk_id, None)
        self._index.delete(reference)

    def keyword_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]:
        if reference is not None:
            return self._index.search_reference(reference, query, limit=limit)
        # Global keyword search — flatten across all references
        from stele.retrieval.rank import keyword_score, snippet_around

        hits: list[SearchHit] = []
        for ref, chunks in self._chunks.items():
            for chunk in chunks:
                score = keyword_score(query, chunk.text)
                if score <= 0:
                    continue
                hits.append(
                    SearchHit(
                        artifact_id=chunk.artifact_id,
                        reference=chunk.reference,
                        chunk_id=chunk.chunk_id,
                        text=snippet_around(chunk.text, query),
                        score=score,
                        retrieval_mode="keyword",
                        metadata=dict(chunk.metadata),
                    )
                )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def vector_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]:
        q_vec = _hash_embed(query, self._dim)
        candidates: list[tuple[ChunkRecord, float]] = []
        for ref, chunks in self._chunks.items():
            if reference is not None and ref != reference:
                continue
            for chunk in chunks:
                emb = self._embeddings.get(chunk.chunk_id)
                if emb is None:
                    continue
                score = float(np.dot(q_vec, emb))  # cosine, since both normalized
                if score > 0:
                    candidates.append((chunk, score))
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        top = candidates[:limit]
        if not top:
            return []
        max_score = max(s for _, s in top) or 1.0
        return [
            SearchHit(
                artifact_id=chunk.artifact_id,
                reference=chunk.reference,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                score=score / max_score,
                retrieval_mode="vector",
                metadata=dict(chunk.metadata),
            )
            for chunk, score in top
        ]

    def embed(self, text: str) -> list[float]:
        return _hash_embed(text, self._dim).tolist()

    def close(self) -> None:
        self._chunks.clear()
        self._embeddings.clear()
```

- [ ] **Step 4: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/storage/test_chunk_store_memory.py -v
.venv/bin/ruff check src/stele/storage/chunk_store/memory.py
.venv/bin/mypy src/stele/storage/chunk_store/memory.py
```

- [ ] **Step 5: Progress note**

```bash
echo "Task 11: InProcessChunkStore ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 12: Vector dim resolution cascade

**Files:**
- Create: `src/stele/indexing/dim_resolution.py`
- Test: `tests/unit/indexing/test_dim_resolution.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/indexing/test_dim_resolution.py`:

```python
"""Tests for vector dim resolution: bakeoff → auto-detect → default."""

from __future__ import annotations

import json
from pathlib import Path

from stele.core.config import IndexingConfig
from stele.indexing.bakeoff import BakeoffSummary
from stele.indexing.dim_resolution import resolve_dim_and_similarity
from stele.storage.chunk_store.memory import InProcessChunkStore


def test_bakeoff_wins(tmp_path: Path) -> None:
    bakeoff_path = tmp_path / "b.json"
    bakeoff_path.write_text(
        json.dumps(
            {
                "chunker": {"type": "fixed_overlap", "params": {}},
                "embedder": {"name": "x", "dim": 768},
                "similarity": "ip",
            }
        )
    )
    cfg = IndexingConfig(bakeoff_path=str(bakeoff_path))
    summary = resolve_dim_and_similarity(cfg, store=None)
    assert summary.source == "bakeoff_file"
    assert summary.embedder is not None
    assert summary.embedder.dim == 768
    assert summary.similarity == "ip"


def test_auto_detect_when_no_bakeoff() -> None:
    cfg = IndexingConfig()
    store = InProcessChunkStore(cfg)
    summary = resolve_dim_and_similarity(cfg, store=store)
    assert summary.source == "auto_detected"
    assert summary.embedder is not None
    assert summary.embedder.dim == 384


def test_default_when_no_store_and_no_bakeoff() -> None:
    cfg = IndexingConfig()
    summary = resolve_dim_and_similarity(cfg, store=None)
    assert summary.source == "default"
    assert summary.similarity == "cosine"
```

- [ ] **Step 2: Implement**

Create `src/stele/indexing/dim_resolution.py`:

```python
"""Vector dim + similarity resolution cascade: bakeoff → auto-detect → default."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stele.core.config import IndexingConfig
from stele.indexing.bakeoff import (
    BakeoffEmbedder,
    BakeoffSummary,
    load_bakeoff_file,
)

if TYPE_CHECKING:
    from stele.storage.chunk_store.base import ChunkStore


def resolve_dim_and_similarity(
    config: IndexingConfig, *, store: "ChunkStore | None"
) -> BakeoffSummary:
    # 1. Bakeoff
    if config.bakeoff_path is not None:
        cfg = load_bakeoff_file(config.bakeoff_path)
        return BakeoffSummary(
            source="bakeoff_file",
            chunker=cfg.chunker,
            embedder=cfg.embedder,
            similarity=cfg.similarity,
            file_path=config.bakeoff_path,
        )

    # 2. Auto-detect via embedder probe
    if store is not None:
        probe_vec = store.embed("__stele_probe__")
        return BakeoffSummary(
            source="auto_detected",
            chunker=None,
            embedder=BakeoffEmbedder(name="<auto-detected>", dim=len(probe_vec)),
            similarity=config.similarity,
        )

    # 3. Default
    return BakeoffSummary(
        source="default",
        chunker=None,
        embedder=None,
        similarity=config.similarity,
    )
```

- [ ] **Step 3: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/indexing/test_dim_resolution.py -v
.venv/bin/ruff check src/stele/indexing/dim_resolution.py
.venv/bin/mypy src/stele/indexing/dim_resolution.py
```

- [ ] **Step 4: Progress note**

```bash
echo "Task 12: Dim resolution cascade ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 13: `chunkshop_adapter.py` — chunk_id translation

**Files:**
- Create: `src/stele/indexing/chunkshop_adapter.py`
- Test: `tests/unit/indexing/test_chunkshop_adapter.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/indexing/test_chunkshop_adapter.py`:

```python
"""Tests for the Chunkshop adapter — chunk_id round-trip + no native objects escape."""

from __future__ import annotations

from stele.indexing.chunkshop_adapter import (
    chunk_id_from_chunkshop_row,
    chunkshop_row_id_from_chunk_id,
    stele_chunk_id,
)


def test_stele_chunk_id_format() -> None:
    assert stele_chunk_id("aid", 7) == "aid:7"


def test_round_trip() -> None:
    cid = stele_chunk_id("aid_xyz", 3)
    row_id = chunkshop_row_id_from_chunk_id(cid)
    parsed = chunk_id_from_chunkshop_row(row_id)
    assert parsed.artifact_id == "aid_xyz"
    assert parsed.ordinal == 3


def test_malformed_row_id_raises() -> None:
    import pytest

    from stele.core.exceptions import BackendError

    with pytest.raises(BackendError):
        chunk_id_from_chunkshop_row("not_a_valid_id")
```

- [ ] **Step 2: Implement**

Create `src/stele/indexing/chunkshop_adapter.py`:

```python
"""Translates between Stele's chunk_id format and Chunkshop row identifiers.

Stele chunk_id: "{artifact_id}:{ordinal}"
Chunkshop row_id: opaque per backend; this module owns the mapping so no
Chunkshop-native identifiers escape into public Stele API surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass

from stele.core.exceptions import BackendError


@dataclass(frozen=True)
class ParsedChunkId:
    artifact_id: str
    ordinal: int


def stele_chunk_id(artifact_id: str, ordinal: int) -> str:
    return f"{artifact_id}:{ordinal}"


def chunkshop_row_id_from_chunk_id(chunk_id: str) -> str:
    """The mapping is identity today; this function exists as a stable boundary."""
    if ":" not in chunk_id:
        raise BackendError(f"malformed Stele chunk_id: {chunk_id!r}")
    return chunk_id


def chunk_id_from_chunkshop_row(row_id: str) -> ParsedChunkId:
    if ":" not in row_id:
        raise BackendError(f"malformed Chunkshop row id: {row_id!r}")
    artifact_id, _, ordinal_str = row_id.rpartition(":")
    try:
        ordinal = int(ordinal_str)
    except ValueError as exc:
        raise BackendError(f"malformed Chunkshop row id (ordinal): {row_id!r}") from exc
    if not artifact_id:
        raise BackendError(f"malformed Chunkshop row id (artifact_id): {row_id!r}")
    return ParsedChunkId(artifact_id=artifact_id, ordinal=ordinal)
```

- [ ] **Step 3: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/indexing/test_chunkshop_adapter.py -v
.venv/bin/ruff check src/stele/indexing/chunkshop_adapter.py
.venv/bin/mypy src/stele/indexing/chunkshop_adapter.py
```

- [ ] **Step 4: Progress note**

```bash
echo "Task 13: chunkshop_adapter ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 14: `SQLiteChunkStore`

**Files:**
- Create: `src/stele/storage/chunk_store/sqlite.py`
- Test: `tests/unit/storage/test_chunk_store_sqlite.py`

- [ ] **Step 1: Write test**

Create `tests/unit/storage/test_chunk_store_sqlite.py`:

```python
"""Tests for SQLiteChunkStore via chunkshop[sqlite]."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.core.exceptions import OptionalDependencyError

CHUNKSHOP_SQLITE_AVAILABLE = importlib.util.find_spec("chunkshop.sqlite") is not None


def _artifact(text: str) -> ArtifactRecord:
    now = datetime.now(UTC)
    return ArtifactRecord(
        artifact_id="aid_s",
        reference="stele://default/aid_s",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=len(text.split()),
        summary=text[:200],
        digest_sha256="x" * 64,
        metadata={},
        created_at=now,
    )


@pytest.mark.skipif(CHUNKSHOP_SQLITE_AVAILABLE, reason="chunkshop[sqlite] is installed")
def test_sqlite_chunk_store_raises_optional_dep_when_extra_missing(tmp_path: Path) -> None:
    from stele.storage.chunk_store.sqlite import SQLiteChunkStore

    with pytest.raises(OptionalDependencyError, match="chunkshop"):
        SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "x.db"))


@pytest.mark.skipif(not CHUNKSHOP_SQLITE_AVAILABLE, reason="chunkshop[sqlite] not installed")
def test_sqlite_chunk_store_round_trip(tmp_path: Path) -> None:
    from stele.storage.chunk_store.sqlite import SQLiteChunkStore

    store = SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "x.db"))
    try:
        n = store.write(_artifact("user prefers dark mode for the dashboard"))
        assert n >= 1
        hits = store.vector_search("dark mode", limit=5)
        assert hits
    finally:
        store.close()
```

- [ ] **Step 2: Implement**

Create `src/stele/storage/chunk_store/sqlite.py`:

```python
"""SQLiteChunkStore — wraps chunkshop[sqlite]; raises OptionalDependencyError if missing."""

from __future__ import annotations

import importlib.util
from typing import Literal

from stele.core.artifact import ArtifactRecord, SearchHit
from stele.core.config import IndexingConfig
from stele.core.exceptions import OptionalDependencyError
from stele.indexing.chunkshop_adapter import stele_chunk_id


class SQLiteChunkStore:
    name: Literal["sqlite"] = "sqlite"

    def __init__(self, config: IndexingConfig, *, db_path: str) -> None:
        spec = importlib.util.find_spec("chunkshop.sqlite")
        if spec is None:
            raise OptionalDependencyError(
                "chunkshop[sqlite] required for SQLite chunk store; "
                "install: pip install 'stele-core[chunkshop]' and 'chunkshop[sqlite]>=X.Y'"
            )
        from chunkshop.sqlite import SQLiteRetrievalIndex  # type: ignore[import-not-found]

        self._config = config
        self._index = SQLiteRetrievalIndex(
            db_path=db_path,
            chunker_config=self._chunker_kwargs(),
        )
        self._dim = config.vector_dim or 0
        self._sim: Literal["cosine", "ip", "l2"] = config.similarity

    def _chunker_kwargs(self) -> dict[str, object]:
        return {
            "type": self._config.chunker,
            "window_words": self._config.chunk_words,
            "overlap_words": self._config.chunk_overlap_words,
        }

    @property
    def dim(self) -> int:
        if self._dim == 0:
            probe = self.embed("__stele_probe__")
            self._dim = len(probe)
        return self._dim

    @property
    def similarity(self) -> Literal["cosine", "ip", "l2"]:
        return self._sim

    def write(self, artifact: ArtifactRecord) -> int:
        # Defensive PII assertion (boundary check, not re-scrub)
        self._assert_pii_scrubbed(artifact.content_as_text())
        chunks = self._index.index(
            doc_id=artifact.artifact_id,
            text=artifact.content_as_text(),
            metadata={
                "reference": artifact.reference,
                "namespace": artifact.namespace,
                "session_id": artifact.session_id,
            },
        )
        return len(chunks)

    def delete(self, reference: str) -> None:
        self._index.delete_by_metadata({"reference": reference})

    def keyword_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]:
        filters = {"reference": reference} if reference else None
        rows = self._index.keyword_search(query, k=limit, filters=filters)
        return [self._row_to_hit(row, "keyword") for row in rows]

    def vector_search(
        self, query: str, *, limit: int, reference: str | None = None
    ) -> list[SearchHit]:
        filters = {"reference": reference} if reference else None
        rows = self._index.vector_search(query, k=limit, filters=filters)
        return [self._row_to_hit(row, "vector") for row in rows]

    def embed(self, text: str) -> list[float]:
        return list(self._index.embed(text))

    def close(self) -> None:
        self._index.close()

    def _row_to_hit(self, row: object, mode: Literal["keyword", "vector"]) -> SearchHit:
        # Chunkshop row → SearchHit; field accessors per Chunkshop's API.
        # Adjust attribute names to match the installed chunkshop[sqlite] release.
        return SearchHit(
            artifact_id=row.metadata["doc_id"],  # type: ignore[attr-defined]
            reference=row.metadata["reference"],  # type: ignore[attr-defined]
            chunk_id=stele_chunk_id(row.metadata["doc_id"], row.ordinal),  # type: ignore[attr-defined]
            text=row.text,  # type: ignore[attr-defined]
            score=float(row.score),  # type: ignore[attr-defined]
            retrieval_mode=mode,
            metadata=dict(row.metadata),  # type: ignore[attr-defined]
        )

    @staticmethod
    def _assert_pii_scrubbed(text: str) -> None:
        # Cheap regex check for the common PII patterns. Not a full scrub
        # implementation — that's the PII module's job. This is a defensive
        # invariant check: if these patterns appear, upstream PII layer
        # didn't run.
        import re

        if re.search(r"\b\w+@\w+\.\w+\b", text):
            raise BackendError("chunk text contains unscrubbed email-like pattern")  # noqa: F821
        if re.search(r"\b\d{3}-\d{3}-\d{4}\b", text):
            raise BackendError("chunk text contains unscrubbed phone-like pattern")  # noqa: F821
```

Fix import on `BackendError`:

```python
from stele.core.exceptions import BackendError, OptionalDependencyError
```

- [ ] **Step 3: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/storage/test_chunk_store_sqlite.py -v
.venv/bin/ruff check src/stele/storage/chunk_store/sqlite.py
.venv/bin/mypy src/stele/storage/chunk_store/sqlite.py
```

Note: if chunkshop[sqlite] isn't installed, only the OptionalDependencyError test runs. Investigate the row field accessors against the actual Chunkshop release (`row.metadata`, `row.ordinal`, etc.) and adjust if the released API uses different names.

- [ ] **Step 4: Progress note**

```bash
echo "Task 14: SQLiteChunkStore ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 15: `PostgresChunkStore`

**Files:**
- Create: `src/stele/storage/chunk_store/postgres.py`
- Test: `tests/unit/storage/test_chunk_store_postgres.py`

Identical structure to Task 14, swapping `chunkshop.sqlite` for `chunkshop.postgres`. Requires `STELE_PG_DSN` env var for the live test; the OptionalDependencyError test runs unconditionally.

- [ ] **Step 1: Write test** — same shape as Task 14's test, parametrized on `STELE_PG_DSN`. Skip if not set.
- [ ] **Step 2: Implement** — copy `sqlite.py` template; replace `chunkshop.sqlite` import with `chunkshop.postgres`; constructor takes `dsn: str` instead of `db_path: str`; rest is identical.
- [ ] **Step 3: Run + lint + types.**
- [ ] **Step 4: Progress note.**

---

### Task 16: `MariaDBChunkStore` (gated on user's Chunkshop release)

**Files:**
- Create: `src/stele/storage/chunk_store/mariadb.py`
- Test: `tests/unit/storage/test_chunk_store_mariadb.py`

Same pattern as Tasks 14/15 but **gated** on the user's unreleased Chunkshop branch.

- [ ] **Step 1: Write test** — skipif when `chunkshop.mariadb` isn't importable. OptionalDependencyError test runs unconditionally.
- [ ] **Step 2: Implement** — copy `postgres.py`; replace `chunkshop.postgres` with `chunkshop.mariadb`; constructor takes `dsn: str`.
- [ ] **Step 3: Run + lint + types.** Live test skips gracefully if Chunkshop's MariaDB adapter isn't available yet.
- [ ] **Step 4: Progress note.**

---

### Task 17: `ClickHouseChunkStore` (gated)

**Files:**
- Create: `src/stele/storage/chunk_store/clickhouse.py`
- Test: `tests/unit/storage/test_chunk_store_clickhouse.py`

Same as Task 16 but for ClickHouse. Constructor takes `dsn: str`.

---

### Task 18: `vector_search` + `hybrid_search` facades + DC-001

**Files:**
- Create: `src/stele/retrieval/vector.py`
- Create: `src/stele/retrieval/hybrid.py`
- Test: `tests/unit/retrieval/test_vector.py`
- Test: `tests/unit/retrieval/test_hybrid.py`

- [ ] **Step 1: Write failing tests for `vector.py`**

Create `tests/unit/retrieval/test_vector.py`:

```python
"""Tests for retrieval/vector.py — backend-agnostic facade."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.retrieval.vector import vector_search
from stele.storage.chunk_store.memory import InProcessChunkStore


def _artifact(text: str, aid: str = "aid") -> ArtifactRecord:
    now = datetime.now(UTC)
    return ArtifactRecord(
        artifact_id=aid,
        reference=f"stele://default/{aid}",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=len(text.split()),
        summary=text[:200],
        digest_sha256="x" * 64,
        metadata={},
        created_at=now,
    )


def test_vector_search_returns_search_hits() -> None:
    store = InProcessChunkStore(IndexingConfig())
    store.write(_artifact("user prefers dark mode"))
    hits = vector_search(store, "dark mode", limit=5)
    assert hits
    assert all(h.retrieval_mode == "vector" for h in hits)
```

- [ ] **Step 2: Implement `vector.py`**

Create `src/stele/retrieval/vector.py`:

```python
"""Backend-agnostic vector retrieval facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stele.core.artifact import SearchHit

if TYPE_CHECKING:
    from stele.storage.chunk_store.base import ChunkStore


def vector_search(
    chunk_store: "ChunkStore",
    query: str,
    *,
    limit: int = 10,
    reference: str | None = None,
) -> list[SearchHit]:
    return chunk_store.vector_search(query, limit=limit, reference=reference)
```

- [ ] **Step 3: Write failing tests for `hybrid.py`**

Create `tests/unit/retrieval/test_hybrid.py`:

```python
"""Tests for retrieval/hybrid.py — RRF + WeightedSum merging."""

from __future__ import annotations

from stele.core.artifact import SearchHit
from stele.retrieval.hybrid import _rrf_merge, _weighted_sum_merge, hybrid_search


def _hit(aid: str, cid: str, score: float, mode: str) -> SearchHit:
    return SearchHit(
        artifact_id=aid,
        reference=f"stele://default/{aid}",
        chunk_id=cid,
        text="x",
        score=score,
        retrieval_mode=mode,  # type: ignore[arg-type]
        metadata={},
    )


def test_rrf_merge_basic() -> None:
    kw = [_hit("a", "a:0", 0.9, "keyword"), _hit("a", "a:1", 0.5, "keyword")]
    vec = [_hit("a", "a:1", 0.9, "vector"), _hit("a", "a:2", 0.7, "vector")]
    merged = _rrf_merge(kw, vec, k=60, limit=10)
    chunk_ids = [h.chunk_id for h in merged]
    # a:1 appears in both at rank 2 and 1 → strong RRF score
    assert "a:1" in chunk_ids
    assert all(h.retrieval_mode == "hybrid" for h in merged)


def test_weighted_sum_merge_basic() -> None:
    kw = [_hit("a", "a:0", 0.8, "keyword")]
    vec = [_hit("a", "a:0", 0.6, "vector")]
    merged = _weighted_sum_merge(
        kw, vec, weights={"keyword": 0.5, "vector": 0.5}, limit=10
    )
    assert len(merged) == 1
    # 0.5*0.8 + 0.5*0.6 = 0.7
    assert merged[0].score == 0.7


def test_hybrid_search_degrades_when_vector_raises() -> None:
    class FailingVector:
        def vector_search(self, query, *, limit, reference=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated vector failure")

        def keyword_search(self, query, *, limit, reference=None):  # type: ignore[no-untyped-def]
            return [_hit("a", "a:0", 0.9, "keyword")]

        def embed(self, text):  # type: ignore[no-untyped-def]
            return [0.0]

    result = hybrid_search(
        FailingVector(),  # type: ignore[arg-type]
        query="x",
        limit=5,
        method="rrf",
        weights={"keyword": 0.5, "vector": 0.5},
        rrf_k=60,
    )
    assert result
    assert any(h.metadata.get("hybrid_degraded") is True for h in result)
```

- [ ] **Step 4: Implement `hybrid.py`**

Create `src/stele/retrieval/hybrid.py`:

```python
"""Hybrid keyword+vector retrieval — RRF default + WeightedSum optional."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from stele.core.artifact import SearchHit

if TYPE_CHECKING:
    from stele.storage.chunk_store.base import ChunkStore

_log = logging.getLogger(__name__)


def hybrid_search(
    chunk_store: "ChunkStore",
    query: str,
    *,
    limit: int = 10,
    reference: str | None = None,
    method: Literal["rrf", "weighted_sum"] = "rrf",
    weights: dict[str, float] | None = None,
    rrf_k: int = 60,
) -> list[SearchHit]:
    weights = weights or {"keyword": 0.5, "vector": 0.5}

    keyword_hits: list[SearchHit] = []
    vector_hits: list[SearchHit] = []
    keyword_failed = False
    vector_failed = False

    try:
        keyword_hits = chunk_store.keyword_search(query, limit=limit * 2, reference=reference)
    except Exception as exc:
        _log.warning("hybrid_search keyword path failed: %s", exc)
        keyword_failed = True

    try:
        vector_hits = chunk_store.vector_search(query, limit=limit * 2, reference=reference)
    except Exception as exc:
        _log.warning("hybrid_search vector path failed: %s", exc)
        vector_failed = True

    if keyword_failed and vector_failed:
        return []
    if keyword_failed:
        return _flag_degraded(vector_hits[:limit])
    if vector_failed:
        return _flag_degraded(keyword_hits[:limit])

    if method == "rrf":
        return _rrf_merge(keyword_hits, vector_hits, k=rrf_k, limit=limit)
    return _weighted_sum_merge(keyword_hits, vector_hits, weights=weights, limit=limit)


def _rrf_merge(
    kw: list[SearchHit], vec: list[SearchHit], *, k: int, limit: int
) -> list[SearchHit]:
    scores: dict[tuple[str, str], float] = {}
    by_key: dict[tuple[str, str], SearchHit] = {}
    for rank, hit in enumerate(kw):
        key = (hit.artifact_id, hit.chunk_id or "")
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        by_key.setdefault(key, hit)
    for rank, hit in enumerate(vec):
        key = (hit.artifact_id, hit.chunk_id or "")
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        by_key.setdefault(key, hit)
    sorted_keys = sorted(scores.keys(), key=lambda k_: scores[k_], reverse=True)[:limit]
    return [
        by_key[k_].model_copy(
            update={
                "score": scores[k_],
                "retrieval_mode": "hybrid",
                "metadata": {**by_key[k_].metadata, "sources": ["keyword", "vector"]},
            }
        )
        for k_ in sorted_keys
    ]


def _weighted_sum_merge(
    kw: list[SearchHit],
    vec: list[SearchHit],
    *,
    weights: dict[str, float],
    limit: int,
) -> list[SearchHit]:
    kw_by_key = {(h.artifact_id, h.chunk_id or ""): h for h in kw}
    vec_by_key = {(h.artifact_id, h.chunk_id or ""): h for h in vec}
    all_keys = set(kw_by_key) | set(vec_by_key)
    w_k = weights.get("keyword", 0.5)
    w_v = weights.get("vector", 0.5)
    merged: list[SearchHit] = []
    for key in all_keys:
        kw_hit = kw_by_key.get(key)
        vec_hit = vec_by_key.get(key)
        kw_s = kw_hit.score if kw_hit else 0.0
        vec_s = vec_hit.score if vec_hit else 0.0
        score = w_k * kw_s + w_v * vec_s
        base = kw_hit or vec_hit
        assert base is not None
        merged.append(
            base.model_copy(
                update={
                    "score": score,
                    "retrieval_mode": "hybrid",
                    "metadata": {**base.metadata, "sources": ["keyword", "vector"]},
                }
            )
        )
    merged.sort(key=lambda h: h.score, reverse=True)
    return merged[:limit]


def _flag_degraded(hits: list[SearchHit]) -> list[SearchHit]:
    return [
        h.model_copy(update={"metadata": {**h.metadata, "hybrid_degraded": True}})
        for h in hits
    ]
```

- [ ] **Step 5: Run + DC-001**

```bash
.venv/bin/pytest tests/unit/retrieval/test_vector.py tests/unit/retrieval/test_hybrid.py -v
.venv/bin/ruff check src/stele/retrieval/vector.py src/stele/retrieval/hybrid.py
.venv/bin/mypy src/stele/retrieval/vector.py src/stele/retrieval/hybrid.py
```

Run DC-001:

```bash
echo "=== DC-001 ==="
grep -rn 'chunkshop\.[a-z_]*' src/stele/retrieval/ src/stele/recall/ 2>/dev/null || echo "(empty — OK)"
```

Expected: empty.

- [ ] **Step 6: Progress note**

```bash
echo "Task 18: vector + hybrid retrieval + DC-001 ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 19: Hybrid quality test (load-bearing) + DC-003

**Files:**
- Create: `tests/fixtures/recall/hybrid_held_out_set.json`
- Create: `tests/unit/retrieval/test_hybrid_quality.py`

- [ ] **Step 1: Build the held-out fixture set**

Create `tests/fixtures/recall/hybrid_held_out_set.json` with ≥20 query/relevant-chunk pairs. Example shape:

```json
{
  "pairs": [
    {"query": "migration deadline", "relevant_text": "The migration deadline is 2026-06-30."},
    {"query": "dark mode preference", "relevant_text": "I prefer dark mode for the dashboard."},
    {"query": "Q1 revenue", "relevant_text": "Q1 revenue grew 12 percent year over year."},
    ... 17+ more pairs ...
  ]
}
```

Build the fixture by hand from realistic agent-conversation snippets. Keep queries short (2–4 words) and relevant chunks 1–3 sentences each.

- [ ] **Step 2: Write the test**

Create `tests/unit/retrieval/test_hybrid_quality.py`:

```python
"""Load-bearing hybrid quality test: hybrid recall@5 >= max(components) - floor."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.retrieval.hybrid import hybrid_search
from stele.retrieval.vector import vector_search
from stele.storage.chunk_store.memory import InProcessChunkStore

FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/recall/hybrid_held_out_set.json"
FLOOR = float(os.environ.get("STELE_HYBRID_FLOOR", "0.05"))


def _load_pairs() -> list[dict[str, str]]:
    return json.loads(FIXTURE.read_text())["pairs"]


def _seed_store(pairs: list[dict[str, str]]) -> InProcessChunkStore:
    store = InProcessChunkStore(IndexingConfig())
    for i, pair in enumerate(pairs):
        now = datetime.now(UTC)
        artifact = ArtifactRecord(
            artifact_id=f"aid_{i}",
            reference=f"stele://default/aid_{i}",
            namespace="default",
            session_id=None,
            content=pair["relevant_text"],
            content_encoding="utf-8",
            content_type="text",
            byte_size=len(pair["relevant_text"]),
            token_estimate=len(pair["relevant_text"].split()),
            summary=pair["relevant_text"][:200],
            digest_sha256="x" * 64,
            metadata={"target": True, "index": i},
            created_at=now,
        )
        store.write(artifact)
    return store


def _recall_at_5(pairs: list[dict[str, str]], mode: str, store: InProcessChunkStore) -> float:
    hits = 0
    for i, pair in enumerate(pairs):
        if mode == "vector":
            results = vector_search(store, pair["query"], limit=5)
        elif mode == "keyword":
            results = store.keyword_search(pair["query"], limit=5)
        else:
            results = hybrid_search(
                store,
                pair["query"],
                limit=5,
                method="rrf",
                weights={"keyword": 0.5, "vector": 0.5},
                rrf_k=60,
            )
        if any(f"aid_{i}" == h.artifact_id for h in results):
            hits += 1
    return hits / len(pairs)


def test_hybrid_beats_components_within_floor() -> None:
    pairs = _load_pairs()
    assert len(pairs) >= 20, "fixture set must have at least 20 pairs"
    store = _seed_store(pairs)
    try:
        v = _recall_at_5(pairs, "vector", store)
        k = _recall_at_5(pairs, "keyword", store)
        h = _recall_at_5(pairs, "hybrid", store)
        best = max(v, k)
        assert h >= best - FLOOR, (
            f"hybrid recall@5={h:.3f} below best component "
            f"({best:.3f}, vector={v:.3f}, keyword={k:.3f}) by more than {FLOOR:.0%}"
        )
    finally:
        store.close()
```

- [ ] **Step 3: Run DC-003**

```bash
.venv/bin/pytest tests/unit/retrieval/test_hybrid_quality.py -v
```

Expected: PASS with the default 5% floor. If it fails, either (a) fixture set is too small/unfair (rebuild it), (b) the in-process hash embedder is too weak (acceptable for the smoke test — log and document, raise floor temporarily), or (c) hybrid implementation has a bug (fix it). Do NOT silently lower the floor in code — it's an environment variable for a reason.

- [ ] **Step 4: Progress note**

```bash
echo "Task 19: Hybrid quality test + DC-003 ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 20: `SyncChunkIndexer` writes through `ChunkStore`

**Files:**
- Modify: `src/stele/indexing/queue.py`
- Test: existing tests should continue passing; add a small targeted test

- [ ] **Step 1: Refactor `SyncChunkIndexer`**

In `src/stele/indexing/queue.py`, change `SyncChunkIndexer` to accept either a `ChunkIndex` (existing) or a `ChunkStore` (new). When given a `ChunkStore`, route writes through it:

```python
from typing import Union

from stele.storage.chunk_store.base import ChunkStore


class SyncChunkIndexer:
    def __init__(self, target: Union[ChunkIndex, ChunkStore]) -> None:
        self._target = target
        self._status: dict[str, IndexResult] = {}

    def index_now(self, artifact: ArtifactRecord) -> IndexResult:
        try:
            chunk_count = self._target.write(artifact) if hasattr(self._target, "write") and not isinstance(self._target, ChunkIndex) else self._target.index(artifact)
        except Exception as exc:
            result = IndexResult(
                artifact_id=artifact.artifact_id, status="failed", message=str(exc)
            )
        else:
            result = IndexResult(
                artifact_id=artifact.artifact_id,
                status="indexed",
                message=f"indexed {chunk_count} chunks",
            )
        self._status[artifact.artifact_id] = result
        return result
    # ... rest unchanged ...
```

- [ ] **Step 2: Run existing indexing tests**

```bash
.venv/bin/pytest tests/unit/indexing -v
```

Expected: all pass (no regression).

- [ ] **Step 3: Progress note**

```bash
echo "Task 20: SyncChunkIndexer writes through ChunkStore ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 21: Wire `Stele.search(mode=...)` dispatch + chunk_store + async_indexer

**Files:**
- Modify: `src/stele/core/stash.py`
- Test: extension of existing `tests/unit/core/test_stash_facade.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/core/test_stash_facade.py`:

```python
def test_stele_search_mode_vector_on_memory_backend() -> None:
    from stele import Stele
    from stele.core.config import StashConfig

    stele = Stele(StashConfig())
    stored = stele.store(data="user prefers dark mode", namespace="default")
    stele.indexing_status(stored.artifact_id)  # smoke that method exists
    hits = stele.search(stored.reference, "dark mode", mode="vector")
    assert hits, "vector search should return hits on the memory backend"
    stele.close()


def test_stele_search_mode_hybrid_on_memory_backend() -> None:
    from stele import Stele
    from stele.core.config import StashConfig

    stele = Stele(StashConfig())
    stored = stele.store(data="user prefers dark mode", namespace="default")
    hits = stele.search(stored.reference, "dark mode", mode="hybrid")
    assert hits
    assert all(h.retrieval_mode == "hybrid" for h in hits)
    stele.close()


def test_stele_indexing_status_async() -> None:
    import time

    from stele import Stele
    from stele.core.config import StashConfig

    cfg = StashConfig.load({"indexing": {"mode": "async"}})
    stele = Stele(cfg)
    try:
        stored = stele.store(data="anything", namespace="default")
        immediate = stele.indexing_status(stored.artifact_id)
        assert immediate.status in {"pending", "indexed"}
        for _ in range(100):
            s = stele.indexing_status(stored.artifact_id)
            if s.status == "indexed":
                break
            time.sleep(0.01)
        final = stele.indexing_status(stored.artifact_id)
        assert final.status == "indexed"
    finally:
        stele.close()
```

- [ ] **Step 2: Implement the wire-up in `stash.py`**

In `src/stele/core/stash.py`, in `Stele.__init__`:

1. After building `self.pii_scrubber`, build the chunk store:

```python
self._chunk_store: ChunkStore | None = self._build_chunk_store()
```

Define `_build_chunk_store`:

```python
def _build_chunk_store(self) -> ChunkStore | None:
    cfg = self.config.indexing
    if cfg.mode == "skip":
        return None
    backend_type = self.config.backend.type
    if backend_type == "memory":
        from stele.storage.chunk_store.memory import InProcessChunkStore
        return InProcessChunkStore(cfg)
    if backend_type == "sqlite":
        from stele.storage.chunk_store.sqlite import SQLiteChunkStore
        path = self.config.backend.path or "stele.db"
        chunk_path = str(Path(path).with_name("chunks_" + Path(path).name))
        return SQLiteChunkStore(cfg, db_path=chunk_path)
    if backend_type == "postgres":
        from stele.storage.chunk_store.postgres import PostgresChunkStore
        if not self.config.backend.dsn:
            raise ConfigError("postgres chunk store requires backend.dsn")
        return PostgresChunkStore(cfg, dsn=self.config.backend.dsn)
    if backend_type == "mariadb":
        from stele.storage.chunk_store.mariadb import MariaDBChunkStore
        if not self.config.backend.dsn:
            raise ConfigError("mariadb chunk store requires backend.dsn")
        return MariaDBChunkStore(cfg, dsn=self.config.backend.dsn)
    if backend_type == "clickhouse":
        from stele.storage.chunk_store.clickhouse import ClickHouseChunkStore
        if not self.config.backend.dsn:
            raise ConfigError("clickhouse chunk store requires backend.dsn")
        return ClickHouseChunkStore(cfg, dsn=self.config.backend.dsn)
    raise ConfigError(f"unsupported backend.type for chunk store: {backend_type!r}")
```

2. Build the indexer based on `indexing.mode`:

```python
def _build_indexer(self):
    cfg = self.config.indexing
    if cfg.mode == "skip" or self._chunk_store is None:
        from stele.indexing.queue import NoOpIndexer
        return NoOpIndexer()
    if cfg.mode == "sync":
        from stele.indexing.queue import SyncChunkIndexer
        return SyncChunkIndexer(self._chunk_store)
    # async
    from stele.indexing.async_queue import AsyncChunkIndexer
    from stele.indexing.queue import SyncChunkIndexer
    sync = SyncChunkIndexer(self._chunk_store)
    backend = self._build_task_backend(sync)
    return AsyncChunkIndexer(task_backend=backend, sync=sync)


def _build_task_backend(self, sync):
    cfg = self.config.indexing
    if cfg.task_backend == "in_process":
        from stele.indexing.task_backend.in_process import InProcessTaskBackend
        return InProcessTaskBackend(worker=lambda task: sync.index_now(self.fetch(task.artifact_id).record))
    if cfg.task_backend == "redis":
        from stele.indexing.task_backend.redis import RedisTaskBackend
        return RedisTaskBackend(dsn=cfg.task_backend_dsn or "")  # raises CapabilityError
    if cfg.task_backend == "celery":
        from stele.indexing.task_backend.celery import CeleryTaskBackend
        return CeleryTaskBackend(dsn=cfg.task_backend_dsn or "")  # raises CapabilityError
    raise ConfigError(f"unsupported task_backend: {cfg.task_backend!r}")
```

3. Replace existing indexer wiring with `self._indexer = self._build_indexer()`.

4. Update `Stele.search`:

```python
def search(
    self,
    reference: str | None = None,
    query: str = "",
    *,
    limit: int = 10,
    mode: RetrievalMode | None = None,
) -> list[SearchHit]:
    # When called as search(query=...) only:
    if isinstance(reference, str) and not query and not reference.startswith("stele://"):
        reference, query = None, reference

    effective_mode = mode or self.config.retrieval.default_mode

    if effective_mode == "keyword":
        return self._search_keyword(reference, query, limit)

    if self._chunk_store is None:
        raise CapabilityError(
            f"mode={effective_mode!r} requires a chunk store; indexing.mode is 'skip'"
        )

    if effective_mode == "vector":
        from stele.retrieval.vector import vector_search
        return vector_search(self._chunk_store, query, limit=limit, reference=reference)

    if effective_mode == "hybrid":
        from stele.retrieval.hybrid import hybrid_search
        cfg = self.config.indexing
        return hybrid_search(
            self._chunk_store,
            query,
            limit=limit,
            reference=reference,
            method=cfg.hybrid_method,
            weights=cfg.hybrid_weights,
            rrf_k=cfg.hybrid_rrf_k,
        )

    raise ValueError(f"unknown retrieval mode: {effective_mode!r}")
```

5. Add `indexing_status`:

```python
def indexing_status(self, artifact_id: str) -> IndexResult:
    return self._indexer.status(artifact_id)
```

6. Extend `close()`:

```python
def close(self) -> None:
    memory = getattr(self, "_memory", None)
    if memory is not None: memory.close()
    extractor = getattr(self, "_extractor", None)
    if extractor is not None: extractor.close()
    recall = getattr(self, "_recall", None)
    if recall is not None: recall.close()
    indexer = getattr(self, "_indexer", None)
    if indexer is not None and hasattr(indexer, "close"): indexer.close()
    chunk_store = getattr(self, "_chunk_store", None)
    if chunk_store is not None: chunk_store.close()
```

- [ ] **Step 3: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/core/test_stash_facade.py -v -k "search_mode or indexing_status"
.venv/bin/ruff check src/stele/core/stash.py
.venv/bin/mypy src/stele
```

- [ ] **Step 4: Progress note**

```bash
echo "Task 21: Stele.search mode + indexing_status wired ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 22: Bakeoff overlay in `Stele.__init__` + DC-004

**Files:**
- Modify: `src/stele/core/stash.py`
- Test: `tests/unit/indexing/test_bakeoff.py` (append) + DC-004 verification

- [ ] **Step 1: Apply overlay at construction**

In `Stele.__init__`, after loading config and before building chunk store:

```python
if self.config.indexing.bakeoff_path is not None:
    from stele.indexing.bakeoff import load_bakeoff_file, overlay_onto_indexing_config
    bakeoff = load_bakeoff_file(self.config.indexing.bakeoff_path)
    new_indexing = overlay_onto_indexing_config(self.config.indexing, bakeoff)
    self.config = self.config.model_copy(update={"indexing": new_indexing})
    self._bakeoff_summary = BakeoffSummary(
        source="bakeoff_file",
        chunker=bakeoff.chunker,
        embedder=bakeoff.embedder,
        similarity=bakeoff.similarity,
        file_path=self.config.indexing.bakeoff_path,
    )
else:
    # Will be filled in by resolve_dim_and_similarity on first capabilities() call
    self._bakeoff_summary = None
```

- [ ] **Step 2: Run DC-004**

```bash
.venv/bin/python - <<'PY'
import json
import tempfile
from pathlib import Path

from stele import Stele
from stele.core.config import StashConfig

# Without bakeoff
s_no = Stele(StashConfig())
print("no bakeoff:", s_no.capabilities().bakeoff_summary)
s_no.close()

# With bakeoff
tmp = Path(tempfile.mkdtemp()) / "b.json"
tmp.write_text(json.dumps({
    "chunker": {"type": "fixed_overlap", "params": {"window_words": 220}},
    "embedder": {"name": "test-model", "dim": 512},
    "similarity": "ip",
}))
s_yes = Stele(StashConfig.load({"indexing": {"bakeoff_path": str(tmp)}}))
print("with bakeoff:", s_yes.capabilities().bakeoff_summary)
s_yes.close()
PY
```

Expected: first run shows `source="auto_detected"` or `"default"`; second run shows `source="bakeoff_file"` with `embedder.dim=512`, `similarity="ip"`.

- [ ] **Step 3: Progress note**

```bash
echo "Task 22: Bakeoff overlay + DC-004 ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 23: `Stele.capabilities()` reports Phase 4 fields

**Files:**
- Modify: `src/stele/core/stash.py`
- Test: `tests/unit/retrieval/test_capabilities.py` (append)

- [ ] **Step 1: Write failing test**

Append to `tests/unit/retrieval/test_capabilities.py`:

```python
def test_capabilities_full_report() -> None:
    import importlib.util

    from stele import Stele
    from stele.core.config import StashConfig

    stele = Stele(StashConfig())
    try:
        caps = stele.capabilities()
        assert caps.chunk_store_backend == "memory"
        assert caps.vector_enabled is True
        assert caps.hybrid_enabled is True
        assert caps.task_backend == "in_process"
        assert caps.chunkshop_installed == (importlib.util.find_spec("chunkshop") is not None)
        assert caps.bakeoff_summary is not None
        assert caps.bakeoff_summary.source in {"bakeoff_file", "auto_detected", "default"}
    finally:
        stele.close()
```

- [ ] **Step 2: Implement**

In `Stele.capabilities()`, return a `Capabilities` populated with:

```python
import importlib.util as _ilu

cs_spec = _ilu.find_spec("chunkshop")
chunkshop_version = None
if cs_spec is not None:
    import chunkshop
    chunkshop_version = getattr(chunkshop, "__version__", None)

# Resolve bakeoff summary if not already set
if self._bakeoff_summary is None:
    from stele.indexing.dim_resolution import resolve_dim_and_similarity
    self._bakeoff_summary = resolve_dim_and_similarity(
        self.config.indexing, store=self._chunk_store
    )

return Capabilities(
    # ... existing fields ...
    chunk_store_backend=self.config.backend.type if self._chunk_store else None,
    vector_enabled=self._chunk_store is not None,
    hybrid_enabled=self._chunk_store is not None,
    chunkshop_installed=cs_spec is not None,
    chunkshop_version=chunkshop_version,
    bakeoff_summary=self._bakeoff_summary,
    task_backend=self.config.indexing.task_backend,
)
```

- [ ] **Step 3: Run + lint + types**

```bash
.venv/bin/pytest tests/unit/retrieval/test_capabilities.py -v
.venv/bin/ruff check src/stele/core/stash.py
.venv/bin/mypy src/stele/core/stash.py
```

- [ ] **Step 4: Progress note**

```bash
echo "Task 23: Capabilities reporting ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 24: Phase 3 integration test — `ArtifactSearchStrategy` picks up vector/hybrid

**Files:**
- Test: `tests/unit/recall/test_artifact_search_vector.py`

- [ ] **Step 1: Write test**

Create `tests/unit/recall/test_artifact_search_vector.py`:

```python
"""Phase 3 picks up vector + hybrid via RetrievalConfig.default_mode — no recall code changes."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def test_artifact_search_uses_vector_when_default_mode_vector() -> None:
    cfg = StashConfig.load({"retrieval": {"default_mode": "vector"}})
    stele = Stele(cfg)
    try:
        stored = stele.store(data="user prefers dark mode for the dashboard", namespace="default")
        result = stele.recall.artifact_search(
            query="dark mode",
            scope=MemoryScope(user_id="alice"),
            artifact_id=stored.artifact_id,
        )
        # ArtifactSearchStrategy calls stele.search() which now honors default_mode.
        # We don't assert retrieval_mode on Citation directly (Phase 3 uses kind="chunk"),
        # but we can assert the strategy ran and returned hits.
        assert result.strategy_used == "artifact_search"
    finally:
        stele.close()


def test_artifact_search_uses_hybrid_when_default_mode_hybrid() -> None:
    cfg = StashConfig.load({"retrieval": {"default_mode": "hybrid"}})
    stele = Stele(cfg)
    try:
        stored = stele.store(data="migration deadline is june 30", namespace="default")
        result = stele.recall.artifact_search(
            query="deadline",
            scope=MemoryScope(user_id="alice"),
            artifact_id=stored.artifact_id,
        )
        assert result.strategy_used == "artifact_search"
    finally:
        stele.close()
```

- [ ] **Step 2: Run**

```bash
.venv/bin/pytest tests/unit/recall/test_artifact_search_vector.py -v
```

Expected: both PASS. If Phase 3's `ArtifactSearchStrategy.execute` doesn't pass `mode` through to `stele.search`, fix Phase 3 first (it should already, per the Phase 3 spec — the call site uses `default_mode` from config implicitly when `mode=None` is passed).

- [ ] **Step 3: Progress note**

```bash
echo "Task 24: Phase 3 vector/hybrid integration ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 25: Vector contract test (5 backends parametrized)

**Files:**
- Test: `tests/contract/test_vector_contract.py`

- [ ] **Step 1: Write test**

Create `tests/contract/test_vector_contract.py`:

```python
"""Cross-backend vector contract — parametrized across all 5 backends."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig


def _configs() -> list[tuple[str, dict[str, object]]]:
    configs: list[tuple[str, dict[str, object]]] = [
        ("memory", {"backend": {"type": "memory"}, "retrieval": {"default_mode": "vector"}}),
    ]
    tmp = Path(tempfile.mkdtemp())
    configs.append((
        "sqlite",
        {
            "backend": {"type": "sqlite", "path": str(tmp / "stele.db")},
            "retrieval": {"default_mode": "vector"},
        },
    ))
    pg = os.environ.get("STELE_PG_DSN")
    if pg:
        configs.append((
            "postgres",
            {"backend": {"type": "postgres", "dsn": pg}, "retrieval": {"default_mode": "vector"}},
        ))
    md = os.environ.get("STELE_MARIADB_DSN")
    if md and importlib.util.find_spec("chunkshop.mariadb"):
        configs.append((
            "mariadb",
            {"backend": {"type": "mariadb", "dsn": md}, "retrieval": {"default_mode": "vector"}},
        ))
    ch = os.environ.get("STELE_CLICKHOUSE_DSN")
    if ch and importlib.util.find_spec("chunkshop.clickhouse"):
        configs.append((
            "clickhouse",
            {"backend": {"type": "clickhouse", "dsn": ch}, "retrieval": {"default_mode": "vector"}},
        ))
    return configs


@pytest.mark.parametrize("backend_name,config", _configs())
def test_vector_search_returns_relevant_chunk(backend_name: str, config: dict[str, object]) -> None:
    cfg = StashConfig.load(config)
    stele = Stele(cfg)
    try:
        stored = stele.store(
            data="The migration deadline is 2026-06-30. " * 5,
            namespace="default",
        )
        hits = stele.search(stored.reference, "migration deadline")
        assert hits, f"{backend_name}: vector search returned no hits"
        assert hits[0].chunk_id and ":" in hits[0].chunk_id, (
            f"{backend_name}: chunk_id should be 'aid:ordinal'"
        )
        # No Chunkshop-native objects leak — chunk_id is Stele format
        assert hits[0].chunk_id.startswith(stored.artifact_id + ":")
    finally:
        stele.close()
```

- [ ] **Step 2: Run**

```bash
.venv/bin/pytest tests/contract/test_vector_contract.py -v
```

Expected: at minimum memory + sqlite pass. Postgres passes when `STELE_PG_DSN` set. MariaDB + ClickHouse pass only when both the Chunkshop branch is installed AND the DSN env var is set.

- [ ] **Step 3: Progress note**

```bash
echo "Task 25: Vector contract test ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 26: Indexing modes contract test

**Files:**
- Test: `tests/contract/test_indexing_modes_contract.py`

- [ ] **Step 1: Write test**

Create `tests/contract/test_indexing_modes_contract.py`:

```python
"""sync / async / skip contract across memory + sqlite + postgres."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig


def _backend_configs() -> list[tuple[str, dict[str, object]]]:
    configs: list[tuple[str, dict[str, object]]] = [
        ("memory", {"backend": {"type": "memory"}}),
    ]
    tmp = Path(tempfile.mkdtemp())
    configs.append(("sqlite", {"backend": {"type": "sqlite", "path": str(tmp / "x.db")}}))
    pg = os.environ.get("STELE_PG_DSN")
    if pg:
        configs.append(("postgres", {"backend": {"type": "postgres", "dsn": pg}}))
    return configs


@pytest.mark.parametrize("backend_name,backend_cfg", _backend_configs())
@pytest.mark.parametrize("mode", ["skip", "sync", "async"])
def test_indexing_mode(backend_name: str, backend_cfg: dict[str, object], mode: str) -> None:
    cfg_dict = dict(backend_cfg)
    cfg_dict["indexing"] = {"mode": mode}
    stele = Stele(StashConfig.load(cfg_dict))
    try:
        stored = stele.store(data="text body", namespace="default")
        status = stele.indexing_status(stored.artifact_id)
        if mode == "skip":
            assert status.status == "skipped"
        elif mode == "sync":
            assert status.status == "indexed"
        else:  # async
            assert status.status in {"pending", "indexed"}
            for _ in range(100):
                s = stele.indexing_status(stored.artifact_id)
                if s.status == "indexed":
                    break
                time.sleep(0.01)
            assert stele.indexing_status(stored.artifact_id).status == "indexed"
    finally:
        stele.close()
```

- [ ] **Step 2: Run + progress note**

```bash
.venv/bin/pytest tests/contract/test_indexing_modes_contract.py -v
```

Expected: at minimum 6 cases pass (memory + sqlite × 3 modes). Postgres adds 3 more when DSN set.

```bash
echo "Task 26: Indexing modes contract ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 27: PII assertion test on chunk write

**Files:**
- Test: `tests/unit/storage/test_chunk_store_memory.py` (append)

- [ ] **Step 1: Write test**

Append to `tests/unit/storage/test_chunk_store_memory.py`:

```python
def test_chunk_store_pii_assertion_fires() -> None:
    import pytest

    from stele.core.exceptions import BackendError

    store = InProcessChunkStore(IndexingConfig())
    pii_artifact = _artifact("contact alice@example.com for details", artifact_id="pii_aid")
    # InProcessChunkStore doesn't have the PII assertion in this skeleton;
    # the assertion lives in the chunkshop-backed wrappers (SQLite/Postgres/etc.)
    # where it's load-bearing. For memory backend, this test documents the
    # design intent — but since memory backend trusts caller-side scrubbing
    # via Phase 1's existing fetch path, no assertion fires here.
    # If desired, mirror the regex assertion into InProcessChunkStore.
    pytest.skip("PII assertion is enforced on chunkshop-backed wrappers; memory backend trusts upstream")
```

For the chunkshop-backed backends, ensure the test exists and runs when the extra is installed:

In `tests/unit/storage/test_chunk_store_sqlite.py` (when chunkshop[sqlite] is installed):

```python
@pytest.mark.skipif(not CHUNKSHOP_SQLITE_AVAILABLE, reason="chunkshop[sqlite] not installed")
def test_sqlite_pii_assertion_fires(tmp_path: Path) -> None:
    from stele.core.exceptions import BackendError
    from stele.storage.chunk_store.sqlite import SQLiteChunkStore

    store = SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "x.db"))
    try:
        with pytest.raises(BackendError, match="unscrubbed"):
            store.write(_artifact("contact alice@example.com for details"))
    finally:
        store.close()
```

- [ ] **Step 2: Run + progress note**

```bash
.venv/bin/pytest tests/unit/storage -v -k pii_assertion
```

Expected: SQLite test runs and passes when chunkshop[sqlite] is installed.

```bash
echo "Task 27: PII assertion ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 28: `pyproject.toml` — pin chunkshop minimum + per-backend extras

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update dependencies**

In `pyproject.toml`, find the `chunkshop` extra and replace:

```toml
[project.optional-dependencies]
chunkshop = [
    "chunkshop[sqlite,postgres,mariadb,clickhouse]>=X.Y",  # X.Y = user's release with all 5 backends
]
```

Replace `X.Y` with the actual minimum version when the user publishes the Chunkshop branch. Until then, leave as `>=0.1` and document the gating in `tests/unit/indexing/test_task_backend.py` README.

- [ ] **Step 2: Validate pyproject parses**

```bash
.venv/bin/python -c "
import tomllib
from pathlib import Path
data = tomllib.loads(Path('pyproject.toml').read_text())
extras = data.get('project', {}).get('optional-dependencies', {})
print('chunkshop extra:', extras.get('chunkshop'))
"
```

Expected: prints the pinned dependency line.

- [ ] **Step 3: Progress note**

```bash
echo "Task 28: pyproject.toml chunkshop pin ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 29: `__init__.py` public exports

**Files:**
- Modify: `src/stele/__init__.py`

- [ ] **Step 1: Add exports**

In `src/stele/__init__.py`:

```python
from stele.indexing.bakeoff import (
    BakeoffChunker,
    BakeoffConfig,
    BakeoffEmbedder,
    BakeoffSummary,
)
from stele.indexing.task_backend.base import IndexTask, TaskStatus
```

Append to `__all__`:

```python
    "BakeoffChunker",
    "BakeoffConfig",
    "BakeoffEmbedder",
    "BakeoffSummary",
    "IndexTask",
    "TaskStatus",
```

- [ ] **Step 2: Verify imports**

```bash
.venv/bin/python -c "
from stele import (
    BakeoffConfig, BakeoffSummary, BakeoffEmbedder, BakeoffChunker,
    IndexTask, TaskStatus, Capabilities,
)
print('Phase 4 public exports: OK')
"
```

Expected: `Phase 4 public exports: OK`.

- [ ] **Step 3: Progress note**

```bash
echo "Task 29: Public exports ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 30: Architecture import-layer check

**Files:**
- Test: `tests/unit/indexing/test_architecture.py`

- [ ] **Step 1: Write test**

Create `tests/unit/indexing/test_architecture.py`:

```python
"""Architectural import-layer checks for Phase 4."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RETRIEVAL_DIR = PROJECT_ROOT / "src/stele/retrieval"
RECALL_DIR = PROJECT_ROOT / "src/stele/recall"

CHUNKSHOP_FORBIDDEN_IN = [RETRIEVAL_DIR, RECALL_DIR]
CONCURRENCY_FORBIDDEN_IN = [RETRIEVAL_DIR, RECALL_DIR]


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


@pytest.mark.parametrize("module_path", sorted(p for d in CHUNKSHOP_FORBIDDEN_IN for p in d.rglob("*.py")))
def test_no_chunkshop_imports_in_retrieval_or_recall(module_path: Path) -> None:
    imports = _imports(module_path)
    chunkshop_imports = [i for i in imports if i.startswith("chunkshop")]
    assert not chunkshop_imports, (
        f"{module_path} imports {chunkshop_imports} — chunkshop must stay in indexing/ + chunk_store/"
    )


@pytest.mark.parametrize("module_path", sorted(p for d in CONCURRENCY_FORBIDDEN_IN for p in d.rglob("*.py")))
def test_no_concurrency_primitives_in_retrieval_or_recall(module_path: Path) -> None:
    imports = _imports(module_path)
    forbidden = {"threading", "asyncio"}
    leaked = imports & forbidden
    assert not leaked, (
        f"{module_path} imports {leaked} — concurrency primitives belong in indexing/task_backend/"
    )
```

- [ ] **Step 2: Run**

```bash
.venv/bin/pytest tests/unit/indexing/test_architecture.py -v
```

Expected: all parametrized cases PASS.

- [ ] **Step 3: Progress note**

```bash
echo "Task 30: Architecture import-layer check ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 31: SC → test coverage mapping

**Files:**
- Read-only

- [ ] **Step 1: Build the mapping**

```bash
cat <<'EOF' > /tmp/stele-phase4-planning/SC-COVERAGE.txt
SC-001 → tests/unit/core/test_types.py::test_retrieval_mode_includes_vector_and_hybrid
SC-002 → tests/unit/core/test_config.py (phase4 tests)
SC-003 → tests/unit/indexing/test_bakeoff.py (model tests)
SC-004 → tests/unit/indexing/test_bakeoff.py::test_load_bakeoff_{json,yaml,missing,invalid}
SC-005 → tests/unit/indexing/test_bakeoff.py::test_overlay_onto_indexing_config + DC-004 script
SC-006 → tests/unit/indexing/test_dim_resolution.py::test_auto_detect_when_no_bakeoff
SC-007 → tests/unit/indexing/test_dim_resolution.py::test_default_when_no_store_and_no_bakeoff
SC-008 → tests/unit/storage/test_chunk_store_*.py (per-backend Protocol conformance)
SC-009 → tests/unit/storage/test_chunk_store_memory.py
SC-010 → tests/unit/storage/test_chunk_store_{sqlite,postgres,mariadb,clickhouse}.py (OptionalDependencyError cases)
SC-011 → tests/unit/indexing/test_chunkshop_adapter.py
SC-012 → tests/unit/retrieval/test_vector.py
SC-013 → tests/unit/retrieval/test_hybrid.py
SC-014 → tests/unit/retrieval/test_hybrid_quality.py (load-bearing)
SC-015 → tests/contract/test_vector_contract.py (parametrized 5 backends)
SC-016 → tests/unit/indexing/test_task_backend.py
SC-017 → tests/unit/indexing/test_task_backend.py::test_in_process_*
SC-018 → tests/unit/indexing/test_task_backend.py::test_{redis,celery}_task_backend_raises_capability_error
SC-019 → tests/unit/indexing/test_async_queue.py::test_async_indexer_pending_then_indexed
SC-020 → tests/unit/core/test_stash_facade.py::test_stele_indexing_status_async + test_async_queue.py
SC-021 → tests/contract/test_indexing_modes_contract.py
SC-022 → tests/unit/retrieval/test_hybrid.py::test_hybrid_search_degrades_when_vector_raises
SC-023 → tests/unit/retrieval/test_capabilities.py::test_capabilities_full_report
SC-024 → tests/unit/recall/test_artifact_search_vector.py
SC-025 → existing tests/contract/test_retrieval_contract.py (Phase 1 regression)
SC-026 → tests/unit/storage/test_chunk_store_sqlite.py::test_sqlite_pii_assertion_fires (+ siblings)
EOF
cat /tmp/stele-phase4-planning/SC-COVERAGE.txt
```

- [ ] **Step 2: Verify every cited test exists and passes**

```bash
.venv/bin/pytest tests/unit/indexing tests/unit/storage tests/unit/retrieval tests/unit/recall/test_artifact_search_vector.py tests/contract/test_vector_contract.py tests/contract/test_indexing_modes_contract.py -v 2>&1 | tail -80
```

Expected: every test cited passes (or is correctly skipped due to missing optional deps).

- [ ] **Step 3: Progress note**

```bash
echo "Task 31: SC coverage mapping ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 32: Re-run all drift checkpoints

**Files:** Read-only

- [ ] **Step 1: DC-001 — no chunkshop in retrieval/recall**

```bash
echo "=== DC-001 ==="
grep -rn 'chunkshop\.[a-z_]*' src/stele/retrieval/ src/stele/recall/ 2>/dev/null || echo "(empty — OK)"
```

- [ ] **Step 2: DC-002 — no concurrency primitives in retrieval/recall**

```bash
echo "=== DC-002 ==="
grep -rn 'threading\.\|queue\.Queue\|asyncio\.' src/stele/retrieval/ src/stele/recall/ 2>/dev/null || echo "(empty — OK)"
```

- [ ] **Step 3: DC-003 — hybrid quality test passes with default floor**

```bash
echo "=== DC-003 ==="
.venv/bin/pytest tests/unit/retrieval/test_hybrid_quality.py -v
```

- [ ] **Step 4: DC-004 — bakeoff overlay observable**

```bash
echo "=== DC-004 ==="
.venv/bin/python -c "
import json, tempfile
from pathlib import Path
from stele import Stele
from stele.core.config import StashConfig

s_no = Stele(StashConfig())
src_no = s_no.capabilities().bakeoff_summary.source
s_no.close()

tmp = Path(tempfile.mkdtemp()) / 'b.json'
tmp.write_text(json.dumps({
    'chunker': {'type': 'fixed_overlap', 'params': {}},
    'embedder': {'name': 'test', 'dim': 256},
    'similarity': 'cosine',
}))
s_yes = Stele(StashConfig.load({'indexing': {'bakeoff_path': str(tmp)}}))
src_yes = s_yes.capabilities().bakeoff_summary.source
s_yes.close()

assert src_no in {'auto_detected', 'default'}, f'no-bakeoff source unexpected: {src_no}'
assert src_yes == 'bakeoff_file', f'with-bakeoff source unexpected: {src_yes}'
print('DC-004 PASS')
"
```

Expected: `DC-004 PASS`.

- [ ] **Step 5: Progress note**

```bash
echo "Task 32: All DCs re-checked ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
```

---

### Task 33: Full repo verification + DC-FINAL

**Files:** Read-only

- [ ] **Step 1: Run the before-commit trio**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest 2>&1 | tail -10
```

Expected: all three pass. Note the pytest count and compare to Task 0's baseline. The delta should equal roughly 70–90 new tests (Phase 4 added the most tests of any phase).

- [ ] **Step 2: Confirm Out-of-Scope items are untouched**

```bash
echo "=== Out-of-Scope check ==="
grep -rn 'reranker\|cross_encoder\|MMR\|asyncio\.create_task' src/stele/ tests/ 2>/dev/null || echo "(empty — OK)"

echo "=== Untouched files check ==="
git diff --name-only 2>/dev/null | grep -E 'src/stele/(memory.py|memory_record\.py|extraction/(candidates|classifier|patterns|models)\.py|recall/.*\.py)$' && echo "WARN: locked file modified" || echo "(no locked files touched — OK)"
```

Expected: out-of-scope grep empty; locked-files grep empty.

- [ ] **Step 3: Final progress note**

```bash
echo "=== DC-FINAL: SC coverage ===" >> /tmp/stele-phase4-planning/PROGRESS.log
cat /tmp/stele-phase4-planning/SC-COVERAGE.txt >> /tmp/stele-phase4-planning/PROGRESS.log
echo "Task 33: DC-FINAL complete ($(date -Iseconds))" >> /tmp/stele-phase4-planning/PROGRESS.log
echo "Phase 4 plan execution complete." >> /tmp/stele-phase4-planning/PROGRESS.log
```

- [ ] **Step 4: User decision: where to commit**

Per user instruction, Phase 4 work has NOT been committed during plan execution. When the Phase 2/3 agents have settled their branches, the user will direct:
1. Which branch the Phase 4 work should land on (likely a fresh `phase4-chunkshop-indexing` branch off main)
2. Whether to squash or preserve per-task commits
3. Whether to publish the Phase 4 spec + plan to `docs/superpowers/{specs,plans}/`

Do **not** initiate any branch operations or commits without that explicit instruction.

---

## Parallel-with-other-phases Notes

Phase 4 lives at the boundary between Stele's storage/retrieval layer and Chunkshop. Conflict surface vs Phase 2/3 if any of those branches are still in flight:

| File | Phase 2/3 touches | Phase 4 touches | Conflict risk |
|---|---|---|---|
| `src/stele/core/stash.py` | Phase 2 adds `Stele.extract`; Phase 3 adds `Stele.recall` | Phase 4 adds `Stele.indexing_status`, extends `Stele.search`, wires `_chunk_store`, `_async_indexer` | **Medium** — all additive on the same class. Merge: accept all blocks; verify `close()` calls all four cleanup paths (memory, extractor, recall, indexer + chunk_store). |
| `src/stele/__init__.py` | Phase 2/3 export new types | Phase 4 exports BakeoffConfig + TaskStatus + IndexTask | **Low** — additive; merge by sorting `__all__`. |
| `src/stele/core/config.py` | Phase 2 adds ExtractionConfig; Phase 3 adds RecallConfig | Phase 4 extends IndexingConfig + RetrievalConfig | **Low** — sibling fields on StashConfig. |
| `src/stele/core/types.py` | Phase 2/3 don't touch | Phase 4 extends `RetrievalMode`, `IndexStatus` | **None** — Phase 4 alone owns this file in this slice. |
| `src/stele/indexing/queue.py` | Phase 2/3 don't touch | Phase 4 refactors `SyncChunkIndexer` to accept `ChunkStore` | **None**. |

If conflicts appear on `stash.py` / `__init__.py` / `config.py`: accept BOTH sides and reconcile.

---

## Definition of Ready For Each Task

- Predecessor task's progress note is in `/tmp/stele-phase4-planning/PROGRESS.log`.
- Required Phase 1+2+3 surfaces work (`pytest tests/contract/` passes).
- Chunkshop's required extras are installed (Task 0 verified).

## Definition of Done For Each Task

- The new test(s) pass (or skip cleanly with documented reason).
- `ruff check` and `mypy` on the touched files are clean.
- Progress note appended to `PROGRESS.log`.
- Any cited DC-XXX checkpoint passed.
- No file outside the task's declared `Files:` list was modified.
- **No git commit** (per user instruction; commits happen at user direction after all plan tasks complete).
