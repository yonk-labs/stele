# Agentic Context & Protocol Ledger: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-scope stele from an "Evolving Fact Engine" (keep atomic facts current) to an "Agentic Context & Protocol Ledger" (capture and serve the agent's non-re-derivable process history + verification protocols), beginning with a typed, schema-validated, append-only write API.

**Architecture:** An event-sourced ledger. Memories are emitted as TYPED records (decision / dead-end / completion / procedure / constraint / verification-method / observation) through a write API that enforces a per-mode schema. Ledger kinds are immutable (append-only); a reversal is a new linked record, never an overwrite. Current-state "views" are projected from the ledger (later phase). The atomic-fact-currency path is the parked experimental corner (`experimental_evolving_facts`).

**Tech Stack:** Python >=3.12, Pydantic models, hatchling, pytest, ruff, mypy --strict. Backends: memory / sqlite / postgres (the kinds drive DB CHECK constraints).

## Why (the evidence behind this re-scope)

Two real-LLM results (gemma-26B) motivate the pivot, both in `benchmarks/`:

- **The staleness trap** (`return_format.py`): under efficiency pressure a STORED stale atomic value gave 0% task accuracy, vs 100% for no-memory or for storing the verification method. Storing a re-derivable value is strictly worse than storing nothing; the model trusts it and suppresses the cheap re-check. Dating the value did not help.
- **Process-memory wins** (`process_memory.py`): with a prior decision/dead-end in memory, decision consistency was 1.0 with 0 wasted turns; without it, the agent re-investigated (open mode) or re-picked the explicitly-rejected option (forced mode, "epistemic amnesia").

Cross-model debate (gemma+qwen+codex) plus two independent reviews (Abe panel + codex second-opinion) converged: pivot to a ledger; make writes TYPED at the source (not after-the-fact classification); distinguish EVIDENCE from TRUTH; project current-state views from an append-only log; and treat scope/applicability as a first-class axis. Findings: [memory-value-thesis-2026-06-21.md](../benchmarks/findings/memory-value-thesis-2026-06-21.md).

## The two load-bearing review insights (folded into this plan)

1. **Typed emission over classification.** Both reviewers: a reliable truth-mode classifier is infeasible over arbitrary prose, but trivial if the agent emits TYPED records via mode-specific write calls with required fields, validated deterministically. LLMs draft; the schema is the authority; durable writes fail closed.
2. **Two axes, not one.** We proved Staleness (is it still true?). Abe surfaced Scope (does it apply HERE?). A valid decision from one environment misapplied to another is "procedural superstition." Every ledger record carries scope/applicability metadata.

## Global Constraints

- Python `>=3.12`; src/ layout; hatchling.
- `ruff check .` clean; `mypy --strict` over `src tests benchmarks` clean; `pytest` green before every commit.
- No em-dashes or en-dashes in prose or docs (replace with period/colon/comma/parens).
- Every memory cites evidence: `memory.add(source_refs=[...])` with `stele://` URIs; empty raises `ValidationError`.
- Ledger kinds are APPEND-ONLY: typed writers must reject `supersedes=`. Reversal = a new record linking the prior via metadata, never an overwrite.
- One public shape across backends: new `MemoryKind` values must be added to the `Literal` AND propagate to every backend's CHECK constraint, with a contract-test parameter.
- PII scrubbing inherited from `Memory.add`; never re-applied.
- Postgres is the default benchmark/integration backend; sqlite is the default durable unit/contract backend.

---

## Phased Roadmap (decomposed; each phase is its own plan after Phase 1)

| Phase | Subsystem | Why this order | Status |
|---|---|---|---|
| 1 | **Typed Memory Write API + per-mode schema (append-only)** | Both reviews' #1; everything else consumes typed records | THIS PLAN |
| 2 | **Evidence-vs-truth observations** + return-format surface (confidence/staleness/verification-method on recall) | Closes the staleness trap on the read side; small | follow-on plan |
| 3 | **Scope / applicability metadata + validity conditions** on ledger records | Abe's riskiest-assumption fix; prevents procedural superstition | follow-on plan |
| 4 | **Projection layer (event sourcing)**: current-state views from the ledger + compaction + contradiction surfacing | Prevents the append-only "landfill"; both reviews | follow-on plan |
| 5 | **Scoped, conflict-aware precedent recall** ("have we decided/tried/done X?") | The headline retrieval surface; consumes 1-4 | follow-on plan |
| 6 | **Evaluation harness** (extend the benchmarks): misclassification, scope-misapplication, contradiction, weak-model drift, harmful-recall | "Lives or dies by evals" (codex); cross-cutting | follow-on plan |

Control-plane concerns (authority levels User>System>Agent, write policy, recall-budget, deletion/redaction) are threaded through phases 2-5, not a separate phase.

---

## Phase 1: Typed Memory Write API

Phase 1 delivers `Stele.memory.record_*` typed writers that emit schema-validated, append-only ledger records. It builds only on the existing `Memory.add` and `MemoryKind`; no projection or recall changes here.

### File Structure

- Modify `src/stele/core/memory_record.py`: extend `MemoryKind` with the new ledger kinds.
- Create `src/stele/core/ledger.py`: the per-mode required-field schema + a pure `validate_ledger_record(mode, fields)` function (no I/O, deterministic).
- Modify `src/stele/core/memory.py`: add the typed `record_*` writers and append-only enforcement.
- Create `tests/unit/core/test_ledger_schema.py`: unit tests for the pure validator.
- Modify `tests/contract/test_memory_contract.py`: a contract case proving the new kinds round-trip on every backend.
- Create `tests/unit/core/test_typed_writers.py`: writer behavior + append-only rejection.

### Task 1: Extend MemoryKind with ledger kinds

**Files:**
- Modify: `src/stele/core/memory_record.py` (the `MemoryKind = Literal[...]` block)
- Test: `tests/contract/test_memory_contract.py`

**Interfaces:**
- Produces: `MemoryKind` now includes `"dead_end"`, `"completion"`, `"procedure"`, `"constraint"`, `"verification_method"` (in addition to the existing `"decision"` etc.).

- [ ] **Step 1: Write the failing contract test**

```python
# tests/contract/test_memory_contract.py  (add to the existing parametrized file)
import pytest
from stele.core.memory_record import MemoryQuery, MemoryScope

LEDGER_KINDS = ["decision", "dead_end", "completion", "procedure",
                "constraint", "verification_method"]

@pytest.mark.parametrize("kind", LEDGER_KINDS)
def test_ledger_kind_roundtrips(stele, kind):  # `stele` is the existing backend fixture
    scope = MemoryScope(namespace="ledger")
    ref = str(stele.store("evidence blob", namespace="ledger").reference)
    rec = stele.memory.add(text=f"a {kind} record", kind=kind,
                           source_refs=[ref], scope=scope).record
    got = stele.memory.get(rec.id)
    assert got is not None and got.kind == kind
```

- [ ] **Step 2: Run it, watch it fail**

Run: `.venv/bin/pytest tests/contract/test_memory_contract.py -k ledger_kind_roundtrips -q`
Expected: FAIL (CHECK constraint / Literal validation rejects the unknown kinds).

- [ ] **Step 3: Extend the Literal**

```python
# src/stele/core/memory_record.py: append inside MemoryKind = Literal[...]
    # Ledger kinds (Context & Protocol Ledger): non-re-derivable process history,
    # append-only. See docs/specs/context-protocol-ledger-plan.md.
    "dead_end",            # an approach tried that failed (with the failure reason)
    "completion",          # a task/review done ("already reviewed spec X")
    "procedure",           # learned how-to / tips / sequence for a workflow
    "constraint",          # a standing policy/limit ("never use Redis")
    "verification_method",  # how to re-derive a volatile value ("run SELECT version()")
```

- [ ] **Step 4: Run the contract test across backends**

Run: `.venv/bin/pytest tests/contract/test_memory_contract.py -k ledger_kind_roundtrips -q`
Then with Postgres: `STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele .venv/bin/pytest tests/contract/test_memory_contract.py -k ledger_kind_roundtrips -q`
Expected: PASS on memory + sqlite (+ postgres when DSN set). If a backend hardcodes the CHECK list, update its schema string so the kinds propagate.

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/memory_record.py tests/contract/test_memory_contract.py
git commit -m "feat(memory): add Context & Protocol Ledger kinds to MemoryKind"
```

### Task 2: The pure per-mode schema validator

**Files:**
- Create: `src/stele/core/ledger.py`
- Test: `tests/unit/core/test_ledger_schema.py`

**Interfaces:**
- Produces: `LEDGER_REQUIRED: dict[str, tuple[str, ...]]` and
  `validate_ledger_record(mode: str, fields: dict[str, object]) -> None` which raises
  `stele.core.exceptions.ValidationError` listing missing required fields. Non-ledger
  modes validate as a no-op.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/core/test_ledger_schema.py
import pytest
from stele.core.exceptions import ValidationError
from stele.core.ledger import LEDGER_REQUIRED, validate_ledger_record

def test_decision_requires_rationale_and_scope():
    with pytest.raises(ValidationError) as exc:
        validate_ledger_record("decision", {"summary": "use Redis"})
    assert "rationale" in str(exc.value)

def test_decision_with_required_fields_passes():
    validate_ledger_record("decision",
                           {"summary": "use Redis", "rationale": "ops overhead"})

def test_verification_method_requires_method():
    with pytest.raises(ValidationError):
        validate_ledger_record("verification_method", {"summary": "db version"})

def test_unknown_mode_is_noop():
    validate_ledger_record("fact", {})  # not a ledger mode -> no requirement
```

- [ ] **Step 2: Run it, watch it fail**

Run: `.venv/bin/pytest tests/unit/core/test_ledger_schema.py -q`
Expected: FAIL with `ModuleNotFoundError: stele.core.ledger`.

- [ ] **Step 3: Implement the validator**

```python
# src/stele/core/ledger.py
"""Deterministic per-mode schema for Context & Protocol Ledger records. No I/O,
no LLM: the typed write API is the authority, the LLM only drafts. See
docs/specs/context-protocol-ledger-plan.md."""
from __future__ import annotations

from stele.core.exceptions import ValidationError

# mode -> required field names (beyond text/source_refs/scope, which Memory.add enforces)
LEDGER_REQUIRED: dict[str, tuple[str, ...]] = {
    "decision": ("rationale",),
    "dead_end": ("failure_reason",),
    "procedure": (),
    "constraint": (),
    "completion": (),
    "verification_method": ("method",),
}


def validate_ledger_record(mode: str, fields: dict[str, object]) -> None:
    required = LEDGER_REQUIRED.get(mode)
    if required is None:
        return  # not a ledger mode
    missing = [f for f in required if not str(fields.get(f, "")).strip()]
    if missing:
        raise ValidationError(
            f"ledger mode {mode!r} requires non-empty fields: {missing}"
        )
```

- [ ] **Step 4: Run it, watch it pass**

Run: `.venv/bin/pytest tests/unit/core/test_ledger_schema.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/ledger.py tests/unit/core/test_ledger_schema.py
git commit -m "feat(ledger): deterministic per-mode required-field schema validator"
```

### Task 3: `record_decision` typed writer (append-only)

**Files:**
- Modify: `src/stele/core/memory.py` (add method on the `Memory` facade)
- Test: `tests/unit/core/test_typed_writers.py`

**Interfaces:**
- Consumes: `validate_ledger_record` (Task 2); `Memory.add` (existing).
- Produces:
  `Memory.record_decision(*, decision: str, rationale: str, source_refs: list[str], scope: MemoryScope, supersedes_decision: str | None = None, metadata: dict[str, object] | None = None) -> MemoryAddResult`.
  Stores `kind="decision"`, the rationale in `metadata["rationale"]`, and (if a prior
  decision is reversed) `metadata["reverses"] = supersedes_decision` WITHOUT calling
  `add(supersedes=...)` (append-only: the prior record stays active history).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/core/test_typed_writers.py
import tempfile
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import ValidationError
from stele.core.memory_record import MemoryQuery, MemoryScope


def _stele():
    d = tempfile.mkdtemp()
    cfg = StashConfig.model_validate({"backend": {"type": "sqlite", "path": str(Path(d) / "s.db")}})
    return Stele(cfg)


def test_record_decision_stores_rationale_and_kind():
    s = _stele()
    scope = MemoryScope(namespace="t")
    ref = str(s.store("evidence", namespace="t").reference)
    res = s.memory.record_decision(decision="standardize on Redis Streams",
                                   rationale="Kafka ops overhead too high",
                                   source_refs=[ref], scope=scope)
    rec = res.record
    assert rec.kind == "decision"
    assert rec.metadata["rationale"] == "Kafka ops overhead too high"


def test_record_decision_requires_rationale():
    s = _stele()
    scope = MemoryScope(namespace="t")
    ref = str(s.store("evidence", namespace="t").reference)
    with pytest.raises(ValidationError):
        s.memory.record_decision(decision="x", rationale="  ",
                                 source_refs=[ref], scope=scope)


def test_decision_reversal_is_append_only():
    s = _stele()
    scope = MemoryScope(namespace="t")
    ref = str(s.store("evidence", namespace="t").reference)
    first = s.memory.record_decision(decision="use Redis Streams",
                                     rationale="ops", source_refs=[ref], scope=scope)
    s.memory.record_decision(decision="use Kafka after all", rationale="scale grew",
                             source_refs=[ref], scope=scope,
                             supersedes_decision=first.record.id)
    active = s.memory.search(MemoryQuery(query="Redis Streams Kafka", scope=scope, limit=50))
    # BOTH the original decision and its reversal remain active history.
    assert len(active) == 2
    reversal = next(m for m in active if m.metadata.get("reverses"))
    assert reversal.metadata["reverses"] == first.record.id
```

- [ ] **Step 2: Run it, watch it fail**

Run: `.venv/bin/pytest tests/unit/core/test_typed_writers.py -q`
Expected: FAIL with `AttributeError: 'Memory' object has no attribute 'record_decision'`.

- [ ] **Step 3: Implement the writer**

```python
# src/stele/core/memory.py: add to the Memory class, and at top:
# from stele.core.ledger import validate_ledger_record

    def record_decision(
        self,
        *,
        decision: str,
        rationale: str,
        source_refs: list[str],
        scope: MemoryScope,
        supersedes_decision: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        """Append a decision to the ledger (immutable). A reversal links the prior
        decision via metadata['reverses'] and does NOT supersede it: the original
        decision stays active history so 'did we decide X / why' is always answerable
        (avoids epistemic amnesia). See docs/specs/context-protocol-ledger-plan.md."""
        validate_ledger_record("decision", {"summary": decision, "rationale": rationale})
        meta = dict(metadata or {})
        meta["rationale"] = rationale
        if supersedes_decision is not None:
            meta["reverses"] = supersedes_decision
        return self.add(text=decision, kind="decision", source_refs=source_refs,
                        scope=scope, summary=decision, metadata=meta)
```

- [ ] **Step 4: Run it, watch it pass**

Run: `.venv/bin/pytest tests/unit/core/test_typed_writers.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/memory.py tests/unit/core/test_typed_writers.py
git commit -m "feat(ledger): record_decision typed writer (append-only, reversal links prior)"
```

### Task 4: `record_dead_end` and `record_verification_method` writers

**Files:**
- Modify: `src/stele/core/memory.py`
- Test: `tests/unit/core/test_typed_writers.py`

**Interfaces:**
- Produces:
  `Memory.record_dead_end(*, approach: str, failure_reason: str, source_refs, scope, metadata=None) -> MemoryAddResult` (kind `"dead_end"`, `metadata["failure_reason"]`).
  `Memory.record_verification_method(*, subject: str, method: str, source_refs, scope, metadata=None) -> MemoryAddResult` (kind `"verification_method"`, `metadata["method"]`, `metadata["subject"]`).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/core/test_typed_writers.py
def test_record_dead_end_stores_failure_reason():
    s = _stele()
    scope = MemoryScope(namespace="t")
    ref = str(s.store("evidence", namespace="t").reference)
    rec = s.memory.record_dead_end(approach="single global lock",
                                   failure_reason="deadlocks under load",
                                   source_refs=[ref], scope=scope).record
    assert rec.kind == "dead_end"
    assert rec.metadata["failure_reason"] == "deadlocks under load"


def test_record_verification_method_stores_method():
    s = _stele()
    scope = MemoryScope(namespace="t")
    ref = str(s.store("evidence", namespace="t").reference)
    rec = s.memory.record_verification_method(subject="postgres version",
                                              method="run SELECT version()",
                                              source_refs=[ref], scope=scope).record
    assert rec.kind == "verification_method"
    assert rec.metadata["method"] == "run SELECT version()"
```

- [ ] **Step 2: Run, watch fail**

Run: `.venv/bin/pytest tests/unit/core/test_typed_writers.py -k "dead_end or verification" -q`
Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Implement both writers**

```python
# src/stele/core/memory.py: add to the Memory class
    def record_dead_end(
        self, *, approach: str, failure_reason: str,
        source_refs: list[str], scope: MemoryScope,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        """Append a tried-and-failed approach so it is not re-attempted."""
        validate_ledger_record("dead_end",
                               {"summary": approach, "failure_reason": failure_reason})
        meta = dict(metadata or {}); meta["failure_reason"] = failure_reason
        return self.add(text=approach, kind="dead_end", source_refs=source_refs,
                        scope=scope, summary=approach, metadata=meta)

    def record_verification_method(
        self, *, subject: str, method: str,
        source_refs: list[str], scope: MemoryScope,
        metadata: dict[str, object] | None = None,
    ) -> MemoryAddResult:
        """Store HOW to re-derive a volatile value instead of the value itself
        (the staleness-trap fix). See benchmarks/return_format.py."""
        validate_ledger_record("verification_method",
                               {"summary": subject, "method": method})
        meta = dict(metadata or {}); meta["method"] = method; meta["subject"] = subject
        return self.add(text=f"to verify {subject}: {method}",
                        kind="verification_method", source_refs=source_refs,
                        scope=scope, summary=subject, metadata=meta)
```

- [ ] **Step 4: Run, watch pass**

Run: `.venv/bin/pytest tests/unit/core/test_typed_writers.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/memory.py tests/unit/core/test_typed_writers.py
git commit -m "feat(ledger): record_dead_end + record_verification_method writers"
```

### Task 5: Append-only guard for ledger kinds

**Files:**
- Modify: `src/stele/core/memory.py` (the existing `add` method)
- Test: `tests/unit/core/test_typed_writers.py`

**Interfaces:**
- Produces: `Memory.add(...)` raises `ValidationError` when `kind` is a ledger kind AND
  `supersedes` is non-empty. Ledger history is never overwritten; reversals link via
  metadata (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/core/test_typed_writers.py
def test_add_rejects_supersede_on_ledger_kind():
    s = _stele()
    scope = MemoryScope(namespace="t")
    ref = str(s.store("evidence", namespace="t").reference)
    first = s.memory.record_decision(decision="a", rationale="r",
                                     source_refs=[ref], scope=scope)
    with pytest.raises(ValidationError):
        s.memory.add(text="b", kind="decision", source_refs=[ref], scope=scope,
                     supersedes=[first.record.id])
```

- [ ] **Step 2: Run, watch fail**

Run: `.venv/bin/pytest tests/unit/core/test_typed_writers.py -k supersede_on_ledger -q`
Expected: FAIL (no guard yet, the add succeeds).

- [ ] **Step 3: Add the guard at the top of `add`**

```python
# src/stele/core/memory.py: inside add(), before building the record
        from stele.core.ledger import LEDGER_REQUIRED
        if supersedes and kind in LEDGER_REQUIRED:
            raise ValidationError(
                f"ledger kind {kind!r} is append-only; record a new linked entry "
                f"instead of superseding (see record_decision reversal pattern)"
            )
```

- [ ] **Step 4: Run the full typed-writer + ledger + contract subset**

Run: `.venv/bin/pytest tests/unit/core/test_typed_writers.py tests/unit/core/test_ledger_schema.py tests/contract/test_memory_contract.py -q`
Expected: PASS. Then `.venv/bin/ruff check . && .venv/bin/mypy src tests`.

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/memory.py tests/unit/core/test_typed_writers.py
git commit -m "feat(ledger): enforce append-only on ledger kinds in Memory.add"
```

### Phase 1 exit gate

- `record_decision` / `record_dead_end` / `record_verification_method` exist, validate required fields (fail closed), and are append-only.
- Decision reversal links the prior record without superseding it (both stay active).
- New ledger kinds round-trip on memory + sqlite (+ postgres when DSN set).
- `ruff` + `mypy --strict` clean; full unit + memory/sqlite contract suites green.

---

## Self-review notes

- Spec coverage: Phase 1 covers the typed-write API + append-only fence (both reviews' #1). Evidence-vs-truth (Phase 2), scope/applicability (Phase 3), projection views (Phase 4), precedent recall (Phase 5), evals (Phase 6) are explicitly carried as follow-on plans, not dropped.
- The `observation`/evidence mode and the recall-side return-format surface are deferred to Phase 2 on purpose (they touch recall, a different subsystem).
- Open question for Phase 1 review: whether `dead_end`/`procedure`/`constraint`/`completion` should be new `MemoryKind` values (chosen here, additive) or a `mode` metadata field over existing kinds. The kind approach gives DB-level CHECK validation and clean recall filtering; the cost is the cross-backend CHECK propagation in Task 1.
