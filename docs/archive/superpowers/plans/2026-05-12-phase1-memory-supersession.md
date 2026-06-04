# Stele Phase 1: Memory-Level Supersession Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Stele's memory layer with real supersession and `as_of` plumbing on the SQLite and Postgres backends, so the "living knowledge" headline has evidence-bound code at the data layer instead of marketing language.

**Architecture:** Add a `MemoryStore` plugin contract parallel to the existing `StorageBackend`. Implement it on memory + sqlite + postgres; stub it on mariadb + clickhouse to raise `CapabilityError`. Expose via a new `Memory` facade and `Stele.memory` property. No changes to the existing `Artifact` / `StorageBackend` / `RetrievalBackend` protocols.

**Tech Stack:** Python 3.12+, Pydantic v2, sqlite3 (stdlib) with FTS5, psycopg v3 with tsvector, pytest, ruff, mypy strict, uv-managed venv.

**Mission Brief (load-bearing):** [`skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md`](../../../skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md)

Re-read the brief at every DC-XXX checkpoint below. All 11 success criteria (SC-001 through SC-011) must have evidence at DC-FINAL.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/stele/core/memory_record.py` | `MemoryRecord`, `MemoryScope`, `MemoryQuery`, `MemoryAddResult`, enums |
| `src/stele/core/memory.py` | `Memory` facade — PII scrubbing, dispatch to `MemoryStore` |
| `src/stele/storage/memory_store/__init__.py` | Package marker |
| `src/stele/storage/memory_store/base.py` | `MemoryStore` Protocol |
| `src/stele/storage/memory_store/memory.py` | In-process dict-backed store |
| `src/stele/storage/memory_store/sqlite.py` | SQLite store with FTS5 |
| `src/stele/storage/memory_store/postgres.py` | Postgres store with tsvector |
| `src/stele/storage/memory_store/mariadb.py` | Stub raising `CapabilityError` |
| `src/stele/storage/memory_store/clickhouse.py` | Stub raising `CapabilityError` |
| `tests/unit/core/test_memory_record.py` | Model validation, source_refs check (SC-010) |
| `tests/unit/core/test_memory_facade.py` | `Memory` facade + `Stele.memory` |
| `tests/unit/core/test_memory_add.py` | add + supersession atomicity (SC-002) |
| `tests/unit/core/test_memory_search.py` | default / as_of / include_superseded (SC-003) |
| `tests/unit/core/test_memory_update.py` | text-edit rejected (SC-004) |
| `tests/unit/core/test_memory_delete.py` | soft delete (SC-005) |
| `tests/unit/core/test_memory_duplicates.py` | duplicate detection (SC-006) |
| `tests/unit/storage/__init__.py` | Package marker |
| `tests/unit/storage/test_memory_schema.py` | SQLite schema migration (SC-001) |
| `tests/unit/pii/test_memory_scrubbing.py` | PII scrub on memory text (SC-009) |
| `tests/unit/test_architecture.py` | Import-layer check (SC-011) |
| `tests/contract/test_memory_contract.py` | Cross-backend contract (SC-008) |
| `scripts/demo-supersession.sh` | Human-readable supersession demo |

### Modified files

| Path | Change |
|---|---|
| `src/stele/__init__.py` | Export `Memory`, `MemoryRecord`, `MemoryScope`, `MemoryQuery`, `ValidationError` |
| `src/stele/core/stash.py` | Add `Stele.memory` property |
| `src/stele/core/exceptions.py` | Add `ValidationError` class |
| `benchmarks/longrun.py` | Convert 4 temporal scenarios + `SUPERSESSION_ENABLED` flag |

---

## Drift Checkpoints (hard gates from mission brief)

- ⛔ **DC-001** (after Task 5): re-read brief → verify the artifact table was NOT modified
- ⛔ **DC-002** (after Task 15): re-read brief → `grep -rn 'pg_raggraph\|pg-raggraph\|chunkshop\|MemoryExtractor' src/stele/core/memory*.py src/stele/storage/memory_store/` must be empty
- ⛔ **DC-003** (after Task 19): run longrun with `SUPERSESSION_ENABLED=False` → the 4 temporal scenarios MUST fail; if they pass, the test isn't testing supersession
- ⛔ **DC-FINAL** (Task 21): every SC-001..SC-011 has a passing test cited; Out-of-Scope list verified untouched

---

## Tasks

### Task 0: Initialize git repository

The `.git/` directory exists but is empty. Get version control working before any code touches the repo.

**Files:**
- Modify: `.git/` (initialize)

- [ ] **Step 1: Initialize repo and stage current tree**

```bash
cd /home/yonk/yonk-tools/stele
rm -rf .git
git init -b main
git add -A
git status --short | head -20
```

Expected: long list of staged files including `src/stele/`, `docs/`, `tests/`, `pyproject.toml`, etc.

- [ ] **Step 2: Baseline commit**

```bash
git commit -m "chore: baseline Stele repo after rename from yonk-memory-stash

Renamed package, references (stash:// -> stele://), env vars, scripts,
docker container names. Tests pass: ruff/mypy/pytest (45 passed).
Mission brief locked at skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md."
git log --oneline
```

Expected: one commit on `main`.

---

### Task 1: Define `ValidationError`

`exceptions.py` doesn't have it yet; needed for SC-010 source_refs rejection.

**Files:**
- Modify: `src/stele/core/exceptions.py`
- Test: `tests/unit/core/test_memory_record.py` (created next task)

- [ ] **Step 1: Add the exception class**

In `src/stele/core/exceptions.py`, append after `class IndexingError(SteleError)`:

```python


class ValidationError(SteleError):
    """Input failed validation before any backend call."""
```

- [ ] **Step 2: Verify mypy and ruff still clean**

```bash
.venv/bin/ruff check src/stele/core/exceptions.py
.venv/bin/mypy src/stele/core/exceptions.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/stele/core/exceptions.py
git commit -m "feat(exceptions): add ValidationError for pre-backend input checks"
```

---

### Task 2: `MemoryRecord` data model

The single source of truth for memory shape. SC-001 + SC-010 anchored here.

**Files:**
- Create: `src/stele/core/memory_record.py`
- Test: `tests/unit/core/test_memory_record.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/core/test_memory_record.py`:

```python
"""Tests for MemoryRecord model (SC-010 source_refs validation)."""

from datetime import UTC, datetime

import pytest

from stele.core.memory_record import (
    MemoryRecord,
    MemoryScope,
    canonical_scope_key,
    memory_text_hash,
)
from stele.core.exceptions import ValidationError


def _record(**overrides):
    base = dict(
        id="m1",
        text="user prefers Helix editor",
        kind="preference",
        scope=MemoryScope(user_id="alice"),
        source_refs=["stele://default/abc"],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return MemoryRecord(**base)


def test_memory_record_defaults_active_no_expiry():
    r = _record()
    assert r.status == "active"
    assert r.effective_until is None
    assert r.supersedes == []
    assert r.confidence == 1.0


def test_memory_record_rejects_empty_source_refs():
    with pytest.raises(ValidationError) as exc:
        _record(source_refs=[])
    assert "stele://" in str(exc.value)


def test_memory_record_rejects_non_stele_source_ref():
    with pytest.raises(ValidationError) as exc:
        _record(source_refs=["https://example.com/doc"])
    assert "stele://" in str(exc.value)


def test_memory_record_accepts_multiple_source_refs():
    r = _record(source_refs=["stele://ns/a", "stele://ns/b"])
    assert len(r.source_refs) == 2


def test_canonical_scope_key_is_stable():
    s1 = MemoryScope(user_id="alice", namespace="default")
    s2 = MemoryScope(namespace="default", user_id="alice")
    assert canonical_scope_key(s1) == canonical_scope_key(s2)


def test_memory_text_hash_differs_on_text_or_scope_change():
    s = MemoryScope(user_id="alice")
    h1 = memory_text_hash("hello", s)
    h2 = memory_text_hash("hello", MemoryScope(user_id="bob"))
    h3 = memory_text_hash("hi", s)
    assert h1 != h2
    assert h1 != h3
```

- [ ] **Step 2: Run test, verify failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_record.py -v
```

Expected: all FAIL with `ModuleNotFoundError: No module named 'stele.core.memory_record'`.

- [ ] **Step 3: Implement the model**

Create `src/stele/core/memory_record.py`:

```python
"""Memory record model — the single source of truth for memory shape."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from stele.core.exceptions import ValidationError

MemoryKind = Literal[
    "fact",
    "preference",
    "decision",
    "instruction",
    "commitment",
    "issue",
    "summary",
]

MemoryStatus = Literal[
    "active",
    "superseded",
    "retracted",
    "disputed",
    "deleted",
]


class MemoryScope(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str | None = None
    agent_id: str | None = None
    app_id: str | None = None
    session_id: str | None = None
    namespace: str = "default"


class MemoryRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    text: str
    kind: MemoryKind
    scope: MemoryScope
    source_refs: list[str]
    source_chunk_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    status: MemoryStatus = "active"
    supersedes: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    effective_from: datetime
    effective_until: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    pii_flags: list[str] = Field(default_factory=list)

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValidationError(
                "every memory must cite at least one stele:// source_ref"
            )
        for ref in v:
            if not ref.startswith("stele://"):
                raise ValidationError(
                    f"source_refs entries must be stele:// URIs, got {ref!r}"
                )
        return v


class MemoryQuery(BaseModel):
    query: str
    scope: MemoryScope
    as_of: datetime | None = None
    include_superseded: bool = False
    limit: int = 10


class MemoryAddResult(BaseModel):
    record: MemoryRecord
    duplicate_of: str | None = None
    superseded_ids: list[str] = Field(default_factory=list)


def canonical_scope_key(scope: MemoryScope) -> str:
    """Stable string for scope used in hashing."""
    return json.dumps(scope.model_dump(), sort_keys=True, separators=(",", ":"))


def memory_text_hash(text: str, scope: MemoryScope) -> str:
    """sha256(text || canonical(scope)) for duplicate detection."""
    payload = text.encode("utf-8") + b"|" + canonical_scope_key(scope).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/unit/core/test_memory_record.py -v
.venv/bin/ruff check src/stele/core/memory_record.py tests/unit/core/test_memory_record.py
.venv/bin/mypy src/stele/core/memory_record.py
```

Expected: 6 passed, ruff clean, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/memory_record.py tests/unit/core/test_memory_record.py
git commit -m "feat(memory): MemoryRecord model with source_refs validation (SC-010)"
```

---

### Task 3: `MemoryStore` Protocol

The plugin contract — defines what every backend memory store must implement. SC-011 anchored here (Memory layer is separate from existing StorageBackend).

**Files:**
- Create: `src/stele/storage/memory_store/__init__.py`
- Create: `src/stele/storage/memory_store/base.py`

- [ ] **Step 1: Create the package and protocol**

Create `src/stele/storage/memory_store/__init__.py`:

```python
"""Memory store plugin contract and per-backend implementations."""
```

Create `src/stele/storage/memory_store/base.py`:

```python
"""MemoryStore Protocol — the per-backend contract."""

from __future__ import annotations

from typing import Protocol

from stele.core.memory_record import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
)


class MemoryStore(Protocol):
    def initialize(self) -> None: ...

    def add(
        self,
        record: MemoryRecord,
        supersedes: list[str],
    ) -> tuple[MemoryRecord, list[str]]:
        """Insert record. If supersedes is non-empty, mark those memories
        superseded in the same transaction. Returns (stored_record,
        actually_superseded_ids)."""
        ...

    def search(self, query: MemoryQuery) -> list[MemoryRecord]: ...

    def list(
        self,
        scope: MemoryScope,
        status_filter: list[MemoryStatus] | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]: ...

    def get(self, memory_id: str) -> MemoryRecord | None: ...

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord: ...

    def soft_delete(self, memory_id: str) -> None: ...

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        """Return existing memory_id with matching (scope, text_hash) or None."""
        ...

    def close(self) -> None: ...
```

- [ ] **Step 2: Verify ruff and mypy**

```bash
.venv/bin/ruff check src/stele/storage/memory_store/
.venv/bin/mypy src/stele/storage/memory_store/
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/stele/storage/memory_store/
git commit -m "feat(memory): MemoryStore protocol (SC-011 layered architecture)"
```

---

### Task 4: In-process `MemoryStore` (memory backend)

The simplest implementation — dict-backed. Validates the protocol shape before SQLite.

**Files:**
- Create: `src/stele/storage/memory_store/memory.py`
- Test: covered by contract test in Task 17, smoke-tested here

- [ ] **Step 1: Implement the in-process store**

Create `src/stele/storage/memory_store/memory.py`:

```python
"""In-process MemoryStore — dict-backed, for tests and the memory backend."""

from __future__ import annotations

from datetime import UTC, datetime

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    canonical_scope_key,
    memory_text_hash,
)


def _scope_matches(record_scope: MemoryScope, query_scope: MemoryScope) -> bool:
    for field in ("user_id", "agent_id", "app_id", "session_id"):
        q = getattr(query_scope, field)
        if q is not None and getattr(record_scope, field) != q:
            return False
    return record_scope.namespace == query_scope.namespace


def _is_valid_at(record: MemoryRecord, when: datetime) -> bool:
    if record.effective_from > when:
        return False
    if record.effective_until is not None and record.effective_until <= when:
        return False
    return True


class InProcessMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def initialize(self) -> None:
        return None

    def add(
        self,
        record: MemoryRecord,
        supersedes: list[str],
    ) -> tuple[MemoryRecord, list[str]]:
        actually_superseded: list[str] = []
        now = datetime.now(UTC)
        for old_id in supersedes:
            existing = self._records.get(old_id)
            if existing is None:
                raise ArtifactNotFound(f"memory not found: {old_id}")
            updated = existing.model_copy(
                update={
                    "status": "superseded",
                    "effective_until": now,
                    "updated_at": now,
                }
            )
            self._records[old_id] = updated
            actually_superseded.append(old_id)
        self._records[record.id] = record
        return record, actually_superseded

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        as_of = query.as_of or datetime.now(UTC)
        results: list[MemoryRecord] = []
        q_lower = query.query.lower()
        for r in self._records.values():
            if not _scope_matches(r.scope, query.scope):
                continue
            if r.status == "deleted":
                continue
            if not query.include_superseded:
                if r.status != "active":
                    continue
                if not _is_valid_at(r, as_of):
                    continue
            else:
                if not _is_valid_at(r, as_of):
                    continue
            if q_lower not in r.text.lower():
                continue
            results.append(r)
        return results[: query.limit]

    def list(
        self,
        scope: MemoryScope,
        status_filter: list[MemoryStatus] | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        effective_filter: list[MemoryStatus] = (
            status_filter if status_filter is not None else ["active", "superseded"]
        )
        out: list[MemoryRecord] = []
        for r in self._records.values():
            if not _scope_matches(r.scope, scope):
                continue
            if r.status not in effective_filter:
                continue
            out.append(r)
        return out[:limit]

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._records.get(memory_id)

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord:
        existing = self._records.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        merged = dict(existing.metadata)
        merged.update(metadata_patch)
        updated = existing.model_copy(
            update={"metadata": merged, "updated_at": datetime.now(UTC)}
        )
        self._records[memory_id] = updated
        return updated

    def soft_delete(self, memory_id: str) -> None:
        existing = self._records.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self._records[memory_id] = existing.model_copy(
            update={"status": "deleted", "updated_at": datetime.now(UTC)}
        )

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        target_scope = canonical_scope_key(scope)
        for r in self._records.values():
            if r.status in {"deleted", "superseded"}:
                continue
            if canonical_scope_key(r.scope) != target_scope:
                continue
            if memory_text_hash(r.text, r.scope) == text_hash:
                return r.id
        return None

    def close(self) -> None:
        return None
```

- [ ] **Step 2: Quick smoke test**

```bash
.venv/bin/python -c "
from datetime import UTC, datetime
from stele.storage.memory_store.memory import InProcessMemoryStore
from stele.core.memory_record import MemoryRecord, MemoryScope, MemoryQuery

s = InProcessMemoryStore()
s.initialize()
now = datetime.now(UTC)
r = MemoryRecord(
    id='m1', text='hello', kind='fact', scope=MemoryScope(user_id='a'),
    source_refs=['stele://ns/x'], created_at=now, updated_at=now, effective_from=now,
)
stored, sup = s.add(r, [])
print('stored:', stored.id, 'superseded:', sup)
hits = s.search(MemoryQuery(query='hello', scope=MemoryScope(user_id='a')))
print('hits:', [h.id for h in hits])
"
```

Expected output: `stored: m1 superseded: []` and `hits: ['m1']`.

- [ ] **Step 3: Lint and type-check**

```bash
.venv/bin/ruff check src/stele/storage/memory_store/memory.py
.venv/bin/mypy src/stele/storage/memory_store/memory.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/stele/storage/memory_store/memory.py
git commit -m "feat(memory): in-process MemoryStore (dict-backed)"
```

---

### Task 5: SQLite `MemoryStore` — schema + initialize

Land the schema first; supersession + search land in subsequent tasks. After this task, **DC-001 fires**.

**Files:**
- Create: `src/stele/storage/memory_store/sqlite.py` (schema only)
- Test: `tests/unit/storage/test_memory_schema.py`
- Test: `tests/unit/storage/__init__.py`

- [ ] **Step 1: Test stub package**

Create `tests/unit/storage/__init__.py` (empty file).

- [ ] **Step 2: Write the failing schema test**

Create `tests/unit/storage/test_memory_schema.py`:

```python
"""SQLite memory schema migration test (SC-001)."""

import sqlite3
from pathlib import Path

import pytest

from stele.storage.memory_store.sqlite import SQLiteMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteMemoryStore:
    s = SQLiteMemoryStore(tmp_path / "memory.db")
    s.initialize()
    return s


def test_memories_table_exists(store: SQLiteMemoryStore) -> None:
    cur = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
    )
    assert cur.fetchone() is not None


def test_memories_columns_present(store: SQLiteMemoryStore) -> None:
    cur = store.conn.execute("PRAGMA table_info(memories)")
    cols = {row[1] for row in cur.fetchall()}
    expected = {
        "id", "text", "kind", "user_id", "agent_id", "app_id", "session_id",
        "namespace", "source_refs", "source_chunk_ids", "confidence", "status",
        "supersedes", "text_hash", "created_at", "updated_at",
        "effective_from", "effective_until", "metadata", "pii_flags",
    }
    missing = expected - cols
    assert not missing, f"missing columns: {missing}"


def test_memories_indexes_present(store: SQLiteMemoryStore) -> None:
    cur = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memories'"
    )
    names = {row[0] for row in cur.fetchall()}
    for required in (
        "idx_memories_scope",
        "idx_memories_status",
        "idx_memories_effective",
        "idx_memories_text_hash",
    ):
        assert required in names, f"missing index: {required}"


def test_memories_fts_table_exists(store: SQLiteMemoryStore) -> None:
    cur = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
    )
    assert cur.fetchone() is not None


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    s1 = SQLiteMemoryStore(db)
    s1.initialize()
    s1.close()
    s2 = SQLiteMemoryStore(db)
    s2.initialize()  # should not raise
    cur = s2.conn.execute("SELECT count(*) FROM memories")
    assert cur.fetchone()[0] == 0
```

- [ ] **Step 3: Run test, verify failure**

```bash
.venv/bin/pytest tests/unit/storage/test_memory_schema.py -v
```

Expected: `ModuleNotFoundError: No module named 'stele.storage.memory_store.sqlite'`.

- [ ] **Step 4: Implement the schema-only SQLite store**

Create `src/stele/storage/memory_store/sqlite.py`:

```python
"""SQLite MemoryStore — schema migration + connection management.

Operations (add/search/list/etc.) land in subsequent tasks.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  kind TEXT NOT NULL
    CHECK (kind IN ('fact','preference','decision','instruction','commitment','issue','summary')),
  user_id TEXT,
  agent_id TEXT,
  app_id TEXT,
  session_id TEXT,
  namespace TEXT NOT NULL DEFAULT 'default',
  source_refs TEXT NOT NULL,
  source_chunk_ids TEXT NOT NULL DEFAULT '[]',
  confidence REAL NOT NULL DEFAULT 1.0,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','superseded','retracted','disputed','deleted')),
  supersedes TEXT NOT NULL DEFAULT '[]',
  text_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_until TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  pii_flags TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_memories_scope
  ON memories(namespace, user_id, agent_id, app_id, session_id);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_effective
  ON memories(effective_from, effective_until);
CREATE INDEX IF NOT EXISTS idx_memories_text_hash
  ON memories(text_hash, namespace, user_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
  USING fts5(text, content='memories', content_rowid='rowid');

CREATE TRIGGER IF NOT EXISTS memories_fts_insert
  AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
  END;
CREATE TRIGGER IF NOT EXISTS memories_fts_delete
  AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text)
      VALUES('delete', old.rowid, old.text);
  END;
CREATE TRIGGER IF NOT EXISTS memories_fts_update
  AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text)
      VALUES('delete', old.rowid, old.text);
    INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
  END;
"""


class SQLiteMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
```

- [ ] **Step 5: Run test, verify pass**

```bash
.venv/bin/pytest tests/unit/storage/test_memory_schema.py -v
```

Expected: 5 passed.

- [ ] **Step 6: ⛔ DC-001 — Drift checkpoint**

Re-read the mission brief at `skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md`, especially the **Evolution Boundary** and **Constraints (NEVER)** sections.

Then run:

```bash
git diff HEAD src/stele/core/artifact.py
git diff HEAD src/stele/storage/sqlite.py
git diff HEAD src/stele/storage/postgres.py
```

Expected: all three diffs are empty (or show only whitespace).

If any artifact-side evolution column (`effective_from`, `effective_until`, `retracted`, `supersedes`) appears in those diffs, STOP. The boundary has been violated. Revert the artifact-side changes before proceeding.

- [ ] **Step 7: Commit**

```bash
git add src/stele/storage/memory_store/sqlite.py tests/unit/storage/
git commit -m "feat(memory): SQLite schema + initialize (SC-001, DC-001 passed)"
```

---

### Task 6: SQLite `MemoryStore` — `add()` + `find_duplicate()` + `get()`

Build the simplest write/read pair before search.

**Files:**
- Modify: `src/stele/storage/memory_store/sqlite.py`
- Test: `tests/unit/core/test_memory_add.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_memory_add.py`:

```python
"""memory.add() — basic insert + supersession atomicity (SC-002)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    MemoryRecord,
    MemoryScope,
    memory_text_hash,
)
from stele.storage.memory_store.sqlite import SQLiteMemoryStore


def _make(record_id: str, text: str = "hello", scope: MemoryScope | None = None):
    scope = scope or MemoryScope(user_id="alice")
    now = datetime.now(UTC)
    return MemoryRecord(
        id=record_id,
        text=text,
        kind="fact",
        scope=scope,
        source_refs=["stele://ns/" + record_id],
        created_at=now,
        updated_at=now,
        effective_from=now,
    )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteMemoryStore:
    s = SQLiteMemoryStore(tmp_path / "m.db")
    s.initialize()
    return s


def test_add_persists_record(store: SQLiteMemoryStore) -> None:
    r = _make("m1")
    stored, sup = store.add(r, supersedes=[])
    assert stored.id == "m1"
    assert sup == []
    fetched = store.get("m1")
    assert fetched is not None
    assert fetched.text == "hello"
    assert fetched.status == "active"


def test_get_returns_none_for_missing(store: SQLiteMemoryStore) -> None:
    assert store.get("does-not-exist") is None


def test_add_with_supersedes_marks_old_records(store: SQLiteMemoryStore) -> None:
    a = _make("m_a", text="old preference")
    store.add(a, supersedes=[])
    b = _make("m_b", text="new preference")
    stored, sup = store.add(b, supersedes=["m_a"])
    assert sup == ["m_a"]
    old = store.get("m_a")
    assert old is not None
    assert old.status == "superseded"
    assert old.effective_until is not None
    new = store.get("m_b")
    assert new is not None
    assert new.status == "active"


def test_add_supersedes_missing_id_raises_and_keeps_new_unsaved(
    store: SQLiteMemoryStore,
) -> None:
    r = _make("m_new", text="new")
    with pytest.raises(ArtifactNotFound):
        store.add(r, supersedes=["does-not-exist"])
    # SC-002 atomicity: the new record must NOT have been inserted
    assert store.get("m_new") is None


def test_find_duplicate_returns_id_for_same_scope_same_text(
    store: SQLiteMemoryStore,
) -> None:
    scope = MemoryScope(user_id="alice")
    r = _make("m1", text="duplicate me", scope=scope)
    store.add(r, supersedes=[])
    h = memory_text_hash("duplicate me", scope)
    assert store.find_duplicate(scope, h) == "m1"


def test_find_duplicate_returns_none_for_different_scope(
    store: SQLiteMemoryStore,
) -> None:
    r = _make("m1", text="duplicate me", scope=MemoryScope(user_id="alice"))
    store.add(r, supersedes=[])
    h = memory_text_hash("duplicate me", MemoryScope(user_id="bob"))
    assert store.find_duplicate(MemoryScope(user_id="bob"), h) is None
```

- [ ] **Step 2: Run test, verify failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_add.py -v
```

Expected: all FAIL (`add`, `get`, `find_duplicate` not implemented on `SQLiteMemoryStore`).

- [ ] **Step 3: Extend `SQLiteMemoryStore` with the three methods**

Append to `src/stele/storage/memory_store/sqlite.py`:

```python
import json
from datetime import UTC, datetime

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    MemoryRecord,
    MemoryScope,
    memory_text_hash,
)


def _record_to_row(r: MemoryRecord) -> dict[str, object]:
    return {
        "id": r.id,
        "text": r.text,
        "kind": r.kind,
        "user_id": r.scope.user_id,
        "agent_id": r.scope.agent_id,
        "app_id": r.scope.app_id,
        "session_id": r.scope.session_id,
        "namespace": r.scope.namespace,
        "source_refs": json.dumps(r.source_refs),
        "source_chunk_ids": json.dumps(r.source_chunk_ids),
        "confidence": r.confidence,
        "status": r.status,
        "supersedes": json.dumps(r.supersedes),
        "text_hash": memory_text_hash(r.text, r.scope),
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
        "effective_from": r.effective_from.isoformat(),
        "effective_until": r.effective_until.isoformat() if r.effective_until else None,
        "metadata": json.dumps(r.metadata),
        "pii_flags": json.dumps(r.pii_flags),
    }


def _row_to_record(row: dict[str, object]) -> MemoryRecord:
    return MemoryRecord(
        id=str(row["id"]),
        text=str(row["text"]),
        kind=str(row["kind"]),  # type: ignore[arg-type]
        scope=MemoryScope(
            user_id=row["user_id"],  # type: ignore[arg-type]
            agent_id=row["agent_id"],  # type: ignore[arg-type]
            app_id=row["app_id"],  # type: ignore[arg-type]
            session_id=row["session_id"],  # type: ignore[arg-type]
            namespace=str(row["namespace"]),
        ),
        source_refs=json.loads(str(row["source_refs"])),
        source_chunk_ids=json.loads(str(row["source_chunk_ids"])),
        confidence=float(row["confidence"]),  # type: ignore[arg-type]
        status=str(row["status"]),  # type: ignore[arg-type]
        supersedes=json.loads(str(row["supersedes"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        effective_from=datetime.fromisoformat(str(row["effective_from"])),
        effective_until=(
            datetime.fromisoformat(str(row["effective_until"]))
            if row["effective_until"]
            else None
        ),
        metadata=json.loads(str(row["metadata"])),
        pii_flags=json.loads(str(row["pii_flags"])),
    )
```

Then add these methods to the `SQLiteMemoryStore` class body:

```python
    def add(
        self,
        record: MemoryRecord,
        supersedes: list[str],
    ) -> tuple[MemoryRecord, list[str]]:
        now = datetime.now(UTC).isoformat()
        cur = self.conn.cursor()
        try:
            cur.execute("BEGIN")
            for old_id in supersedes:
                affected = cur.execute(
                    "UPDATE memories SET status='superseded', "
                    "effective_until=?, updated_at=? WHERE id=?",
                    (now, now, old_id),
                ).rowcount
                if affected == 0:
                    raise ArtifactNotFound(f"memory not found: {old_id}")
            row = _record_to_row(record)
            cur.execute(
                "INSERT INTO memories ("
                "id, text, kind, user_id, agent_id, app_id, session_id, namespace,"
                "source_refs, source_chunk_ids, confidence, status, supersedes,"
                "text_hash, created_at, updated_at, effective_from, effective_until,"
                "metadata, pii_flags"
                ") VALUES ("
                ":id, :text, :kind, :user_id, :agent_id, :app_id, :session_id, :namespace,"
                ":source_refs, :source_chunk_ids, :confidence, :status, :supersedes,"
                ":text_hash, :created_at, :updated_at, :effective_from, :effective_until,"
                ":metadata, :pii_flags"
                ")",
                row,
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return record, list(supersedes)

    def get(self, memory_id: str) -> MemoryRecord | None:
        cur = self.conn.execute(
            "SELECT * FROM memories WHERE id=?", (memory_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_record(dict(row))

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        cur = self.conn.execute(
            "SELECT id FROM memories WHERE text_hash=? AND namespace=? "
            "AND user_id IS ? AND agent_id IS ? AND app_id IS ? AND session_id IS ? "
            "AND status NOT IN ('deleted','superseded') LIMIT 1",
            (
                text_hash,
                scope.namespace,
                scope.user_id,
                scope.agent_id,
                scope.app_id,
                scope.session_id,
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else None
```

- [ ] **Step 4: Run test, verify pass**

```bash
.venv/bin/pytest tests/unit/core/test_memory_add.py -v
.venv/bin/ruff check src/stele/storage/memory_store/sqlite.py
.venv/bin/mypy src/stele/storage/memory_store/sqlite.py
```

Expected: 6 passed, ruff/mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/stele/storage/memory_store/sqlite.py tests/unit/core/test_memory_add.py
git commit -m "feat(memory): SQLite add() with atomic supersession + get/find_duplicate (SC-002, SC-006)"
```

---

### Task 7: SQLite `MemoryStore` — `search()` with default filter, `as_of`, `include_superseded`

The headline query path. SC-003.

**Files:**
- Modify: `src/stele/storage/memory_store/sqlite.py`
- Test: `tests/unit/core/test_memory_search.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_memory_search.py`:

```python
"""memory.search() — default filter, as_of, include_superseded (SC-003)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele.core.memory_record import MemoryQuery, MemoryRecord, MemoryScope
from stele.storage.memory_store.sqlite import SQLiteMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteMemoryStore:
    s = SQLiteMemoryStore(tmp_path / "m.db")
    s.initialize()
    return s


def _record(id_: str, text: str, effective_from: datetime, scope=None) -> MemoryRecord:
    return MemoryRecord(
        id=id_,
        text=text,
        kind="preference",
        scope=scope or MemoryScope(user_id="alice"),
        source_refs=[f"stele://ns/{id_}"],
        created_at=effective_from,
        updated_at=effective_from,
        effective_from=effective_from,
    )


def test_search_returns_active_matches(store: SQLiteMemoryStore) -> None:
    now = datetime.now(UTC)
    store.add(_record("m1", "user prefers Helix editor", now), supersedes=[])
    hits = store.search(
        MemoryQuery(query="Helix", scope=MemoryScope(user_id="alice"))
    )
    assert [h.id for h in hits] == ["m1"]


def test_search_hides_superseded_by_default(store: SQLiteMemoryStore) -> None:
    t0 = datetime.now(UTC) - timedelta(days=2)
    t1 = datetime.now(UTC)
    store.add(_record("old", "user prefers Helix", t0), supersedes=[])
    store.add(_record("new", "user prefers Zed", t1), supersedes=["old"])
    hits = store.search(
        MemoryQuery(query="prefers", scope=MemoryScope(user_id="alice"))
    )
    ids = {h.id for h in hits}
    assert ids == {"new"}


def test_search_include_superseded_returns_both(store: SQLiteMemoryStore) -> None:
    t0 = datetime.now(UTC) - timedelta(days=2)
    t1 = datetime.now(UTC)
    store.add(_record("old", "user prefers Helix", t0), supersedes=[])
    store.add(_record("new", "user prefers Zed", t1), supersedes=["old"])
    hits = store.search(
        MemoryQuery(
            query="prefers",
            scope=MemoryScope(user_id="alice"),
            include_superseded=True,
        )
    )
    ids = {h.id for h in hits}
    assert ids == {"old", "new"}


def test_search_as_of_returns_historical_view(store: SQLiteMemoryStore) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)
    store.add(_record("old", "user prefers Helix", t0), supersedes=[])
    store.add(_record("new", "user prefers Zed", t1), supersedes=["old"])
    mid = datetime(2026, 1, 15, tzinfo=UTC)
    hits = store.search(
        MemoryQuery(
            query="prefers",
            scope=MemoryScope(user_id="alice"),
            as_of=mid,
        )
    )
    ids = {h.id for h in hits}
    assert ids == {"old"}


def test_search_filters_by_scope(store: SQLiteMemoryStore) -> None:
    now = datetime.now(UTC)
    store.add(
        _record("ma", "shared text", now, scope=MemoryScope(user_id="alice")),
        supersedes=[],
    )
    store.add(
        _record("mb", "shared text", now, scope=MemoryScope(user_id="bob")),
        supersedes=[],
    )
    hits = store.search(
        MemoryQuery(query="shared", scope=MemoryScope(user_id="alice"))
    )
    assert [h.id for h in hits] == ["ma"]
```

- [ ] **Step 2: Run test, verify failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_search.py -v
```

Expected: all FAIL (`search` not implemented).

- [ ] **Step 3: Implement `search()` on `SQLiteMemoryStore`**

Append to `SQLiteMemoryStore` class:

```python
    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        as_of = (query.as_of or datetime.now(UTC)).isoformat()
        params: list[object] = [as_of, as_of]
        sql = [
            "SELECT memories.* FROM memories",
            "JOIN memories_fts ON memories.rowid = memories_fts.rowid",
            "WHERE memories_fts MATCH ?",
        ]
        params.insert(0, query.query)
        sql.append(
            "AND memories.effective_from <= ?"
            " AND (memories.effective_until IS NULL OR memories.effective_until > ?)"
        )
        if not query.include_superseded:
            sql.append("AND memories.status = 'active'")
        else:
            sql.append("AND memories.status != 'deleted'")
        sql.append("AND memories.namespace = ?")
        params.append(query.scope.namespace)
        for field, value in (
            ("user_id", query.scope.user_id),
            ("agent_id", query.scope.agent_id),
            ("app_id", query.scope.app_id),
            ("session_id", query.scope.session_id),
        ):
            if value is not None:
                sql.append(f"AND memories.{field} = ?")
                params.append(value)
        sql.append("ORDER BY memories.effective_from DESC LIMIT ?")
        params.append(query.limit)
        cur = self.conn.execute(" ".join(sql), params)
        return [_row_to_record(dict(row)) for row in cur.fetchall()]
```

- [ ] **Step 4: Run test, verify pass**

```bash
.venv/bin/pytest tests/unit/core/test_memory_search.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/stele/storage/memory_store/sqlite.py tests/unit/core/test_memory_search.py
git commit -m "feat(memory): SQLite search with as_of + include_superseded (SC-003)"
```

---

### Task 8: SQLite `MemoryStore` — `list()`, `update_metadata()`, `soft_delete()`

Round out the CRUD. SC-004 (update text rejected) is enforced at the facade, not here.

**Files:**
- Modify: `src/stele/storage/memory_store/sqlite.py`
- Test: `tests/unit/core/test_memory_delete.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_memory_delete.py`:

```python
"""memory.delete() soft semantics + list() filtering (SC-005)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from stele.core.memory_record import MemoryQuery, MemoryRecord, MemoryScope
from stele.storage.memory_store.sqlite import SQLiteMemoryStore


def _r(id_: str, text: str = "x") -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id=id_, text=text, kind="fact",
        scope=MemoryScope(user_id="alice"),
        source_refs=[f"stele://ns/{id_}"],
        created_at=now, updated_at=now, effective_from=now,
    )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteMemoryStore:
    s = SQLiteMemoryStore(tmp_path / "m.db")
    s.initialize()
    return s


def test_soft_delete_flips_status(store: SQLiteMemoryStore) -> None:
    store.add(_r("m1"), supersedes=[])
    store.soft_delete("m1")
    got = store.get("m1")
    assert got is not None
    assert got.status == "deleted"


def test_search_excludes_deleted(store: SQLiteMemoryStore) -> None:
    store.add(_r("m1", "find me"), supersedes=[])
    store.soft_delete("m1")
    hits = store.search(
        MemoryQuery(query="find", scope=MemoryScope(user_id="alice"))
    )
    assert hits == []


def test_search_include_superseded_does_not_resurrect_deleted(
    store: SQLiteMemoryStore,
) -> None:
    store.add(_r("m1", "find me"), supersedes=[])
    store.soft_delete("m1")
    hits = store.search(
        MemoryQuery(
            query="find",
            scope=MemoryScope(user_id="alice"),
            include_superseded=True,
        )
    )
    assert hits == []


def test_list_default_excludes_deleted(store: SQLiteMemoryStore) -> None:
    store.add(_r("alive"), supersedes=[])
    store.add(_r("doomed"), supersedes=[])
    store.soft_delete("doomed")
    items = store.list(MemoryScope(user_id="alice"))
    ids = {r.id for r in items}
    assert ids == {"alive"}


def test_update_metadata_only(store: SQLiteMemoryStore) -> None:
    store.add(_r("m1"), supersedes=[])
    updated = store.update_metadata("m1", {"tag": "important"})
    assert updated.metadata["tag"] == "important"
```

- [ ] **Step 2: Run test, verify failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_delete.py -v
```

Expected: all FAIL — `soft_delete`, `list`, `update_metadata` not implemented.

- [ ] **Step 3: Implement the three methods**

Append to `SQLiteMemoryStore`:

```python
    def list(
        self,
        scope: MemoryScope,
        status_filter: list[str] | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        effective: list[str] = (
            list(status_filter) if status_filter is not None else ["active", "superseded"]
        )
        placeholders = ",".join("?" * len(effective))
        params: list[object] = [scope.namespace]
        sql = [
            "SELECT * FROM memories WHERE namespace = ?",
            f"AND status IN ({placeholders})",
        ]
        params.extend(effective)
        for field, value in (
            ("user_id", scope.user_id),
            ("agent_id", scope.agent_id),
            ("app_id", scope.app_id),
            ("session_id", scope.session_id),
        ):
            if value is not None:
                sql.append(f"AND {field} = ?")
                params.append(value)
        sql.append("ORDER BY effective_from DESC LIMIT ?")
        params.append(limit)
        cur = self.conn.execute(" ".join(sql), params)
        return [_row_to_record(dict(row)) for row in cur.fetchall()]

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord:
        existing = self.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        merged = dict(existing.metadata)
        merged.update(metadata_patch)
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE memories SET metadata=?, updated_at=? WHERE id=?",
            (json.dumps(merged), now, memory_id),
        )
        self.conn.commit()
        return existing.model_copy(
            update={"metadata": merged, "updated_at": datetime.fromisoformat(now)}
        )

    def soft_delete(self, memory_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        affected = self.conn.execute(
            "UPDATE memories SET status='deleted', updated_at=? WHERE id=?",
            (now, memory_id),
        ).rowcount
        if affected == 0:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self.conn.commit()
```

- [ ] **Step 4: Run test, verify pass**

```bash
.venv/bin/pytest tests/unit/core/test_memory_delete.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/stele/storage/memory_store/sqlite.py tests/unit/core/test_memory_delete.py
git commit -m "feat(memory): SQLite list + update_metadata + soft_delete (SC-005)"
```

---

### Task 9: `Memory` facade — `add`, `get`, `search`, `list`

The public class users call. Layers PII scrubbing on top of the store. Wires Stele.memory.

**Files:**
- Create: `src/stele/core/memory.py`
- Test: `tests/unit/core/test_memory_facade.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_memory_facade.py`:

```python
"""Memory facade + Stele.memory property."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory import Memory
from stele.core.memory_record import MemoryQuery, MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_stele_memory_property_returns_memory(stele: Stele) -> None:
    assert isinstance(stele.memory, Memory)


def test_memory_add_then_get(stele: Stele) -> None:
    res = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    fetched = stele.memory.get(res.record.id)
    assert fetched is not None
    assert fetched.text == "user prefers Helix"


def test_memory_add_then_search(stele: Stele) -> None:
    stele.memory.add(
        text="favorite editor is Helix",
        kind="preference",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    hits = stele.memory.search(
        MemoryQuery(query="editor", scope=MemoryScope(user_id="alice"))
    )
    assert len(hits) == 1


def test_memory_supersession_via_add(stele: Stele) -> None:
    old = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    new = stele.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="alice"),
        supersedes=[old.record.id],
    )
    hits = stele.memory.search(
        MemoryQuery(query="prefers", scope=MemoryScope(user_id="alice"))
    )
    assert [h.id for h in hits] == [new.record.id]
```

- [ ] **Step 2: Run test, verify failure**

```bash
.venv/bin/pytest tests/unit/core/test_memory_facade.py -v
```

Expected: FAIL (no `memory` attribute on Stele; no `stele.core.memory` module).

- [ ] **Step 3: Implement the facade**

Create `src/stele/core/memory.py`:

```python
"""Memory facade — public API on top of MemoryStore."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from stele.core.exceptions import CapabilityError, ValidationError
from stele.core.memory_record import (
    MemoryAddResult,
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    memory_text_hash,
)
from stele.storage.memory_store.base import MemoryStore


class Memory:
    def __init__(self, store: MemoryStore, scrubber) -> None:
        self._store = store
        self._scrubber = scrubber

    def add(
        self,
        *,
        text: str,
        kind: MemoryKind,
        source_refs: list[str],
        scope: MemoryScope,
        supersedes: list[str] | None = None,
        confidence: float = 1.0,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        scrubbed = self._scrubber.scrub(text)
        now = datetime.now(UTC)
        record = MemoryRecord(
            id=uuid.uuid4().hex,
            text=scrubbed.text,
            kind=kind,
            scope=scope,
            source_refs=source_refs,
            confidence=confidence,
            created_at=now,
            updated_at=now,
            effective_from=now,
            metadata=metadata or {},
            pii_flags=sorted({d.entity_type for d in scrubbed.detections}),
        )
        dup_id = self._store.find_duplicate(
            scope, memory_text_hash(record.text, scope)
        )
        stored, superseded_ids = self._store.add(record, supersedes or [])
        return MemoryAddResult(
            record=stored,
            duplicate_of=dup_id,
            superseded_ids=superseded_ids,
        )

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        return self._store.search(query)

    def list(
        self,
        scope: MemoryScope,
        status_filter: list[MemoryStatus] | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        return self._store.list(scope, status_filter, limit)

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._store.get(memory_id)

    def update(
        self,
        memory_id: str,
        *,
        text: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryRecord:
        if text is not None:
            raise CapabilityError(
                "text edits must use add(supersedes=[id]); update() preserves history"
            )
        if metadata is None:
            existing = self._store.get(memory_id)
            if existing is None:
                from stele.core.exceptions import ArtifactNotFound

                raise ArtifactNotFound(f"memory not found: {memory_id}")
            return existing
        return self._store.update_metadata(memory_id, metadata)

    def delete(self, memory_id: str) -> None:
        self._store.soft_delete(memory_id)
```

- [ ] **Step 4: Wire `Stele.memory` property**

In `src/stele/core/stash.py`, add this method to the `Stele` class (place it near `close`):

```python
    @property
    def memory(self) -> "Memory":  # forward ref; imported below
        if not hasattr(self, "_memory"):
            from stele.core.memory import Memory
            from stele.storage.memory_store.memory import InProcessMemoryStore
            from stele.storage.memory_store.sqlite import SQLiteMemoryStore

            store: object
            if self.config.backend.type == "memory":
                store = InProcessMemoryStore()
            elif self.config.backend.type == "sqlite":
                path = self.config.backend.path or ".stele/stele.db"
                from pathlib import Path

                memory_db = str(Path(path).with_name("memory_" + Path(path).name))
                store = SQLiteMemoryStore(memory_db)
            elif self.config.backend.type == "postgres":
                from stele.storage.memory_store.postgres import PostgresMemoryStore

                if not self.config.backend.dsn:
                    raise ConfigError("Postgres memory store requires backend.dsn")
                store = PostgresMemoryStore(self.config.backend.dsn)
            elif self.config.backend.type == "mariadb":
                from stele.storage.memory_store.mariadb import MariaDBMemoryStore

                store = MariaDBMemoryStore()
            elif self.config.backend.type == "clickhouse":
                from stele.storage.memory_store.clickhouse import ClickHouseMemoryStore

                store = ClickHouseMemoryStore()
            else:
                raise ConfigError(
                    f"Memory store not implemented for backend: {self.config.backend.type}"
                )
            store.initialize()  # type: ignore[attr-defined]
            self._memory = Memory(store, self.pii_scrubber)  # type: ignore[arg-type]
        return self._memory
```

- [ ] **Step 5: Update `src/stele/__init__.py` exports**

Append to the imports section:

```python
from stele.core.memory import Memory
from stele.core.memory_record import (
    MemoryAddResult,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
)
from stele.core.exceptions import ValidationError
```

And add to `__all__`:

```python
    "Memory",
    "MemoryAddResult",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryScope",
    "ValidationError",
```

- [ ] **Step 6: Run test, verify pass**

```bash
.venv/bin/pytest tests/unit/core/test_memory_facade.py -v
.venv/bin/ruff check --fix src/stele/ tests/unit/core/test_memory_facade.py
.venv/bin/mypy src/stele
```

Expected: 4 passed, ruff clean (after autofix), mypy clean.

- [ ] **Step 7: Commit**

```bash
git add src/stele/core/memory.py src/stele/core/stash.py src/stele/__init__.py tests/unit/core/test_memory_facade.py
git commit -m "feat(memory): Memory facade + Stele.memory property"
```

---

### Task 10: Facade — `update()` blocks text edits (SC-004)

Already implemented in Task 9; this task adds the explicit test.

**Files:**
- Test: `tests/unit/core/test_memory_update.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/core/test_memory_update.py`:

```python
"""memory.update() rejects text edits (SC-004)."""

from pathlib import Path

import pytest

from stele import Stele
from stele.core.exceptions import CapabilityError
from stele.core.memory_record import MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_update_rejects_text_change(stele: Stele) -> None:
    r = stele.memory.add(
        text="hello",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    with pytest.raises(CapabilityError) as exc:
        stele.memory.update(r.record.id, text="goodbye")
    msg = str(exc.value)
    assert "supersedes" in msg
    assert "preserves history" in msg


def test_update_metadata_succeeds(stele: Stele) -> None:
    r = stele.memory.add(
        text="hello",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    updated = stele.memory.update(r.record.id, metadata={"tag": "x"})
    assert updated.metadata["tag"] == "x"
    assert updated.text == "hello"
```

- [ ] **Step 2: Run, expect pass (already implemented)**

```bash
.venv/bin/pytest tests/unit/core/test_memory_update.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/core/test_memory_update.py
git commit -m "test(memory): cover update text-rejection contract (SC-004)"
```

---

### Task 11: Duplicate-detection facade test (SC-006)

Confirms the facade surfaces `duplicate_of` correctly.

**Files:**
- Test: `tests/unit/core/test_memory_duplicates.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/core/test_memory_duplicates.py`:

```python
"""Duplicate detection (SC-006)."""

from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_first_add_has_no_duplicate(stele: Stele) -> None:
    r = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    assert r.duplicate_of is None


def test_second_identical_add_flags_duplicate(stele: Stele) -> None:
    r1 = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    r2 = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="alice"),
    )
    assert r2.duplicate_of == r1.record.id


def test_different_scope_not_duplicate(stele: Stele) -> None:
    stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    r = stele.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="bob"),
    )
    assert r.duplicate_of is None
```

- [ ] **Step 2: Run, expect pass**

```bash
.venv/bin/pytest tests/unit/core/test_memory_duplicates.py -v
```

Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/core/test_memory_duplicates.py
git commit -m "test(memory): duplicate detection (SC-006)"
```

---

### Task 12: PII scrubbing on memory text (SC-009)

The scrubber is already applied in `Memory.add()`. Test confirms behavior and `pii_flags` propagation.

**Files:**
- Test: `tests/unit/pii/test_memory_scrubbing.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/pii/test_memory_scrubbing.py`:

```python
"""PII scrub on memory text (SC-009)."""

from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_email_in_memory_is_scrubbed_on_add(stele: Stele) -> None:
    r = stele.memory.add(
        text="contact alice@example.com about ticket",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    assert "alice@example.com" not in r.record.text
    assert "EMAIL" in "\n".join(r.record.pii_flags).upper() or r.record.pii_flags


def test_scrubbed_text_persists_through_search(stele: Stele) -> None:
    stele.memory.add(
        text="contact bob@example.com today",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    hits = stele.memory.search(
        MemoryQuery(query="contact", scope=MemoryScope(user_id="alice"))
    )
    assert len(hits) == 1
    assert "bob@example.com" not in hits[0].text
```

- [ ] **Step 2: Run, expect pass**

```bash
.venv/bin/pytest tests/unit/pii/test_memory_scrubbing.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/pii/test_memory_scrubbing.py
git commit -m "test(memory): PII scrub on memory text (SC-009)"
```

---

### Task 13: Postgres `MemoryStore`

Mirror the SQLite store on Postgres. Use tsvector for search; otherwise same shape.

**Files:**
- Create: `src/stele/storage/memory_store/postgres.py`
- Test: contract suite covers (Task 17). Add a unit test for Postgres schema as a smoke.

- [ ] **Step 1: Implement `PostgresMemoryStore`**

Create `src/stele/storage/memory_store/postgres.py`:

```python
"""Postgres MemoryStore — tsvector search, mirror of SQLite shape."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row

from stele.core.exceptions import ArtifactNotFound
from stele.core.memory_record import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    memory_text_hash,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (
    kind IN ('fact','preference','decision','instruction','commitment','issue','summary')
  ),
  user_id TEXT, agent_id TEXT, app_id TEXT, session_id TEXT,
  namespace TEXT NOT NULL DEFAULT 'default',
  source_refs JSONB NOT NULL,
  source_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  status TEXT NOT NULL DEFAULT 'active' CHECK (
    status IN ('active','superseded','retracted','disputed','deleted')
  ),
  supersedes JSONB NOT NULL DEFAULT '[]'::jsonb,
  text_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  effective_from TIMESTAMPTZ NOT NULL,
  effective_until TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  pii_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  search_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

CREATE INDEX IF NOT EXISTS idx_memories_scope
  ON memories(namespace, user_id, agent_id, app_id, session_id);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_effective
  ON memories(effective_from, effective_until);
CREATE INDEX IF NOT EXISTS idx_memories_text_hash
  ON memories(text_hash, namespace, user_id);
CREATE INDEX IF NOT EXISTS idx_memories_search_tsv
  ON memories USING GIN(search_tsv);
"""


def _to_record(row: dict[str, object]) -> MemoryRecord:
    return MemoryRecord(
        id=str(row["id"]),
        text=str(row["text"]),
        kind=str(row["kind"]),  # type: ignore[arg-type]
        scope=MemoryScope(
            user_id=row["user_id"],  # type: ignore[arg-type]
            agent_id=row["agent_id"],  # type: ignore[arg-type]
            app_id=row["app_id"],  # type: ignore[arg-type]
            session_id=row["session_id"],  # type: ignore[arg-type]
            namespace=str(row["namespace"]),
        ),
        source_refs=row["source_refs"],  # type: ignore[arg-type]
        source_chunk_ids=row["source_chunk_ids"],  # type: ignore[arg-type]
        confidence=float(row["confidence"]),  # type: ignore[arg-type]
        status=str(row["status"]),  # type: ignore[arg-type]
        supersedes=row["supersedes"],  # type: ignore[arg-type]
        created_at=row["created_at"],  # type: ignore[arg-type]
        updated_at=row["updated_at"],  # type: ignore[arg-type]
        effective_from=row["effective_from"],  # type: ignore[arg-type]
        effective_until=row["effective_until"],  # type: ignore[arg-type]
        metadata=row["metadata"],  # type: ignore[arg-type]
        pii_flags=row["pii_flags"],  # type: ignore[arg-type]
    )


class PostgresMemoryStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)

    def initialize(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(_SCHEMA)
        self.conn.commit()

    def add(
        self,
        record: MemoryRecord,
        supersedes: list[str],
    ) -> tuple[MemoryRecord, list[str]]:
        now = datetime.now(UTC)
        try:
            with self.conn.cursor() as cur:
                for old_id in supersedes:
                    affected = cur.execute(
                        "UPDATE memories SET status='superseded', "
                        "effective_until=%s, updated_at=%s WHERE id=%s",
                        (now, now, old_id),
                    ).rowcount
                    if affected == 0:
                        raise ArtifactNotFound(f"memory not found: {old_id}")
                cur.execute(
                    "INSERT INTO memories ("
                    "id, text, kind, user_id, agent_id, app_id, session_id, namespace,"
                    "source_refs, source_chunk_ids, confidence, status, supersedes,"
                    "text_hash, created_at, updated_at, effective_from, effective_until,"
                    "metadata, pii_flags"
                    ") VALUES ("
                    "%s, %s, %s, %s, %s, %s, %s, %s,"
                    "%s::jsonb, %s::jsonb, %s, %s, %s::jsonb,"
                    "%s, %s, %s, %s, %s,"
                    "%s::jsonb, %s::jsonb)",
                    (
                        record.id, record.text, record.kind,
                        record.scope.user_id, record.scope.agent_id,
                        record.scope.app_id, record.scope.session_id,
                        record.scope.namespace,
                        json.dumps(record.source_refs),
                        json.dumps(record.source_chunk_ids),
                        record.confidence, record.status,
                        json.dumps(record.supersedes),
                        memory_text_hash(record.text, record.scope),
                        record.created_at, record.updated_at,
                        record.effective_from, record.effective_until,
                        json.dumps(record.metadata),
                        json.dumps(record.pii_flags),
                    ),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return record, list(supersedes)

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM memories WHERE id=%s", (memory_id,))
            row = cur.fetchone()
        return _to_record(row) if row else None

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        as_of = query.as_of or datetime.now(UTC)
        sql = [
            "SELECT * FROM memories",
            "WHERE search_tsv @@ plainto_tsquery('english', %s)",
            "AND effective_from <= %s",
            "AND (effective_until IS NULL OR effective_until > %s)",
            "AND namespace = %s",
        ]
        params: list[object] = [query.query, as_of, as_of, query.scope.namespace]
        if not query.include_superseded:
            sql.append("AND status = 'active'")
        else:
            sql.append("AND status != 'deleted'")
        for field, value in (
            ("user_id", query.scope.user_id),
            ("agent_id", query.scope.agent_id),
            ("app_id", query.scope.app_id),
            ("session_id", query.scope.session_id),
        ):
            if value is not None:
                sql.append(f"AND {field} = %s")
                params.append(value)
        sql.append("ORDER BY effective_from DESC LIMIT %s")
        params.append(query.limit)
        with self.conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()
        return [_to_record(r) for r in rows]

    def list(
        self,
        scope: MemoryScope,
        status_filter: list[str] | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        effective: list[str] = (
            list(status_filter) if status_filter is not None else ["active", "superseded"]
        )
        sql = ["SELECT * FROM memories WHERE namespace=%s AND status = ANY(%s)"]
        params: list[object] = [scope.namespace, effective]
        for field, value in (
            ("user_id", scope.user_id),
            ("agent_id", scope.agent_id),
            ("app_id", scope.app_id),
            ("session_id", scope.session_id),
        ):
            if value is not None:
                sql.append(f"AND {field} = %s")
                params.append(value)
        sql.append("ORDER BY effective_from DESC LIMIT %s")
        params.append(limit)
        with self.conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            rows = cur.fetchall()
        return [_to_record(r) for r in rows]

    def update_metadata(
        self,
        memory_id: str,
        metadata_patch: dict[str, object],
    ) -> MemoryRecord:
        existing = self.get(memory_id)
        if existing is None:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        merged = dict(existing.metadata)
        merged.update(metadata_patch)
        now = datetime.now(UTC)
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET metadata=%s::jsonb, updated_at=%s WHERE id=%s",
                (json.dumps(merged), now, memory_id),
            )
        self.conn.commit()
        return existing.model_copy(update={"metadata": merged, "updated_at": now})

    def soft_delete(self, memory_id: str) -> None:
        now = datetime.now(UTC)
        with self.conn.cursor() as cur:
            affected = cur.execute(
                "UPDATE memories SET status='deleted', updated_at=%s WHERE id=%s",
                (now, memory_id),
            ).rowcount
        if affected == 0:
            raise ArtifactNotFound(f"memory not found: {memory_id}")
        self.conn.commit()

    def find_duplicate(
        self,
        scope: MemoryScope,
        text_hash: str,
    ) -> str | None:
        sql = [
            "SELECT id FROM memories",
            "WHERE text_hash=%s AND namespace=%s",
            "AND user_id IS NOT DISTINCT FROM %s",
            "AND agent_id IS NOT DISTINCT FROM %s",
            "AND app_id IS NOT DISTINCT FROM %s",
            "AND session_id IS NOT DISTINCT FROM %s",
            "AND status NOT IN ('deleted','superseded')",
            "LIMIT 1",
        ]
        params = (
            text_hash,
            scope.namespace,
            scope.user_id, scope.agent_id, scope.app_id, scope.session_id,
        )
        with self.conn.cursor() as cur:
            cur.execute(" ".join(sql), params)
            row = cur.fetchone()
        return str(row["id"]) if row else None

    def close(self) -> None:
        self.conn.close()
```

- [ ] **Step 2: Lint and type-check**

```bash
.venv/bin/ruff check src/stele/storage/memory_store/postgres.py
.venv/bin/mypy src/stele/storage/memory_store/postgres.py
```

Expected: clean.

- [ ] **Step 3: Quick smoke test if STELE_PG_DSN set**

```bash
if [ -n "$STELE_PG_DSN" ]; then
  .venv/bin/python -c "
from stele.storage.memory_store.postgres import PostgresMemoryStore
import os
s = PostgresMemoryStore(os.environ['STELE_PG_DSN'])
s.initialize()
print('postgres memory schema OK')
s.close()
"
fi
```

Expected (if DSN set): `postgres memory schema OK`. If DSN unset, skip — contract tests will cover it once Postgres is up.

- [ ] **Step 4: Commit**

```bash
git add src/stele/storage/memory_store/postgres.py
git commit -m "feat(memory): Postgres MemoryStore with tsvector search"
```

---

### Task 14: MariaDB and ClickHouse stubs (CapabilityError)

Per brief: memory support on these backends arrives later; for now they raise `CapabilityError` with a clear message.

**Files:**
- Create: `src/stele/storage/memory_store/mariadb.py`
- Create: `src/stele/storage/memory_store/clickhouse.py`

- [ ] **Step 1: Implement the stubs**

Create `src/stele/storage/memory_store/mariadb.py`:

```python
"""MariaDB memory stub — memory support lands in a later slice."""

from __future__ import annotations

from typing import Any

from stele.core.exceptions import CapabilityError

_MSG = (
    "memory support on the MariaDB backend is not yet implemented; "
    "use the SQLite or Postgres backend, or wait for a later phase"
)


class MariaDBMemoryStore:
    def initialize(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        if name in {
            "add", "search", "list", "get",
            "update_metadata", "soft_delete", "find_duplicate", "close",
        }:
            def _raise(*_args: object, **_kwargs: object) -> None:
                raise CapabilityError(_MSG)

            return _raise
        raise AttributeError(name)
```

Create `src/stele/storage/memory_store/clickhouse.py`:

```python
"""ClickHouse memory stub — memory support lands in a later slice."""

from __future__ import annotations

from typing import Any

from stele.core.exceptions import CapabilityError

_MSG = (
    "memory support on the ClickHouse backend is not yet implemented; "
    "use the SQLite or Postgres backend, or wait for a later phase"
)


class ClickHouseMemoryStore:
    def initialize(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        if name in {
            "add", "search", "list", "get",
            "update_metadata", "soft_delete", "find_duplicate", "close",
        }:
            def _raise(*_args: object, **_kwargs: object) -> None:
                raise CapabilityError(_MSG)

            return _raise
        raise AttributeError(name)
```

- [ ] **Step 2: Lint and type-check**

```bash
.venv/bin/ruff check src/stele/storage/memory_store/mariadb.py src/stele/storage/memory_store/clickhouse.py
.venv/bin/mypy src/stele/storage/memory_store/
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add src/stele/storage/memory_store/mariadb.py src/stele/storage/memory_store/clickhouse.py
git commit -m "feat(memory): MariaDB and ClickHouse capability-error stubs"
```

---

### Task 15: Cross-backend contract test (SC-008)

Parametrize core memory behavior across `memory + sqlite + postgres`. After this task, **DC-002 fires**.

**Files:**
- Test: `tests/contract/test_memory_contract.py`

- [ ] **Step 1: Write the contract test**

Create `tests/contract/test_memory_contract.py`:

```python
"""Memory contract tests parametrized across backends (SC-008)."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope

BACKENDS = ["memory", "sqlite"]
if os.environ.get("STELE_PG_DSN"):
    BACKENDS.append("postgres")


def _stele(tmp_path: Path, backend: str) -> Stele:
    if backend == "memory":
        return Stele.from_config({"backend": {"type": "memory"}})
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
        )
    return Stele.from_config(
        {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}}
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_add_then_get(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    r = s.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    got = s.memory.get(r.record.id)
    assert got is not None
    assert got.text == "user prefers Helix"


@pytest.mark.parametrize("backend", BACKENDS)
def test_supersession_hides_old_in_default_search(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    old = s.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    new = s.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="alice"),
        supersedes=[old.record.id],
    )
    hits = s.memory.search(
        MemoryQuery(query="prefers", scope=MemoryScope(user_id="alice"))
    )
    assert [h.id for h in hits] == [new.record.id]


@pytest.mark.parametrize("backend", BACKENDS)
def test_as_of_returns_historical(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    old = s.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    t_between = datetime.now(UTC) + timedelta(milliseconds=10)
    import time

    time.sleep(0.05)  # ensure new memory has later effective_from
    s.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id="alice"),
        supersedes=[old.record.id],
    )
    hits = s.memory.search(
        MemoryQuery(
            query="prefers",
            scope=MemoryScope(user_id="alice"),
            as_of=t_between,
        )
    )
    ids = {h.id for h in hits}
    assert ids == {old.record.id}


@pytest.mark.parametrize("backend", BACKENDS)
def test_delete_excludes_from_search(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    r = s.memory.add(
        text="find me",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id="alice"),
    )
    s.memory.delete(r.record.id)
    hits = s.memory.search(
        MemoryQuery(query="find", scope=MemoryScope(user_id="alice"))
    )
    assert hits == []
    assert s.memory.get(r.record.id) is not None  # still retrievable


@pytest.mark.parametrize("backend", ["mariadb", "clickhouse"])
def test_unsupported_backend_raises_capability_error(
    tmp_path: Path,
    backend: str,
) -> None:
    if backend == "mariadb" and not os.environ.get("STELE_MARIADB_DSN"):
        pytest.skip("STELE_MARIADB_DSN unset")
    if backend == "clickhouse" and not os.environ.get("STELE_CLICKHOUSE_DSN"):
        pytest.skip("STELE_CLICKHOUSE_DSN unset")
    from stele.core.exceptions import CapabilityError

    dsn_env = f"STELE_{backend.upper()}_DSN"
    s = Stele.from_config(
        {"backend": {"type": backend, "dsn": os.environ[dsn_env]}}
    )
    with pytest.raises(CapabilityError) as exc:
        s.memory.add(
            text="x",
            kind="fact",
            source_refs=["stele://default/a"],
            scope=MemoryScope(user_id="alice"),
        )
    assert "not yet implemented" in str(exc.value)
```

- [ ] **Step 2: Run with memory + sqlite (Postgres skipped if DSN unset)**

```bash
.venv/bin/pytest tests/contract/test_memory_contract.py -v
```

Expected: 8 passed (4 tests × 2 backends), or 12 passed if `STELE_PG_DSN` is set.

If `STELE_PG_DSN` is set:
```bash
scripts/postgres-up.sh
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
.venv/bin/pytest tests/contract/test_memory_contract.py -v
```

Expected: 12+ passed.

- [ ] **Step 3: ⛔ DC-002 — Drift checkpoint**

Re-read the mission brief. Then run:

```bash
grep -rn 'pg_raggraph\|pg-raggraph\|chunkshop\|MemoryExtractor' \
  src/stele/core/memory*.py src/stele/storage/memory_store/
```

Expected output: **empty**. If any match, STOP — the slice has drifted into Phase 4 or Phase 5.

- [ ] **Step 4: Commit**

```bash
git add tests/contract/test_memory_contract.py
git commit -m "test(memory): cross-backend contract suite (SC-008, DC-002 passed)"
```

---

### Task 16: Architectural layering check (SC-011)

Verify `Memory` doesn't reach into storage internals.

**Files:**
- Test: `tests/unit/test_architecture.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/test_architecture.py`:

```python
"""Layering checks — Memory facade does not import storage internals (SC-011)."""

import ast
from pathlib import Path

REPO = Path(__file__).parent.parent.parent


def _imports(file: Path) -> list[str]:
    tree = ast.parse(file.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
    return names


def test_memory_facade_does_not_import_storage_backends_directly() -> None:
    """The Memory facade should depend on MemoryStore protocol, not concrete stores.

    Concrete stores are imported lazily in Stele.memory property; the facade
    module itself only knows about the abstract protocol.
    """
    facade = REPO / "src/stele/core/memory.py"
    imports = _imports(facade)
    forbidden = [
        "stele.storage.memory_store.sqlite",
        "stele.storage.memory_store.postgres",
        "stele.storage.memory_store.mariadb",
        "stele.storage.memory_store.clickhouse",
        "stele.storage.sqlite",
        "stele.storage.postgres",
    ]
    for f in forbidden:
        assert f not in imports, f"Memory facade illegally imports {f}"


def test_memory_record_module_has_no_storage_imports() -> None:
    record = REPO / "src/stele/core/memory_record.py"
    imports = _imports(record)
    for name in imports:
        assert not name.startswith("stele.storage"), (
            f"memory_record.py imports storage module: {name}"
        )


def test_no_artifact_evolution_columns_added() -> None:
    """SC-011 + Evolution Boundary: artifact model is unchanged."""
    artifact = REPO / "src/stele/core/artifact.py"
    src = artifact.read_text()
    for forbidden in (
        "effective_from",
        "effective_until",
        "retracted",
        "supersedes",
    ):
        assert forbidden not in src, (
            f"artifact.py contains '{forbidden}' — Evolution Boundary violated"
        )
```

- [ ] **Step 2: Run, expect pass**

```bash
.venv/bin/pytest tests/unit/test_architecture.py -v
```

Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_architecture.py
git commit -m "test(architecture): SC-011 layering + Evolution Boundary guard"
```

---

### Task 17: Source-ref validation through the facade (SC-010)

The model rejects bad source_refs (Task 2). This task confirms the rejection propagates through the facade.

**Files:**
- Test: `tests/unit/core/test_memory_validation.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/core/test_memory_validation.py`:

```python
"""SC-010 source_refs validation propagates through Memory facade."""

from pathlib import Path

import pytest

from stele import Stele
from stele.core.exceptions import ValidationError
from stele.core.memory_record import MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def test_empty_source_refs_rejected(stele: Stele) -> None:
    with pytest.raises(ValidationError) as exc:
        stele.memory.add(
            text="hello",
            kind="fact",
            source_refs=[],
            scope=MemoryScope(user_id="alice"),
        )
    assert "stele://" in str(exc.value)


def test_non_stele_source_ref_rejected(stele: Stele) -> None:
    with pytest.raises(ValidationError) as exc:
        stele.memory.add(
            text="hello",
            kind="fact",
            source_refs=["https://example.com"],
            scope=MemoryScope(user_id="alice"),
        )
    assert "stele://" in str(exc.value)
```

- [ ] **Step 2: Run, expect pass**

```bash
.venv/bin/pytest tests/unit/core/test_memory_validation.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/core/test_memory_validation.py
git commit -m "test(memory): SC-010 source_refs validation propagation"
```

---

### Task 18: Demo script (`scripts/demo-supersession.sh`)

Human-readable proof, referenced in SC-007's E2E plan.

**Files:**
- Create: `scripts/demo-supersession.sh`

- [ ] **Step 1: Write the script**

Create `scripts/demo-supersession.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON=.venv/bin/python

"$PYTHON" - <<'PY'
"""Stele supersession demo: prove living-knowledge semantics at the data layer."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope

with tempfile.TemporaryDirectory() as tmp:
    stele = Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(Path(tmp) / "demo.db")}}
    )
    scope = MemoryScope(user_id="alice", namespace="demo")

    # T0: user prefers Helix
    old = stele.memory.add(
        text="user prefers Helix editor",
        kind="preference",
        source_refs=["stele://demo/onboarding-2026-01"],
        scope=scope,
    )
    print(f"T0  added memory {old.record.id[:8]}: 'user prefers Helix editor'")

    t_between = datetime.now(UTC) + timedelta(milliseconds=50)

    import time
    time.sleep(0.1)  # ensure new memory effective_from > t_between

    # T1: user switches to Zed; supersede the old preference
    new = stele.memory.add(
        text="user prefers Zed editor",
        kind="preference",
        source_refs=["stele://demo/chat-2026-05"],
        scope=scope,
        supersedes=[old.record.id],
    )
    print(f"T1  added memory {new.record.id[:8]}: 'user prefers Zed editor'")
    print(f"    superseded: {new.superseded_ids}")
    print()

    # Default search returns Zed only
    hits = stele.memory.search(MemoryQuery(query="prefers", scope=scope))
    print("DEFAULT search('prefers'):")
    for h in hits:
        print(f"  {h.id[:8]} [{h.status}] {h.text!r}")
    print()

    # as_of=t_between returns Helix
    hits = stele.memory.search(
        MemoryQuery(query="prefers", scope=scope, as_of=t_between)
    )
    print(f"AS_OF={t_between.isoformat()} search('prefers'):")
    for h in hits:
        print(f"  {h.id[:8]} [{h.status}] {h.text!r}")
    print()

    # include_superseded shows both
    hits = stele.memory.search(
        MemoryQuery(query="prefers", scope=scope, include_superseded=True)
    )
    print("INCLUDE_SUPERSEDED=True search('prefers'):")
    for h in hits:
        print(f"  {h.id[:8]} [{h.status}] {h.text!r}")
PY
```

- [ ] **Step 2: Make executable and run**

```bash
chmod +x scripts/demo-supersession.sh
scripts/demo-supersession.sh
```

Expected output: a `DEFAULT` block showing only Zed, an `AS_OF` block showing only Helix, an `INCLUDE_SUPERSEDED=True` block showing both with statuses.

- [ ] **Step 3: Commit**

```bash
git add scripts/demo-supersession.sh
git commit -m "feat(demo): supersession demo script proving as_of semantics"
```

---

### Task 19: Longrun benchmark — `SUPERSESSION_ENABLED` flag + scenario rewrite (SC-007, load-bearing)

The mission brief's headline proof. The four temporal scenarios must fail with the flag off and pass with it on. **DC-003 fires after this task.**

**Files:**
- Modify: `benchmarks/longrun.py`

- [ ] **Step 1: Inspect current temporal scenarios**

```bash
grep -n 'temporal\|knowledge_update' benchmarks/longrun.py | head -20
```

Note the existing `_scenario("temporal_old_title", "temporal", "...")` shape and the function that turns scenarios into stash workloads.

- [ ] **Step 2: Add the feature flag and a memory-aware path**

In `benchmarks/longrun.py`:

1. Near the top, after existing imports, add:

```python
import os

SUPERSESSION_ENABLED = os.environ.get("STELE_SUPERSESSION_ENABLED", "1") not in {"0", "false", "False"}
```

2. Find the helper that constructs scenarios. For each of the four temporal scenarios (`temporal_old_title`, `temporal_new_title`, `knowledge_update_address`, `knowledge_update_preference`), refactor so they are paired:

```python
# At a clearly-commented section labelled "Temporal supersession scenarios"
def _temporal_scenarios() -> list:
    """Pairs of (old, new) memories where the new supersedes the old.

    The benchmark's job is to return the currently-true memory. Without
    supersession (SUPERSESSION_ENABLED=False), this passes only by keyword
    coincidence — both old and new contain matching keywords. With supersession,
    only the new memory is active and returned by default.
    """
    return [
        ("temporal_title", "in March the title was analyst", "in April the title became director", "what is the current title?"),
        ("knowledge_update_address", "old office is building A", "current office is building C", "what is the current office?"),
        ("knowledge_update_preference", "favorite editor used to be Helix", "current editor is Zed", "what is the current editor?"),
        ("knowledge_update_role", "previously the lead was Alex", "current lead is Bren", "who is the current lead?"),
    ]
```

3. In the benchmark runner, route those four through the memory API when `SUPERSESSION_ENABLED` is True; route them through the existing artifact-only path otherwise. The oracle that scores each scenario must look for the **new** value's substring in the returned answer.

4. Add a column to the report: `supersession_mode` (set to `enabled` or `disabled`).

- [ ] **Step 3: ⛔ DC-003 — Drift checkpoint (run with flag OFF)**

Run the benchmark with the flag off:

```bash
STELE_SUPERSESSION_ENABLED=0 .venv/bin/python -m benchmarks.longrun --backends memory,sqlite
```

Expected: the four temporal scenarios FAIL (the oracle still finds the old value somewhere in the returned snippets, since both old + new memories exist).

If the four scenarios PASS with the flag off, the test is not actually testing supersession — the oracle is too lenient. Tighten it: require the returned answer to contain the new-value substring AND NOT contain the old-value substring. Re-run, confirm fail.

- [ ] **Step 4: Run with flag ON**

```bash
STELE_SUPERSESSION_ENABLED=1 .venv/bin/python -m benchmarks.longrun --backends memory,sqlite
```

Expected: the four temporal scenarios PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/longrun.py
git commit -m "feat(benchmarks): SUPERSESSION_ENABLED flag for temporal scenarios (SC-007, DC-003 passed)"
```

---

### Task 20: Full repo-wide ruff + mypy + pytest pass

Catch anything the per-task runs missed.

- [ ] **Step 1: Run the trio**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest
```

Expected:
- ruff: clean (any new violations get auto-fixed with `.venv/bin/ruff check --fix .` then re-run)
- mypy: clean
- pytest: all tests pass; new count should be roughly 45 (baseline) + ~30 new memory tests ≈ 75+ passing

- [ ] **Step 2: Commit any cleanup**

If ruff or mypy required fixes:

```bash
git add -A
git commit -m "chore: lint and type cleanup after memory layer lands"
```

---

### Task 21: ⛔ DC-FINAL — Success Criterion coverage check

The closing gate. For each SC-XXX, point to the test that proves it.

- [ ] **Step 1: Re-read the mission brief**

```bash
cat skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md
```

- [ ] **Step 2: Map each SC to its passing test**

Run this verification:

```bash
.venv/bin/pytest \
  tests/unit/storage/test_memory_schema.py \
  tests/unit/core/test_memory_record.py \
  tests/unit/core/test_memory_add.py \
  tests/unit/core/test_memory_search.py \
  tests/unit/core/test_memory_update.py \
  tests/unit/core/test_memory_delete.py \
  tests/unit/core/test_memory_duplicates.py \
  tests/unit/core/test_memory_facade.py \
  tests/unit/core/test_memory_validation.py \
  tests/unit/pii/test_memory_scrubbing.py \
  tests/unit/test_architecture.py \
  tests/contract/test_memory_contract.py \
  -v
```

Expected: all pass.

Then assert each SC has evidence:

| SC | Evidence |
|---|---|
| SC-001 | `tests/unit/storage/test_memory_schema.py` (5 tests) + contract suite |
| SC-002 | `tests/unit/core/test_memory_add.py` (6 tests including atomicity) |
| SC-003 | `tests/unit/core/test_memory_search.py` (5 tests) + contract `test_as_of_returns_historical` |
| SC-004 | `tests/unit/core/test_memory_update.py` (2 tests) |
| SC-005 | `tests/unit/core/test_memory_delete.py` (5 tests) + contract `test_delete_excludes_from_search` |
| SC-006 | `tests/unit/core/test_memory_duplicates.py` (3 tests) |
| SC-007 | `benchmarks/longrun.py` — passes the supersession-aware oracle with flag on, fails with flag off (DC-003 verified) |
| SC-008 | `tests/contract/test_memory_contract.py` — parametrized across memory + sqlite (+ postgres if DSN set) |
| SC-009 | `tests/unit/pii/test_memory_scrubbing.py` (2 tests) |
| SC-010 | `tests/unit/core/test_memory_record.py::test_memory_record_rejects_empty_source_refs` + `test_memory_record_rejects_non_stele_source_ref` + `tests/unit/core/test_memory_validation.py` |
| SC-011 | `tests/unit/test_architecture.py` (3 tests) — facade-not-importing-storage-internals + Evolution-Boundary guard |

- [ ] **Step 3: Re-read Out of Scope — confirm none built**

```bash
grep -rn 'pg_raggraph\|pg-raggraph\|chunkshop\|MemoryExtractor' src/stele/ benchmarks/
grep -rn 'as_of\|supersedes\|effective_from\|effective_until\|retracted' src/stele/core/artifact.py
```

Expected:
- First grep: empty (or only the assertion line in `tests/unit/test_architecture.py`)
- Second grep: empty — artifact model is unmodified

- [ ] **Step 4: Final commit + tag**

```bash
git add -A
git commit -m "chore: Phase 1 complete — memory-level supersession + as_of on SQLite + Postgres

All 11 success criteria (SC-001..SC-011) have passing test evidence.
All 4 drift checkpoints (DC-001..DC-FINAL) passed.
Out-of-Scope list verified untouched.

Mission brief: skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md"

git tag phase1-memory-supersession
```

---

## Self-Review Summary

After writing this plan I re-read the mission brief and walked the checklist:

**Spec coverage.** Each SC-XXX in the brief maps to one or more tasks: SC-001 → Task 5 + contract; SC-002 → Task 6; SC-003 → Task 7 + contract; SC-004 → Task 9 + Task 10; SC-005 → Task 8 + contract; SC-006 → Task 6 + Task 11; SC-007 → Task 19; SC-008 → Task 15; SC-009 → Task 12; SC-010 → Task 2 + Task 17; SC-011 → Task 16. Each DC-XXX is an inline ⛔ checkpoint in its task: DC-001 in Task 5, DC-002 in Task 15, DC-003 in Task 19, DC-FINAL in Task 21.

**Placeholder scan.** Every code block contains actual code. No "TODO" / "TBD" / "implement later" markers. The "minimal implementation" steps show the real code that makes each test pass.

**Type consistency.** `MemoryRecord` field names, `MemoryScope` field names, `MemoryQuery` field names, and method signatures (`add(record, supersedes) -> tuple[record, list[str]]`, `search(query) -> list[record]`, etc.) are consistent across the protocol, the SQLite store, the Postgres store, the in-process store, the facade, and the tests.

**Known scope expansions.** I added `update_metadata` as a store method (Task 8) rather than a generic `update`, because SC-004 requires text edits to be impossible — having the protocol method explicitly metadata-only makes that constraint structural. The facade's `update()` still accepts both `text` and `metadata` kwargs to give the caller a clear error path.
