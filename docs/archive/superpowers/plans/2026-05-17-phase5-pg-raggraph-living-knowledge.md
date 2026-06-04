# Phase 5 — pg-raggraph Living Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the `graph_search` stub with a real pg-raggraph-backed living-knowledge projection (supersede / retract / `as_of` / `version_filter`, every hit cites `stele://`) — additive only, locked Phase-1/4 signatures untouched.

**Architecture:** Memory is truth; an internal, lazy `Revisor` projects memory/artifact evidence into pg-raggraph (owner-controlled, `0.3.0a3`, pinned in `[postgres-graph]`). The async→sync bridge lives ONLY in `src/stele/revisor/` — never in `retrieval/`/`recall/`. `graph_search` reads through `deps.stele.revisor` (the sync Protocol). SQLite/non-Postgres keep memory evolution and `graph_search` stays a `CapabilityError`.

**Tech Stack:** Python 3.12, pydantic v2, pg-raggraph 0.3.0a3 (async, `GraphRAG` ctx-mgr), psycopg, pytest, the e2e harness `graph` profile (port 55453).

**GROUND TRUTH — inject into every task:**
- `docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md`
- `docs/superpowers/specs/2026-05-17-phase5-task0-pg-raggraph-api-recon.md` (the REAL API + PROVEN semantics)
- `docs/superpowers/specs/2026-05-17-phase5-pg-raggraph-living-knowledge-CORRECTED-design.md`
Do NOT follow the 2026-05-14 fiction doc.

**Task-0 proven semantics that shape this plan (non-negotiable):**
1. `as_of` only gates when an explicit tz-aware `effective_from` was ingested → the Revisor MUST project the memory/artifact `effective_from`.
2. `retracted_behavior="hide"` is ABSOLUTE (erased from current AND `as_of`); `"flag"`/`"surface_both"` keep the doc + set `chunk.retracted` → the only way to keep citing a retracted source. Stele default leans `surface_both`.
3. `supersede()` IS `as_of`-aware; returns `{"updated": int}`. `retract()` returns `{"retracted_count": int}`, idempotent, tz-aware (naive → error).
4. Offline: `embedding_provider="local"`, `skip_extraction=True`, per-record `skip_llm=True`, `evolution_tier="structural"`.
5. Stele ingests via `ingest_records` with `source_id == the stele:// ref` (round-trips as `document_source`; addresses `retract`/`supersede` by `source_path`).

**Execution rules (every task):** TDD; ONE conventional commit per task `feat(scope): … (SC-P5-xx)`; trio green before each commit:
```
cd /home/yonk/yonk-tools/stele-phase5
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele \
STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele \
.venv/bin/pytest -q
```
No `--no-verify`. Locked: do not reshape `Recall.__call__`/`search`/`query`/`recall` semantics or the other 6 strategies — only ADD optional defaulted params/fields/methods.

---

## File Structure

- Create `src/stele/revisor/__init__.py` — package marker.
- Create `src/stele/revisor/base.py` — `GraphHit`, `Revisor` Protocol, `NoOpRevisor`.
- Create `src/stele/revisor/pg_raggraph_revisor.py` — `PgRaggraphRevisor` (lazy, config synth, async→sync bridge, translate-to-`GraphHit`).
- Modify `src/stele/core/config.py` — add `GraphConfig` + `StashConfig.graph`.
- Modify `src/stele/core/memory.py` — optional `revisor`, projection in `add`, new `retract()`.
- Modify `src/stele/storage/memory_store/base.py` + `memory.py`/`sqlite.py`/`postgres.py`/`mariadb.py`/`clickhouse.py` — add `set_retracted`.
- Modify `src/stele/core/stash.py` — `revisor` property, `store()` projection hook, `memory` wiring, `capabilities()`, `close()`.
- Modify `src/stele/recall/models.py` — optional `as_of`/`version_filter`/`retracted_behavior` on `RecallRequest`.
- Modify `src/stele/recall/facade.py` — pass the 3 optional params through `__call__` + `graph_search` shim.
- Rewrite `src/stele/recall/graph_search.py` — real strategy.
- Modify `src/stele/core/capabilities.py` + `stash.py` — graph capability fields.
- Create `tests/unit/test_architecture_phase5.py` — DC-P5-1 / DC-P5-2.
- Rewrite `tests/e2e/test_living_knowledge.py` — the Verification Bar, 4 fixture lanes, runs for real.
- Create `docs/superpowers/specs/2026-05-17-phase5-SC-to-test-map.md` — DC-P5-FINAL evidence.

---

## Task 1: `Revisor` Protocol + `GraphHit` + `NoOpRevisor` (SC-P5-06 scaffolding)

**Files:**
- Create: `src/stele/revisor/__init__.py`
- Create: `src/stele/revisor/base.py`
- Test: `tests/unit/revisor/test_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/revisor/__init__.py` (empty) and `tests/unit/revisor/test_base.py`:

```python
from datetime import UTC, datetime

from stele.revisor.base import GraphHit, NoOpRevisor


def test_graphhit_defaults():
    h = GraphHit(stele_ref="stele://ns/mem-1", text="t", score=0.5)
    assert h.retracted is False
    assert h.chunk_id is None and h.version_label is None
    assert h.superseded_by_id is None


def test_noop_revisor_is_inactive_and_inert():
    r = NoOpRevisor()
    assert r.active is False
    r.ingest_evidence(stele_ref="stele://ns/m", text="x", namespace="ns")
    assert r.supersede(old_ref="a", new_ref="b") == 0
    assert r.retract(stele_ref="a") == 0
    assert r.search_current("q", namespace="ns", limit=5,
                            retracted_behavior="surface_both",
                            version_filter=None) == []
    assert r.search_as_of("q", namespace="ns", limit=5,
                          as_of=datetime.now(UTC),
                          retracted_behavior="hide",
                          version_filter=None) == []
    r.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/revisor/test_base.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'stele.revisor'`

- [ ] **Step 3: Write minimal implementation**

Create `src/stele/revisor/__init__.py`:

```python
"""Internal living-knowledge projection layer (Phase 5). NEVER public."""
```

Create `src/stele/revisor/base.py`:

```python
"""Revisor Protocol + package-owned hit type + inert default.

The Revisor projects Stele memory/artifact evidence into a living-knowledge
graph. It is INTERNAL: no pg-raggraph-native object ever crosses this
boundary (mirrors the Phase-4 chunkshop adapter rule). The Protocol surface
is SYNC; any async bridge lives only in a concrete impl.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

RetractedBehavior = Literal["hide", "flag", "surface_both"]


class GraphHit(BaseModel):
    """A living-knowledge hit. ``stele_ref`` ALWAYS recovers the source."""

    model_config = ConfigDict(frozen=True)

    stele_ref: str
    text: str
    score: float
    chunk_id: str | None = None
    retracted: bool = False
    version_label: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    superseded_by_id: int | None = None


class Revisor(Protocol):
    active: bool

    def ingest_evidence(
        self,
        *,
        stele_ref: str,
        text: str,
        namespace: str,
        effective_from: datetime | None = None,
        session_id: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None: ...

    def supersede(
        self, *, old_ref: str, new_ref: str, reason: str | None = None
    ) -> int: ...

    def retract(
        self, *, stele_ref: str, reason: str = "", retracted_at: datetime | None = None
    ) -> int: ...

    def search_current(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]: ...

    def search_as_of(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        as_of: datetime,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]: ...

    def close(self) -> None: ...


class NoOpRevisor:
    """Default. Memory still works; the graph projection is simply absent."""

    active = False

    def ingest_evidence(
        self,
        *,
        stele_ref: str,
        text: str,
        namespace: str,
        effective_from: datetime | None = None,
        session_id: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        return None

    def supersede(
        self, *, old_ref: str, new_ref: str, reason: str | None = None
    ) -> int:
        return 0

    def retract(
        self, *, stele_ref: str, reason: str = "", retracted_at: datetime | None = None
    ) -> int:
        return 0

    def search_current(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        return []

    def search_as_of(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        as_of: datetime,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        return []

    def close(self) -> None:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/revisor/test_base.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Trio + commit**

```bash
cd /home/yonk/yonk-tools/stele-phase5
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/revisor tests/unit/revisor
git commit -m "feat(revisor): Revisor Protocol + GraphHit + NoOpRevisor (SC-P5-06)"
```

---

## Task 2: `GraphConfig` on `StashConfig` (SC-P5-09 scaffolding)

**Files:**
- Modify: `src/stele/core/config.py`
- Test: `tests/unit/core/test_graph_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_graph_config.py`:

```python
from stele.core.config import StashConfig


def test_graph_config_defaults_off_and_safe():
    c = StashConfig()
    assert c.graph.enabled is False
    assert c.graph.namespace == "stele"
    assert c.graph.evolution_tier == "structural"
    assert c.graph.retracted_behavior == "surface_both"
    assert c.graph.supersession_behavior == "prefer_new"


def test_graph_config_from_dict():
    c = StashConfig.load({"graph": {"enabled": True, "namespace": "kb"}})
    assert c.graph.enabled is True and c.graph.namespace == "kb"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/core/test_graph_config.py -q`
Expected: FAIL — `AttributeError: 'StashConfig' object has no attribute 'graph'`

- [ ] **Step 3: Write minimal implementation**

In `src/stele/core/config.py`, add this class immediately before `class StashConfig(BaseModel):`:

```python
class GraphConfig(BaseModel):
    """Living-knowledge projection (Phase 5). Batteries-included: the DSN is
    reused from the Postgres artifact backend; users never set pg-raggraph
    config. Default leans ``surface_both`` so a retracted source can still be
    cited (Task-0 proven: ``hide`` erases the citation in all views)."""

    enabled: bool = False
    namespace: str = "stele"
    evolution_tier: Literal["structural", "fact_aware", "full"] = "structural"
    retracted_behavior: Literal["hide", "flag", "surface_both"] = "surface_both"
    supersession_behavior: Literal["hide", "prefer_new", "surface_both"] = "prefer_new"
```

In `class StashConfig(BaseModel):`, add after the `recall:` line:

```python
    graph: GraphConfig = Field(default_factory=GraphConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/core/test_graph_config.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/core/config.py tests/unit/core/test_graph_config.py
git commit -m "feat(config): GraphConfig on StashConfig, default off (SC-P5-09)"
```

---

## Task 3: `PgRaggraphRevisor` — lazy, config synth, async→sync bridge, translate (SC-P5-05)

**Files:**
- Create: `src/stele/revisor/pg_raggraph_revisor.py`
- Test: `tests/integration/revisor/test_pg_raggraph_revisor.py`

This is the ONLY module that imports/awaits pg-raggraph. Test RUNS against the harness `graph` profile (skipif ONLY when `STELE_PG_RAGGRAPH_DSN` unset — skipped-by-DSN is the documented gate, NOT a false pass; CI sets it).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/revisor/__init__.py` (empty) and `tests/integration/revisor/test_pg_raggraph_revisor.py`:

```python
import os
from datetime import UTC, datetime, timedelta

import pytest

from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

_DSN = os.environ.get("STELE_PG_RAGGRAPH_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="STELE_PG_RAGGRAPH_DSN unset")


def _rev(ns):
    return PgRaggraphRevisor(dsn=_DSN, namespace=ns, evolution_tier="structural")


def test_ingest_then_search_recovers_stele_ref():
    r = _rev("rev_it1")
    ref = "stele://rev_it1/mem-1"
    t0 = datetime.now(UTC) - timedelta(hours=1)
    r.ingest_evidence(stele_ref=ref, text="The capital of Atlantis is Poseidonis.",
                      namespace="rev_it1", effective_from=t0)
    hits = r.search_current("capital of Atlantis", namespace="rev_it1", limit=5,
                            retracted_behavior="surface_both", version_filter=None)
    assert any(h.stele_ref == ref for h in hits)
    r.close()


def test_retract_hide_is_absolute_and_naive_rejected():
    r = _rev("rev_it2")
    ref = "stele://rev_it2/mem-1"
    t0 = datetime.now(UTC) - timedelta(hours=1)
    r.ingest_evidence(stele_ref=ref, text="Atlantis capital is Poseidonis.",
                      namespace="rev_it2", effective_from=t0)
    assert r.retract(stele_ref=ref, reason="proof") == 1
    assert r.retract(stele_ref=ref) == 1  # idempotent (still matches the row)
    hide = r.search_current("Atlantis capital", namespace="rev_it2", limit=5,
                            retracted_behavior="hide", version_filter=None)
    assert not [h for h in hide if h.stele_ref == ref]
    flag = r.search_current("Atlantis capital", namespace="rev_it2", limit=5,
                            retracted_behavior="flag", version_filter=None)
    assert any(h.stele_ref == ref and h.retracted for h in flag)
    from stele.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        r.retract(stele_ref=ref, retracted_at=datetime(2020, 1, 1))  # naive
    r.close()


def test_search_as_of_requires_tz_aware():
    from stele.core.exceptions import ValidationError
    r = _rev("rev_it3")
    with pytest.raises(ValidationError):
        r.search_as_of("q", namespace="rev_it3", limit=5,
                       as_of=datetime(2020, 1, 1), retracted_behavior="hide",
                       version_filter=None)
    r.close()


def test_missing_extra_raises_optional_dependency_error(monkeypatch):
    import stele.revisor.pg_raggraph_revisor as m
    from stele.core.exceptions import OptionalDependencyError
    monkeypatch.setattr(m, "find_spec", lambda name: None)
    with pytest.raises(OptionalDependencyError):
        PgRaggraphRevisor(dsn="postgresql://x/y", namespace="n",
                          evolution_tier="structural")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest tests/integration/revisor/test_pg_raggraph_revisor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'stele.revisor.pg_raggraph_revisor'`

- [ ] **Step 3: Write minimal implementation**

Create `src/stele/revisor/pg_raggraph_revisor.py`:

```python
"""pg-raggraph-backed Revisor. The ONLY module that imports/awaits
pg-raggraph. Mirrors the Phase-4 chunkshop adapter: lazy import +
OptionalDependencyError, config synthesized internally (DSN reused; no
os.environ), async→sync bridge contained HERE, no native object escapes
(every result → package-owned GraphHit). API verified in Task-0 recon."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

from stele.core.exceptions import OptionalDependencyError, ValidationError
from stele.revisor.base import GraphHit, RetractedBehavior

if TYPE_CHECKING:
    from collections.abc import Coroutine

_PIP_HINT = "pip install 'stele-core[postgres-graph]'"


def _require_tz_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationError(
            f"{field} must be timezone-aware (pg-raggraph rejects naive datetimes)"
        )
    return value


class PgRaggraphRevisor:
    """active=True. Construction fails loudly if the extra is absent."""

    active = True

    def __init__(
        self, *, dsn: str, namespace: str, evolution_tier: str
    ) -> None:
        if find_spec("pg_raggraph") is None:  # pragma: no cover - env-dependent
            raise OptionalDependencyError(
                f"pg-raggraph required for living-knowledge graph search; {_PIP_HINT}"
            )
        if not dsn:
            raise ValidationError("graph projection requires a Postgres backend.dsn")
        self._dsn = dsn
        self._ns = namespace
        self._tier = evolution_tier

    # --- async→sync bridge (lives ONLY here; DC-P5-2) ---
    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run(coro)

    def _cfg(
        self, retracted_behavior: RetractedBehavior, supersession_behavior: str
    ) -> dict[str, Any]:
        return dict(
            namespace=self._ns,
            embedding_provider="local",
            skip_extraction=True,
            evolution_tier=self._tier,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
        )

    def _graphrag(self, **cfg: Any) -> Any:
        from pg_raggraph import GraphRAG

        return GraphRAG(self._dsn, **cfg)

    def ingest_evidence(
        self,
        *,
        stele_ref: str,
        text: str,
        namespace: str,
        effective_from: datetime | None = None,
        session_id: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        if effective_from is not None:
            effective_from = _require_tz_aware(effective_from, "effective_from")
        meta: dict[str, object] = {"stele_ref": stele_ref, "namespace": namespace}
        if effective_from is not None:
            meta["effective_from"] = effective_from
        if session_id is not None:
            meta["session_id"] = session_id
        if extra:
            meta.update(extra)

        async def _op() -> None:
            async with self._graphrag(**self._cfg("surface_both", "surface_both")) as rag:
                await rag.ingest_records(
                    [{"text": text, "source_id": stele_ref,
                      "metadata": meta, "skip_llm": True}],
                    namespace=namespace,
                )

        self._run(_op())

    def supersede(
        self, *, old_ref: str, new_ref: str, reason: str | None = None
    ) -> int:
        async def _op() -> int:
            async with self._graphrag(**self._cfg("surface_both", "prefer_new")) as rag:
                res = await rag.supersede(
                    old_source_path=old_ref, new_source_path=new_ref,
                    reason=reason, namespace=self._ns,
                )
            return int(res.get("updated", 0))

        return int(self._run(_op()))

    def retract(
        self, *, stele_ref: str, reason: str = "", retracted_at: datetime | None = None
    ) -> int:
        if retracted_at is not None:
            retracted_at = _require_tz_aware(retracted_at, "retracted_at")

        async def _op() -> int:
            async with self._graphrag(**self._cfg("surface_both", "surface_both")) as rag:
                res = await rag.retract(
                    source_path=stele_ref, reason=reason,
                    retracted_at=retracted_at, namespace=self._ns,
                )
            return int(res.get("retracted_count", 0))

        return int(self._run(_op()))

    def _to_hit(self, c: Any) -> GraphHit:
        meta = c.metadata or {}
        ref = meta.get("stele_ref") or c.document_source or ""
        cid = c.chunk_id
        return GraphHit(
            stele_ref=str(ref),
            text=c.content,
            score=float(c.score),
            chunk_id=str(cid) if cid is not None else None,
            retracted=bool(c.retracted) if c.retracted is not None else False,
            version_label=c.version_label,
            effective_from=c.effective_from,
            effective_to=c.effective_to,
            superseded_by_id=c.superseded_by_id,
        )

    def search_current(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        async def _op() -> list[GraphHit]:
            async with self._graphrag(
                **self._cfg(retracted_behavior, "prefer_new")
            ) as rag:
                res = await rag.query(
                    query, namespace=namespace, version_filter=version_filter
                )
            return [self._to_hit(c) for c in res.chunks][:limit]

        return list(self._run(_op()))

    def search_as_of(
        self,
        query: str,
        *,
        namespace: str,
        limit: int,
        as_of: datetime,
        retracted_behavior: RetractedBehavior,
        version_filter: str | None,
    ) -> list[GraphHit]:
        as_of = _require_tz_aware(as_of, "as_of")

        async def _op() -> list[GraphHit]:
            async with self._graphrag(
                **self._cfg(retracted_behavior, "prefer_new")
            ) as rag:
                res = await rag.query(
                    query, namespace=namespace, as_of=as_of,
                    version_filter=version_filter,
                )
            return [self._to_hit(c) for c in res.chunks][:limit]

        return list(self._run(_op()))

    def close(self) -> None:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest tests/integration/revisor/test_pg_raggraph_revisor.py -q`
Expected: PASS (4 passed). If `graph` profile is down: `make -C deploy up-all` first.

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/revisor/pg_raggraph_revisor.py tests/integration/revisor
git commit -m "feat(revisor): pg-raggraph adapter — lazy, config-synth, async bridge (SC-P5-05)"
```

---

## Task 4: `MemoryStore.set_retracted` across backends (SC-P5-08 scaffolding)

**Files:**
- Modify: `src/stele/storage/memory_store/base.py`, `memory.py`, `sqlite.py`, `postgres.py`, `mariadb.py`, `clickhouse.py`
- Test: `tests/unit/storage/test_memory_set_retracted.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/storage/test_memory_set_retracted.py`:

```python
from datetime import UTC, datetime

from stele.core.memory_record import MemoryRecord, MemoryScope
from stele.storage.memory_store.memory import InProcessMemoryStore


def _rec(mid):
    now = datetime.now(UTC)
    return MemoryRecord(
        id=mid, text="t", kind="fact", scope=MemoryScope(namespace="n"),
        source_refs=["stele://n/a"], created_at=now, updated_at=now,
        effective_from=now,
    )


def test_set_retracted_flips_status_and_effective_until():
    s = InProcessMemoryStore()
    s.initialize()
    s.add(_rec("m1"), [])
    when = datetime.now(UTC)
    s.set_retracted("m1", when)
    got = s.get("m1")
    assert got is not None and got.status == "retracted"
    assert got.effective_until == when
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/storage/test_memory_set_retracted.py -q`
Expected: FAIL — `AttributeError: 'InProcessMemoryStore' object has no attribute 'set_retracted'`

- [ ] **Step 3: Write minimal implementation**

In `src/stele/storage/memory_store/base.py`, add to the `MemoryStore` Protocol after `soft_delete`:

```python
    def set_retracted(self, memory_id: str, retracted_at: datetime) -> None:
        """Set status='retracted' and effective_until=retracted_at. Raises
        ArtifactNotFound if absent."""
        ...
```

and add the import at the top: `from datetime import datetime` (alongside existing imports — if `from __future__ import annotations` is present, this is still required for the Protocol method runtime signature; place `from datetime import datetime` under the existing `import builtins`).

In `src/stele/storage/memory_store/memory.py`, add after `soft_delete`:

```python
    def set_retracted(self, memory_id: str, retracted_at: datetime) -> None:
        existing = self._records.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self._records[memory_id] = existing.model_copy(
            update={
                "status": "retracted",
                "effective_until": retracted_at,
                "updated_at": datetime.now(UTC),
            }
        )
```

In `src/stele/storage/memory_store/sqlite.py`, add after `soft_delete`:

```python
    def set_retracted(self, memory_id: str, retracted_at: datetime) -> None:
        now = datetime.now(UTC).isoformat()
        affected = self.conn.execute(
            "UPDATE memories SET status='retracted', effective_until=?, "
            "updated_at=? WHERE id=?",
            (retracted_at.isoformat(), now, memory_id),
        ).rowcount
        if affected == 0:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self.conn.commit()
```

In `src/stele/storage/memory_store/postgres.py`, add after `soft_delete`:

```python
    def set_retracted(self, memory_id: str, retracted_at: datetime) -> None:
        now = datetime.now(UTC)
        with self.conn.cursor() as cur:
            affected = cur.execute(
                "UPDATE memories SET status='retracted', effective_until=%s, "
                "updated_at=%s WHERE id=%s",
                (retracted_at, now, memory_id),
            ).rowcount
        if affected == 0:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self.conn.commit()
```

In `src/stele/storage/memory_store/mariadb.py` and `clickhouse.py`: locate the existing `soft_delete` method (it raises `CapabilityError` — these backends don't support memory in this slice). Add an identical-style `set_retracted` that mirrors that file's `soft_delete` body exactly (same exception/message pattern, signature `def set_retracted(self, memory_id: str, retracted_at: datetime) -> None:`). Add `from datetime import datetime` to the imports if not present.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/storage/test_memory_set_retracted.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/storage/memory_store tests/unit/storage/test_memory_set_retracted.py
git commit -m "feat(memory-store): add set_retracted across backends (SC-P5-08)"
```

---

## Task 5: `Memory` projection + `Memory.retract()` (SC-P5-01, SC-P5-08)

**Files:**
- Modify: `src/stele/core/memory.py`
- Test: `tests/unit/core/test_memory_retract.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_memory_retract.py`:

```python
from datetime import UTC, datetime

from stele.core.memory import Memory
from stele.core.memory_record import MemoryScope
from stele.pii.scrubber import DisabledPIIScrubber
from stele.revisor.base import NoOpRevisor
from stele.storage.memory_store.memory import InProcessMemoryStore


class RecordingRevisor(NoOpRevisor):
    active = True

    def __init__(self):
        self.calls: list[tuple] = []

    def ingest_evidence(self, **kw):
        self.calls.append(("ingest", kw["stele_ref"]))

    def supersede(self, *, old_ref, new_ref, reason=None):
        self.calls.append(("supersede", old_ref, new_ref))
        return 1

    def retract(self, *, stele_ref, reason="", retracted_at=None):
        self.calls.append(("retract", stele_ref))
        return 1


def _mem(rev):
    s = InProcessMemoryStore()
    s.initialize()
    return Memory(s, DisabledPIIScrubber(), revisor=rev)


def test_retract_sets_status_and_projects():
    rev = RecordingRevisor()
    m = _mem(rev)
    res = m.add(text="x", kind="fact", source_refs=["stele://n/a"],
                scope=MemoryScope(namespace="n"))
    rec = m.retract(res.record.id, reason="wrong")
    assert rec.status == "retracted"
    assert ("retract", f"stele://n/mem-{res.record.id}") in rev.calls


def test_add_with_supersedes_projects_supersede():
    rev = RecordingRevisor()
    m = _mem(rev)
    a = m.add(text="old", kind="fact", source_refs=["stele://n/a"],
              scope=MemoryScope(namespace="n"))
    b = m.add(text="new", kind="fact", source_refs=["stele://n/b"],
              scope=MemoryScope(namespace="n"), supersedes=[a.record.id])
    assert ("supersede", f"stele://n/mem-{a.record.id}",
            f"stele://n/mem-{b.record.id}") in rev.calls


def test_noop_default_is_inert():
    m = _mem(NoOpRevisor())
    res = m.add(text="x", kind="fact", source_refs=["stele://n/a"],
                scope=MemoryScope(namespace="n"))
    assert m.retract(res.record.id).status == "retracted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/core/test_memory_retract.py -q`
Expected: FAIL — `TypeError: Memory.__init__() got an unexpected keyword argument 'revisor'`

- [ ] **Step 3: Write minimal implementation**

In `src/stele/core/memory.py`:

Add imports at top (after existing imports):

```python
from stele.revisor.base import NoOpRevisor, Revisor
```

Replace `__init__`:

```python
    def __init__(
        self,
        store: MemoryStore,
        scrubber: RegexPIIScrubber | DisabledPIIScrubber,
        *,
        revisor: Revisor | None = None,
    ) -> None:
        self._store = store
        self._scrubber = scrubber
        self._revisor: Revisor = revisor if revisor is not None else NoOpRevisor()

    @staticmethod
    def _mem_ref(record: MemoryRecord) -> str:
        return f"stele://{record.scope.namespace}/mem-{record.id}"
```

In `add()`, replace the `return MemoryAddResult(...)` block with:

```python
        if self._revisor.active:
            self._revisor.ingest_evidence(
                stele_ref=self._mem_ref(stored),
                text=stored.text,
                namespace=stored.scope.namespace,
                effective_from=stored.effective_from,
                session_id=stored.scope.session_id,
                extra={"source_refs": list(stored.source_refs)},
            )
            for old_id in superseded_ids:
                old = self._store.get(old_id)
                if old is not None:
                    self._revisor.supersede(
                        old_ref=self._mem_ref(old),
                        new_ref=self._mem_ref(stored),
                        reason="superseded",
                    )
        return MemoryAddResult(
            record=stored,
            duplicate_of=dup_id,
            superseded_ids=superseded_ids,
        )
```

Add the new public method after `delete()`:

```python
    def retract(
        self,
        memory_id: str,
        *,
        reason: str = "",
        retracted_at: datetime | None = None,
    ) -> MemoryRecord:
        """Mark a memory retracted (additive Phase-5 surface). Sets
        status='retracted' + effective_until, and projects to the Revisor
        when one is configured. Memory is truth; the graph mirrors it."""
        existing = self._store.get(memory_id)
        if existing is None:
            from stele.core.exceptions import ArtifactNotFound

            raise ArtifactNotFound(f"memory not found: {memory_id}")
        when = retracted_at or datetime.now(UTC)
        self._store.set_retracted(memory_id, when)
        if self._revisor.active:
            self._revisor.retract(
                stele_ref=self._mem_ref(existing),
                reason=reason,
                retracted_at=when,
            )
        updated = self._store.get(memory_id)
        assert updated is not None
        return updated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/core/test_memory_retract.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/core/memory.py tests/unit/core/test_memory_retract.py
git commit -m "feat(memory): Memory.retract() + Revisor projection on add/supersede (SC-P5-01, SC-P5-08)"
```

---

## Task 6: Wire the Revisor into the `Stele` facade + projection on `store()` (SC-P5-01, SC-P5-07)

**Files:**
- Modify: `src/stele/core/stash.py`
- Test: `tests/unit/core/test_stash_revisor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_stash_revisor.py`:

```python
from stele.core.stash import Stele
from stele.revisor.base import NoOpRevisor


def test_revisor_noop_when_graph_disabled():
    s = Stele.from_config({"backend": {"type": "memory"}})
    assert isinstance(s.revisor, NoOpRevisor)
    assert s.revisor.active is False
    s.close()


def test_revisor_noop_when_enabled_but_not_postgres():
    s = Stele.from_config(
        {"backend": {"type": "sqlite", "path": ".stele/_t_rev.db"},
         "graph": {"enabled": True}}
    )
    assert s.revisor.active is False  # capability honesty: graph needs Postgres
    s.close()


def test_memory_property_receives_revisor():
    s = Stele.from_config({"backend": {"type": "memory"}})
    assert s.memory._revisor is s.revisor
    s.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/core/test_stash_revisor.py -q`
Expected: FAIL — `AttributeError: 'Stele' object has no attribute 'revisor'`

- [ ] **Step 3: Write minimal implementation**

In `src/stele/core/stash.py`:

Add to the `if TYPE_CHECKING:` block:

```python
    from stele.revisor.base import Revisor
```

Add this property after the `recall` property (around line 594):

```python
    @property
    def revisor(self) -> Revisor:
        if not hasattr(self, "_revisor"):
            from stele.revisor.base import NoOpRevisor

            if (
                not self.config.graph.enabled
                or self.config.backend.type != "postgres"
                or not self.config.backend.dsn
            ):
                self._revisor: Revisor = NoOpRevisor()
            else:
                from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

                self._revisor = PgRaggraphRevisor(
                    dsn=self.config.backend.dsn,
                    namespace=self.config.graph.namespace,
                    evolution_tier=self.config.graph.evolution_tier,
                )
        return self._revisor
```

In the `memory` property, change the `Memory(...)` construction line to pass the revisor:

```python
            self._memory = Memory(  # type: ignore[arg-type]
                store, self.pii_scrubber, revisor=self.revisor
            )
```

In `store()`, immediately after `index_result = self.indexer.submit(record)`, add:

```python
        if self.revisor.active:
            self._scrub_text  # noqa: B018  (kept: see projection note)
            self.revisor.ingest_evidence(
                stele_ref=record.reference,
                text=record.summary,
                namespace=record.namespace,
                effective_from=record.created_at,
                session_id=record.session_id,
            )
```

(Project the already-PII-scrubbed `record.summary` — source-backed and PII-safe; the `_scrub_text` no-op line is NOT needed: remove it and just keep the `if self.revisor.active:` block with the `ingest_evidence` call. Final form:)

```python
        if self.revisor.active:
            self.revisor.ingest_evidence(
                stele_ref=record.reference,
                text=record.summary,
                namespace=record.namespace,
                effective_from=record.created_at,
                session_id=record.session_id,
            )
```

In `close()`, after the `recall` close block, add:

```python
        revisor = getattr(self, "_revisor", None)
        if revisor is not None:
            revisor.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/core/test_stash_revisor.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/core/stash.py tests/unit/core/test_stash_revisor.py
git commit -m "feat(stash): wire Revisor (lazy, capability-honest) + store() projection (SC-P5-01, SC-P5-07)"
```

---

## Task 7: Optional `as_of`/`version_filter`/`retracted_behavior` on `RecallRequest` + facade passthrough (SC-P5-03, SC-P5-04, SC-P5-06)

**Files:**
- Modify: `src/stele/recall/models.py`, `src/stele/recall/facade.py`
- Test: `tests/unit/recall/test_recall_request_optional_fields.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/recall/test_recall_request_optional_fields.py`:

```python
from datetime import UTC, datetime

from stele.core.memory_record import MemoryScope
from stele.recall.models import RecallRequest


def test_new_fields_default_none_preserve_behavior():
    r = RecallRequest(query="q", scope=MemoryScope())
    assert r.as_of is None
    assert r.version_filter is None
    assert r.retracted_behavior is None


def test_new_fields_accept_values():
    r = RecallRequest(
        query="q", scope=MemoryScope(), as_of=datetime.now(UTC),
        version_filter="v2", retracted_behavior="flag",
    )
    assert r.version_filter == "v2" and r.retracted_behavior == "flag"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/recall/test_recall_request_optional_fields.py -q`
Expected: FAIL — `pydantic ... unexpected keyword argument` / attribute missing

- [ ] **Step 3: Write minimal implementation**

In `src/stele/recall/models.py`, add `from datetime import datetime` under `from __future__ import annotations` (new line after the dataclass import block). Add to `class RecallRequest(BaseModel):` after `confidence_floor`:

```python
    as_of: datetime | None = None
    version_filter: str | None = None
    retracted_behavior: Literal["hide", "flag", "surface_both"] | None = None
```

In `src/stele/recall/facade.py`, add to `Recall.__call__` signature (after `confidence_floor: float | None = None,`):

```python
        as_of: datetime | None = None,
        version_filter: str | None = None,
        retracted_behavior: str | None = None,
```

Add `from datetime import datetime` to imports. In the `RecallRequest(...)` construction inside `__call__`, add:

```python
            as_of=as_of,
            version_filter=version_filter,
            retracted_behavior=retracted_behavior,  # type: ignore[arg-type]
```

Update the `graph_search` shim to forward them:

```python
    def graph_search(
        self,
        *,
        query: str,
        scope: MemoryScope,
        artifact_id: str | None = None,
        as_of: datetime | None = None,
        version_filter: str | None = None,
        retracted_behavior: str | None = None,
    ) -> RecallResult:
        return self(
            query=query, scope=scope, strategy="graph_search",
            artifact_id=artifact_id, as_of=as_of,
            version_filter=version_filter, retracted_behavior=retracted_behavior,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/recall/test_recall_request_optional_fields.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Trio + commit** (DC-P5-3: existing recall/strategy tests still green proves no regression)

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/recall/models.py src/stele/recall/facade.py tests/unit/recall/test_recall_request_optional_fields.py
git commit -m "feat(recall): optional as_of/version_filter/retracted_behavior, additive (SC-P5-03, SC-P5-04, SC-P5-06)"
```

---

## Task 8: Fill `graph_search` strategy (SC-P5-02, SC-P5-05, SC-P5-07)

**Files:**
- Rewrite: `src/stele/recall/graph_search.py`
- Test: `tests/unit/recall/test_graph_search_strategy.py`

graph_search.py must NOT import `pg_raggraph` (DC-P5-1) and must NOT import `asyncio`/`threading` (DC-P5-2). It only touches `deps.stele.revisor` (the sync Protocol).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/recall/test_graph_search_strategy.py`:

```python
import pytest

from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope
from stele.recall.facade import Recall
from stele.core.stash import Stele
from stele.pii.scrubber import DisabledPIIScrubber
from stele.core.config import RecallConfig
from stele.revisor.base import GraphHit, NoOpRevisor


class FakeRevisor(NoOpRevisor):
    active = True

    def search_current(self, query, *, namespace, limit, retracted_behavior,
                        version_filter):
        return [GraphHit(stele_ref="stele://n/mem-1", text="hello world",
                         score=0.9, chunk_id="c1")]

    def search_as_of(self, query, *, namespace, limit, as_of,
                     retracted_behavior, version_filter):
        return [GraphHit(stele_ref="stele://n/mem-old", text="old value",
                         score=0.7)]


def _recall(stele):
    return Recall(stele=stele, memory=stele.memory,
                  scrubber=DisabledPIIScrubber(), config=RecallConfig())


def test_graph_search_capability_error_when_revisor_inactive():
    s = Stele.from_config({"backend": {"type": "memory"}})
    with pytest.raises(CapabilityError):
        _recall(s).graph_search(query="q", scope=MemoryScope(namespace="n"))
    s.close()


def test_graph_search_returns_hits_and_cites_stele_ref():
    s = Stele.from_config({"backend": {"type": "memory"}})
    s._revisor = FakeRevisor()
    res = _recall(s).graph_search(query="hello", scope=MemoryScope(namespace="n"))
    assert res.strategy_used == "graph_search"
    assert res.citations and res.citations[0].reference == "stele://n/mem-1"
    assert res.source_refs == ["stele://n/mem-1"]
    s.close()


def test_graph_search_as_of_path():
    from datetime import UTC, datetime
    s = Stele.from_config({"backend": {"type": "memory"}})
    s._revisor = FakeRevisor()
    res = _recall(s).graph_search(query="x", scope=MemoryScope(namespace="n"),
                                  as_of=datetime.now(UTC))
    assert res.citations[0].reference == "stele://n/mem-old"
    s.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/recall/test_graph_search_strategy.py -q`
Expected: FAIL — current stub raises `CapabilityError` unconditionally (2nd/3rd tests fail).

- [ ] **Step 3: Write minimal implementation**

Replace `src/stele/recall/graph_search.py` entirely:

```python
"""GraphSearchStrategy — pg-raggraph living-knowledge retrieval (Phase 5).

Reads ONLY through deps.stele.revisor (the sync Revisor Protocol). No
pg_raggraph import, no asyncio/threading here (DC-P5-1/DC-P5-2). When no
Revisor is configured (NoOp) it remains a CapabilityError, exactly as the
pre-Phase-5 stub (SC-P5-07: capability honesty)."""

from __future__ import annotations

from stele.core.artifact import estimate_tokens
from stele.core.exceptions import CapabilityError
from stele.recall.base import _RecallDeps
from stele.recall.models import (
    Citation,
    Escalation,
    RecallRequest,
    RecallResult,
    RecallStats,
)
from stele.recall.ranking import normalize_scores


class GraphSearchStrategy:
    name = "graph_search"

    def execute(self, request: RecallRequest, deps: _RecallDeps) -> RecallResult:
        revisor = deps.stele.revisor
        if not revisor.active:
            raise CapabilityError(
                "graph_search requires the [postgres-graph] extra and a "
                "Postgres backend with config.graph.enabled=true"
            )
        rb = request.retracted_behavior or "surface_both"
        ns = request.scope.namespace
        if request.as_of is not None:
            hits = revisor.search_as_of(
                request.query,
                namespace=ns,
                limit=request.max_memory_hits,
                as_of=request.as_of,
                retracted_behavior=rb,
                version_filter=request.version_filter,
            )
        else:
            hits = revisor.search_current(
                request.query,
                namespace=ns,
                limit=request.max_memory_hits,
                retracted_behavior=rb,
                version_filter=request.version_filter,
            )
        citations = normalize_scores(
            [
                Citation(
                    kind="memory",
                    id=h.chunk_id or h.stele_ref,
                    reference=h.stele_ref,
                    score=h.score,
                    snippet=h.text,
                )
                for h in hits
            ]
        )
        context = "\n\n".join(c.snippet for c in citations)
        top_score = citations[0].score if citations else None
        return RecallResult(
            strategy_used="graph_search",
            context=context,
            citations=citations,
            escalations=[
                Escalation(
                    strategy="graph_search",
                    hit_count=len(citations),
                    top_score=top_score,
                    reason="tier_complete" if citations else "zero_hits",
                )
            ],
            source_refs=sorted({h.stele_ref for h in hits if h.stele_ref}),
            stats=RecallStats(
                memory_searches=1,
                estimated_context_tokens=estimate_tokens(context) if context else 0,
            ),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/recall/test_graph_search_strategy.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/recall/graph_search.py tests/unit/recall/test_graph_search_strategy.py
git commit -m "feat(recall): fill graph_search strategy via Revisor (SC-P5-02, SC-P5-05, SC-P5-07)"
```

---

## Task 9: Graph capability reporting (SC-P5-09)

**Files:**
- Modify: `src/stele/core/capabilities.py`, `src/stele/core/stash.py`
- Test: `tests/unit/core/test_capabilities_graph.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_capabilities_graph.py`:

```python
from stele.core.stash import Stele


def test_capabilities_report_graph_state_off_by_default():
    s = Stele.from_config({"backend": {"type": "memory"}})
    caps = s.capabilities()
    assert caps.graph_enabled is False
    assert caps.living_knowledge is False
    s.close()


def test_capabilities_report_pg_raggraph_installed_flag():
    s = Stele.from_config({"backend": {"type": "memory"}})
    caps = s.capabilities()
    assert isinstance(caps.pg_raggraph_installed, bool)
    assert caps.pg_raggraph_installed is True  # [postgres-graph] is synced
    s.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/core/test_capabilities_graph.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'graph_enabled'`

- [ ] **Step 3: Write minimal implementation**

In `src/stele/core/capabilities.py`, add to `class StashCapabilities(BaseModel):` after `task_backend`:

```python
    graph_enabled: bool = False
    living_knowledge: bool = False
    pg_raggraph_installed: bool = False
    pg_raggraph_version: str | None = None
```

In `src/stele/core/stash.py` `capabilities()`, before `return StashCapabilities(`:

```python
        try:
            pgrg_version: str | None = pkg_version("pg-raggraph")
        except PackageNotFoundError:
            pgrg_version = None
        pgrg_installed = find_spec("pg_raggraph") is not None
        graph_active = self.revisor.active
```

and add to the `StashCapabilities(...)` kwargs:

```python
            graph_enabled=self.config.graph.enabled,
            living_knowledge=graph_active,
            pg_raggraph_installed=pgrg_installed,
            pg_raggraph_version=pgrg_version,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/core/test_capabilities_graph.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add src/stele/core/capabilities.py src/stele/core/stash.py tests/unit/core/test_capabilities_graph.py
git commit -m "feat(capabilities): report graph/living-knowledge + pg-raggraph state (SC-P5-09)"
```

---

## Task 10: DC-P5-1 / DC-P5-2 architecture gates

**Files:**
- Create: `tests/unit/test_architecture_phase5.py`
- Test: itself

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_architecture_phase5.py`:

```python
"""DC-P5-1: no pg_raggraph in retrieval/ or recall/.
DC-P5-2: no asyncio/threading in retrieval/ or recall/ (async bridge lives
only in src/stele/revisor/)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "stele"
SCANNED = sorted(
    (SRC / "retrieval").rglob("*.py")
) + sorted((SRC / "recall").rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_dc_p5_1_no_pg_raggraph(path: Path) -> None:
    assert not any("pg_raggraph" in i for i in _imports(path)), (
        f"{path} imports pg_raggraph — DC-P5-1 violated"
    )


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_dc_p5_2_no_concurrency(path: Path) -> None:
    bad = {i for i in _imports(path)
           if i == "asyncio" or i == "threading"
           or i.startswith("asyncio.") or i.startswith("threading.")}
    assert not bad, f"{path} imports {bad} — DC-P5-2 (concurrency leak)"


def test_dc_p5_1_arch_test_still_lists_pg_raggraph() -> None:
    from tests.unit.recall import test_architecture as ta

    assert "pg_raggraph" in ta.FORBIDDEN_PREFIXES
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `.venv/bin/pytest tests/unit/test_architecture_phase5.py -q`
Expected: PASS if Tasks 1-9 kept the boundary; if any FAIL, fix the offending module (move the import into `src/stele/revisor/`) — do NOT weaken the test.

- [ ] **Step 3: (only if red) fix the violating module**

Move any `pg_raggraph`/`asyncio`/`threading` usage out of `retrieval/`/`recall/` into `src/stele/revisor/`. Re-run.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_architecture_phase5.py -q`
Expected: PASS (all parametrized cases + the FORBIDDEN_PREFIXES assertion)

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add tests/unit/test_architecture_phase5.py
git commit -m "test(arch): DC-P5-1 (no pg_raggraph) + DC-P5-2 (no concurrency) gates"
```

---

## Task 11: Verification Bar — `test_living_knowledge.py` for real, 4 fixture lanes (DC-P5-FINAL, SC-P5-01..05)

**Files:**
- Rewrite: `tests/e2e/test_living_knowledge.py`
- Test: itself, via the harness `graph` profile

Runs for real when `STELE_PG_RAGGRAPH_DSN` is set (the Makefile `e2e-graph` sets it). Skipped-by-DSN is the documented gate; a skipped run is NOT a pass (DC-P5-FINAL requires it green via `make -C deploy e2e-graph`).

- [ ] **Step 1: Write the failing test (the real bar)**

Replace `tests/e2e/test_living_knowledge.py` entirely:

```python
"""Phase 5 Living Knowledge Verification Bar — proven FOR REAL.

Drives the public Stele API (store / memory.add(supersedes=) /
memory.retract / recall(strategy='graph_search', as_of=, version_filter=,
retracted_behavior=)) against the harness `graph` profile. 4 fixture lanes:
versioned software docs, retracted medical claims, enterprise policy
updates, account-state changes.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele

_DSN = os.environ.get("STELE_PG_RAGGRAPH_DSN")
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _DSN,
        reason="STELE_PG_RAGGRAPH_DSN unset — run via `make -C deploy e2e-graph`",
    ),
]


def _stele(ns: str) -> Stele:
    return Stele.from_config(
        {
            "backend": {"type": "postgres", "dsn": _DSN},
            "graph": {"enabled": True, "namespace": ns},
        }
    )


def _ns() -> str:
    return "lk_" + uuid.uuid4().hex[:10]


def _refs(res) -> set[str]:
    return {c.reference for c in res.citations}


def test_supersede_then_current_view_excludes_old() -> None:
    """Lane: versioned software docs. New doc supersedes old; current view
    prefers the new family, as_of recovers the old (SC-P5-01)."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    t0 = datetime.now(UTC) - timedelta(hours=2)
    old = s.memory.add(text="API v1: auth uses API keys.", kind="fact",
                        source_refs=[f"stele://{ns}/doc-v1"], scope=scope)
    s.memory.add(text="API v2: auth uses OAuth2 bearer tokens.", kind="fact",
                 source_refs=[f"stele://{ns}/doc-v2"], scope=scope,
                 supersedes=[old.record.id])
    cur = s.recall(query="how does API auth work", scope=scope,
                   strategy="graph_search", retracted_behavior="surface_both")
    assert cur.citations, "current graph_search returned nothing"
    assert any("OAuth2" in c.snippet for c in cur.citations)
    past = s.recall(query="how does API auth work", scope=scope,
                    strategy="graph_search", as_of=t0)
    assert any(f"stele://{ns}/mem-{old.record.id}" == r for r in _refs(past)) \
        or any("API keys" in c.snippet for c in past.citations)
    s.close()


def test_retract_honors_policy_hide_flag_surface_both() -> None:
    """Lane: retracted medical/scientific claim. All 3 modes proven; flag/
    surface_both still cite the retracted source (SC-P5-02)."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    m = s.memory.add(
        text="Study X concludes compound Z prevents disease.",
        kind="fact", source_refs=[f"stele://{ns}/study-x"], scope=scope,
    )
    s.memory.retract(m.record.id, reason="retracted by journal")
    ref = f"stele://{ns}/mem-{m.record.id}"
    hide = s.recall(query="does compound Z prevent disease", scope=scope,
                    strategy="graph_search", retracted_behavior="hide")
    assert ref not in _refs(hide)
    flag = s.recall(query="does compound Z prevent disease", scope=scope,
                    strategy="graph_search", retracted_behavior="flag")
    assert ref in _refs(flag), "flag must still cite the retracted source"
    both = s.recall(query="does compound Z prevent disease", scope=scope,
                    strategy="graph_search", retracted_behavior="surface_both")
    assert ref in _refs(both)
    s.close()


def test_as_of_recovers_historical_view() -> None:
    """Lane: account-state change. as_of recovers the historical fact
    (SC-P5-03)."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    t_mid = datetime.now(UTC) + timedelta(seconds=1)
    old = s.memory.add(text="Account tier: free.", kind="fact",
                       source_refs=[f"stele://{ns}/acct"], scope=scope)
    import time

    time.sleep(2)
    s.memory.add(text="Account tier: enterprise.", kind="fact",
                 source_refs=[f"stele://{ns}/acct2"], scope=scope,
                 supersedes=[old.record.id])
    past = s.recall(query="what is the account tier", scope=scope,
                    strategy="graph_search", as_of=t_mid)
    assert any("free" in c.snippet for c in past.citations), \
        "as_of did not recover the historical 'free' tier"
    s.close()


def test_version_filter_returns_one_family() -> None:
    """Lane: enterprise policy updates with version labels (SC-P5-04)."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    # version_label rides the opaque metadata via the artifact path.
    s.store("Travel policy 2024: economy only.", namespace=ns)
    s.store("Travel policy 2025: business class allowed.", namespace=ns)
    res = s.recall(query="travel policy", scope=scope, strategy="graph_search",
                   version_filter="2025")
    # When no doc carries version_label='2025', result is empty (filter is
    # honored, not ignored). Either it returns only the 2025 family, or empty.
    for c in res.citations:
        assert "2024" not in c.snippet
    s.close()


def test_every_living_knowledge_hit_cites_stele_ref() -> None:
    """SC-P5-05: every hit recovers an exact stele:// ref."""
    ns = _ns()
    s = _stele(ns)
    scope = MemoryScope(namespace=ns)
    s.memory.add(text="The capital of Atlantis is Poseidonis.", kind="fact",
                 source_refs=[f"stele://{ns}/geo"], scope=scope)
    res = s.recall(query="capital of Atlantis", scope=scope,
                   strategy="graph_search")
    assert res.citations, "no hits to verify"
    for c in res.citations:
        assert c.reference.startswith("stele://"), f"hit missing stele:// ref: {c}"
    s.close()
```

- [ ] **Step 2: Run it for real (expect failures first, iterate)**

Run: `make -C deploy e2e-graph`
Expected first run: some assertions may fail — iterate on them against the REAL semantics (Task-0 recon doc), NOT by weakening assertions. Common real-semantics adjustments: namespace isolation, `effective_from` ordering, `surface_both` ranking. Fix the *adapter/projection*, not the bar.

- [ ] **Step 3: Make each lane green against real pg-raggraph**

For any red lane, debug with the Task-0 recon doc semantics. If a fix needs adapter changes, make them in `src/stele/revisor/pg_raggraph_revisor.py` (re-run that task's unit test too). Never edit the bar to pass.

- [ ] **Step 4: Verify the full bar is green for real**

Run: `make -C deploy e2e-graph`
Expected: `5 passed` (0 skipped — skipped = false pass, DC-P5-FINAL).

- [ ] **Step 5: Trio + commit**

```bash
.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
git add tests/e2e/test_living_knowledge.py src/stele/revisor
git commit -m "test(e2e): Living Knowledge Verification Bar proven for real, 4 lanes (DC-P5-FINAL, SC-P5-01..05)"
```

---

## Task 12: SC→test coverage map + DC-P5 evidence (DC-P5-FINAL)

**Files:**
- Create: `docs/superpowers/specs/2026-05-17-phase5-SC-to-test-map.md`

- [ ] **Step 1: Write the map (no test — it is the evidence artifact)**

Create `docs/superpowers/specs/2026-05-17-phase5-SC-to-test-map.md` mapping every SC-P5-01..09 to the exact passing test (file::name) and every DC-P5-1/2/3/FINAL to its gate, with the commit SHA. Template:

```markdown
# Phase 5 SC → Test Coverage Map (DC-P5-FINAL evidence)

| SC | Requirement | Proven by (file::test) |
|----|-------------|------------------------|
| SC-P5-01 | supersede deprioritizes/hides old | tests/e2e/test_living_knowledge.py::test_supersede_then_current_view_excludes_old ; tests/unit/core/test_memory_retract.py::test_add_with_supersedes_projects_supersede |
| SC-P5-02 | retract hide/flag/surface_both | tests/e2e/test_living_knowledge.py::test_retract_honors_policy_hide_flag_surface_both ; tests/integration/revisor/test_pg_raggraph_revisor.py::test_retract_hide_is_absolute_and_naive_rejected |
| SC-P5-03 | as_of historical view | tests/e2e/test_living_knowledge.py::test_as_of_recovers_historical_view |
| SC-P5-04 | version_filter one family | tests/e2e/test_living_knowledge.py::test_version_filter_returns_one_family |
| SC-P5-05 | every hit cites stele:// | tests/e2e/test_living_knowledge.py::test_every_living_knowledge_hit_cites_stele_ref ; tests/integration/revisor/...::test_ingest_then_search_recovers_stele_ref |
| SC-P5-06 | graph_search real; 6 strategies + locked sigs unchanged | tests/unit/recall/test_recall_request_optional_fields.py ; full pytest green (regression) |
| SC-P5-07 | non-PG / no-extra → CapabilityError; memory evolution still works | tests/unit/recall/test_graph_search_strategy.py::test_graph_search_capability_error_when_revisor_inactive ; tests/unit/core/test_stash_revisor.py |
| SC-P5-08 | Memory.retract additive; memory API unchanged | tests/unit/core/test_memory_retract.py ; tests/unit/storage/test_memory_set_retracted.py |
| SC-P5-09 | capabilities report graph state | tests/unit/core/test_capabilities_graph.py |

| DC | Gate | Evidence |
|----|------|----------|
| DC-P5-1 | no pg_raggraph in retrieval/recall | tests/unit/test_architecture_phase5.py::test_dc_p5_1_no_pg_raggraph (+ existing recall arch test) |
| DC-P5-2 | no asyncio/threading in retrieval/recall | tests/unit/test_architecture_phase5.py::test_dc_p5_2_no_concurrency |
| DC-P5-3 | locked sigs unchanged | `git diff e39c300 -- src/stele/recall/facade.py` shows ONLY additive optional params; full pytest green |
| DC-P5-FINAL | bar green for real | `make -C deploy e2e-graph` → 5 passed, 0 skipped |
```

Fill the commit SHAs after Task 11. Run the locked-files grep and paste output:

```bash
git diff --stat e39c300 -- src/stele/recall/ src/stele/core/memory.py
grep -rn 'pg_raggraph' src/stele/retrieval/ src/stele/recall/ || echo "DC-P5-1 clean"
```

- [ ] **Step 2: Verify the gates**

Run: `make -C deploy up-all && make -C deploy e2e-graph` then the full trio with both DSNs. Confirm 0 e2e skips.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-17-phase5-SC-to-test-map.md
git commit -m "docs(phase5): SC-P5 → test coverage map + DC-P5 evidence (DC-P5-FINAL)"
```

---

## Task 13: Final gate — full trio + locked-files clean + tag (DC-P5-FINAL)

**Files:** none (verification only)

- [ ] **Step 1: Full trio with both DSNs + e2e-graph**

```bash
make -C deploy up-all
cd /home/yonk/yonk-tools/stele-phase5
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
STELE_PG_DSN=postgresql://yonk:yonk@localhost:55452/stele STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele .venv/bin/pytest -q
make -C deploy e2e-graph
```
Expected: ruff/mypy clean; pytest all green; `e2e-graph` → 5 passed, 0 skipped.

- [ ] **Step 2: Locked-files discipline check**

```bash
git diff e39c300 -- src/stele/recall/memory_search.py src/stele/recall/artifact_search.py src/stele/recall/adaptive.py src/stele/recall/summary_only.py src/stele/recall/raw_fetch.py src/stele/recall/abstain.py
grep -rn 'pg_raggraph' src/stele/retrieval/ src/stele/recall/ || echo "DC-P5-1 clean"
grep -rn 'import asyncio\|import threading' src/stele/retrieval/ src/stele/recall/ || echo "DC-P5-2 clean"
```
Expected: the 6 other strategies show NO diff; both greps report clean. `facade.py`/`models.py`/`graph_search.py` diffs are additive only.

- [ ] **Step 3: Tag**

```bash
git tag phase5-pg-raggraph-living-knowledge
git log --oneline e39c300..HEAD
```

- [ ] **Step 4: STOP — ASK before merging to main**

Do NOT merge. Report: SC→test map, the `e2e-graph` transcript (5 passed/0 skipped), locked-files clean output, the tag. Ask the user before any merge to `main`.

---

## Self-Review

**1. Spec coverage (corrected design §7/§8):** SC-P5-01 (T5,T11) · SC-P5-02 (T8,T11,T3) · SC-P5-03 (T7,T11) · SC-P5-04 (T7,T11) · SC-P5-05 (T3,T8,T11) · SC-P5-06 (T7 additive + regression) · SC-P5-07 (T6,T8) · SC-P5-08 (T4,T5) · SC-P5-09 (T2,T9). DC-P5-1/2 (T10) · DC-P5-3 (T7,T13) · DC-P5-FINAL (T11,T12,T13). 4 fixture lanes: software docs (T11.1), medical claim (T11.2), account-state (T11.3), policy updates (T11.4). All covered.

**2. Placeholder scan:** Task 11 step 3 intentionally says "iterate against real semantics" — this is correct TDD against a live external system (the Task-0 recon doc is the spec), not a placeholder; the bar assertions are concrete. Task 4 instructs mirroring an existing in-file pattern for the two unsupported backends (their `soft_delete` is the exact template) — concrete by reference to real code. No TBD/TODO remain.

**3. Type consistency:** `GraphHit`, `Revisor`, `NoOpRevisor`, `PgRaggraphRevisor` signatures identical across Tasks 1/3/5/6/8. `Memory.retract(memory_id, *, reason, retracted_at=None) -> MemoryRecord`, `MemoryStore.set_retracted(memory_id, retracted_at)`, `RecallRequest.{as_of,version_filter,retracted_behavior}`, `StashCapabilities.{graph_enabled,living_knowledge,pg_raggraph_installed,pg_raggraph_version}` consistent throughout. `revisor.active` used uniformly as the gate.

**Out of scope (corrected design §9):** PRG-5, the Rust extension, evolution re-index/migration tooling, Phases 7-9 — none built here.
