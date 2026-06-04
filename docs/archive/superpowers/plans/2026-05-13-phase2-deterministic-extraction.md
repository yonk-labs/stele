# Stele Phase 2: Deterministic Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Stele's deterministic extraction layer so callers can turn text (artifacts, agent-message threads, raw input) into accepted `MemoryRecord` rows with full provenance, classification, and an audit-grade `ExtractionReport` — without any LLM or embeddings.

**Architecture:** Pure deterministic core (`extract_candidates`) + thin I/O orchestrator (`MemoryExtractor`). Built on `lede.extract.{key_facts, stats, metadata, phrases}` + `lede.summarize`. Three entry points on `Stele.extract` (`from_artifact`, `from_messages`, `from_text`) all funnel through the same pure core. Type-based classifier maps lede output types to `MemoryKind`; regex pattern overlay overrides for the agent-loop kinds (preference/decision/instruction/commitment/issue). Confidence threshold filtering lives in the orchestrator so Phase 3's `RecallPolicy` can inspect candidates pre-filter.

**Tech Stack:** Python 3.12+, Pydantic v2, `lede` (already a runtime dep), `Memory` from Phase 1, `RegexPIIScrubber` from Phase 1, pytest, ruff, mypy strict, uv-managed venv.

**Spec (load-bearing):** [`docs/superpowers/specs/2026-05-13-phase2-deterministic-extraction-design.md`](../specs/2026-05-13-phase2-deterministic-extraction-design.md)

Re-read the spec at every DC-XXX checkpoint below. All 18 success criteria (SC-001 through SC-018) must have evidence at DC-FINAL.

**Phase 1 dependency:** This plan assumes Phase 1 Tasks 0–21 are complete (the full memory contract is shipped on memory + sqlite + postgres, MariaDB/ClickHouse raise `CapabilityError`). Task 0 verifies the precondition.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/stele/extraction/__init__.py` | Re-exports `MemoryCandidate`, `AcceptedCandidate`, `RejectedCandidate`, `ExtractionStats`, `ExtractionReport` |
| `src/stele/extraction/models.py` | All pydantic models |
| `src/stele/extraction/patterns.py` | Regex packs for the agent-loop kinds (`preference`, `decision`, `instruction`, `commitment`, `issue`) with `kind_weight` |
| `src/stele/extraction/classifier.py` | PURE: `classify_kind(text, lede_source) -> ClassifierOutput`; type-based default + pattern overlay |
| `src/stele/extraction/candidates.py` | PURE: `extract_candidates(text, source_refs, scrubber) -> list[MemoryCandidate]` — wraps `lede.extract.{key_facts, stats, metadata, phrases}` + `lede.summarize` |
| `src/stele/extraction/extractor.py` | `MemoryExtractor` I/O orchestrator — `from_artifact`, `from_messages`, `from_text` |
| `tests/unit/extraction/__init__.py` | Package marker |
| `tests/unit/extraction/test_models.py` | Model field validation, frozen-ness, default values |
| `tests/unit/extraction/test_patterns.py` | Regex pack coverage across 5 fixture kinds |
| `tests/unit/extraction/test_classifier.py` | Type-based defaults + pattern overlay tie-break |
| `tests/unit/extraction/test_candidates.py` | Pure-core determinism, lede mapping, scrubber integration |
| `tests/unit/extraction/test_extractor.py` | Orchestrator: three entry points, threshold/duplicate/validation rejection paths |
| `tests/unit/extraction/test_abstention.py` | Pure-noise inputs return empty `accepted` |
| `tests/unit/extraction/test_pii_invariant.py` | Double-scrub idempotence + PII fixture pass-through |
| `tests/contract/test_extraction_contract.py` | Cross-backend extraction (memory + sqlite + postgres) |
| `tests/fixtures/extraction/preferences.json` | ≥3 positive + ≥3 abstention samples |
| `tests/fixtures/extraction/decisions.json` | Same |
| `tests/fixtures/extraction/commitments.json` | Same |
| `tests/fixtures/extraction/changed_facts.json` | Same |
| `tests/fixtures/extraction/abstention.json` | Pure-noise inputs |
| `scripts/demo-extraction.sh` | Human-readable demo proving all five fixture categories |

### Modified files

| Path | Change |
|---|---|
| `src/stele/core/config.py` | Add `ExtractionConfig` model + `extraction: ExtractionConfig` on `StashConfig` |
| `src/stele/core/stash.py` | Add `Stele.extract` property; wire `_extractor` into `Stele.close()` |
| `src/stele/__init__.py` | Re-export `MemoryCandidate`, `AcceptedCandidate`, `RejectedCandidate`, `ExtractionStats`, `ExtractionReport` |

### Untouched files (locked)

| Path | Why locked |
|---|---|
| `src/stele/core/memory.py` | Phase 1's contract; extraction consumes it via the public facade only |
| `src/stele/core/memory_record.py` | Models are Phase 1's source of truth |
| `src/stele/storage/memory_store/*` | Phase 2 never touches `MemoryStore` directly — only through `Memory.add()` |
| `src/stele/pii/*` | Scrubber is consumed, not modified |
| `src/stele/summary/lede_adapter.py` | Lede summary adapter is the precedent; do not modify |

---

## Drift Checkpoints (hard gates from the spec)

- ⛔ **DC-000** (Task 0): Phase 1 must be complete. Run the verification command; if any assertion fails, STOP.
- ⛔ **DC-001** (after Task 6): re-read spec → run `grep -rn 'pg_raggraph\|chunkshop\|RecallPolicy\|SourceConnector\|UniversalSearch' src/stele/extraction/`. Expected: empty. If anything matches, the slice has drifted into Phase 3+.
- ⛔ **DC-002** (after Task 5): re-read spec → run the overlay-disabled regression test (`test_classifier.py::test_overlay_disabled`). Every agent-loop fixture must fall back to `kind="fact"`. If any retains its agent-loop kind, the flag isn't actually gating behavior.
- ⛔ **DC-003** (after Task 17): re-read spec → run `grep -rn 'MemoryStore\|_store\.' src/stele/extraction/`. Expected: empty. If matched, extraction is bypassing the `Memory` facade.
- ⛔ **DC-FINAL** (Task 23): every SC-001..SC-018 has a passing test cited; the Out-of-Scope list is verified untouched.

---

## Tasks

### Task 0: Verify Phase 1 prerequisites

Phase 2 assumes the full Phase 1 surface ships first. Confirm before touching anything.

**Files:**
- Read-only: `docs/current-status.md`, `src/stele/core/memory.py`, `tests/contract/test_memory_contract.py`

- [ ] **Step 1: Confirm working tree is clean (or at least understood)**

```bash
cd /home/yonk/yonk-tools/stele
git status --short
```

Expected: ideally empty. If `benchmarks/longrun.py` shows ` M` it means Phase 1 Task 19 is in flight. Stop and complete Phase 1 first.

- [ ] **Step 2: Run the Phase 1 verification trio**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest
```

Expected: all three pass. Note the pytest pass count for the DC-FINAL diff.

- [ ] **Step 3: Confirm the Phase 1 contract is shipped on the three required backends**

```bash
.venv/bin/pytest tests/contract/test_memory_contract.py -v --no-header 2>&1 | tail -30
```

Expected: parametrized runs against `memory`, `sqlite`, and (when `STELE_PG_DSN` is set) `postgres`. All pass.

- [ ] **Step 4: Confirm the public Memory facade exposes everything Phase 2 needs**

```bash
.venv/bin/python -c "
from stele import Memory, MemoryAddResult, MemoryRecord, MemoryScope
from stele.core.exceptions import CapabilityError, ValidationError, ArtifactNotFound
from stele.core.memory import Memory as _M
import inspect
sig = inspect.signature(_M.add)
print('Memory.add signature:', sig)
print('Memory has search:', hasattr(_M, 'search'))
print('Memory has get:', hasattr(_M, 'get'))
print('Memory has close:', hasattr(_M, 'close'))
"
```

Expected: signature lists `text`, `kind`, `source_refs`, `scope`, `supersedes`, `confidence`, `metadata`. All `hasattr` lines print `True`.

- [ ] **Step 5: Create the Phase 2 working branch**

```bash
git switch -c phase2-deterministic-extraction
git log --oneline -5
```

Expected: branch created from the current `main`; the last commit is the Phase 2 spec (`docs(phase2): design spec for deterministic extraction`).

No code commit in Task 0. Move to Task 1.

---

### Task 1: Add `ExtractionConfig` to `core/config.py`

The orchestrator reads thresholds and toggles from config. Defaults are picked so the fixtures pass without tuning.

**Files:**
- Modify: `src/stele/core/config.py`
- Test: `tests/unit/core/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_config.py`:

```python
def test_extraction_config_defaults() -> None:
    from stele.core.config import ExtractionConfig, StashConfig

    cfg = StashConfig()
    assert cfg.extraction.enabled is True
    assert cfg.extraction.min_confidence == 0.6
    assert cfg.extraction.max_candidates_per_doc == 50
    assert cfg.extraction.overlay_patterns_enabled is True
    assert cfg.extraction.summary_kind == "summary"
    assert cfg.extraction.auto_stash_messages is True


def test_extraction_config_override_via_dict() -> None:
    from stele.core.config import StashConfig

    cfg = StashConfig.load({"extraction": {"min_confidence": 0.8, "enabled": False}})
    assert cfg.extraction.enabled is False
    assert cfg.extraction.min_confidence == 0.8
    assert cfg.extraction.overlay_patterns_enabled is True  # unchanged default
```

- [ ] **Step 2: Run the test, confirm it fails**

```bash
.venv/bin/pytest tests/unit/core/test_config.py::test_extraction_config_defaults -v
```

Expected: `FAILED` with `AttributeError: 'StashConfig' object has no attribute 'extraction'`.

- [ ] **Step 3: Add `ExtractionConfig` and wire it onto `StashConfig`**

In `src/stele/core/config.py`, add this class right before `class StashConfig` (after `SigningConfig`):

```python
class ExtractionConfig(BaseModel):
    enabled: bool = True
    min_confidence: float = 0.6
    max_candidates_per_doc: int = 50
    overlay_patterns_enabled: bool = True
    summary_kind: Literal[
        "fact",
        "preference",
        "decision",
        "instruction",
        "commitment",
        "issue",
        "summary",
    ] = "summary"
    auto_stash_messages: bool = True
```

Then add a field on `StashConfig` (between `signing` and the `load` classmethod):

```python
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
.venv/bin/pytest tests/unit/core/test_config.py -v -k extraction_config
```

Expected: both `test_extraction_config_*` tests PASS.

- [ ] **Step 5: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/core/config.py tests/unit/core/test_config.py
.venv/bin/mypy src/stele/core/config.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/stele/core/config.py tests/unit/core/test_config.py
git commit -m "feat(config): add ExtractionConfig with phase-2 defaults"
```

---

### Task 2: Extraction models in `extraction/models.py`

Define the five report-shape models that downstream tasks reference.

**Files:**
- Create: `src/stele/extraction/__init__.py`
- Create: `src/stele/extraction/models.py`
- Create: `tests/unit/extraction/__init__.py`
- Test: `tests/unit/extraction/test_models.py`

- [ ] **Step 1: Create package markers**

```bash
mkdir -p src/stele/extraction tests/unit/extraction
: > src/stele/extraction/__init__.py
: > tests/unit/extraction/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/extraction/test_models.py`:

```python
"""Tests for extraction models — field validation and defaults."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.extraction.models import (
    AcceptedCandidate,
    ExtractionReport,
    ExtractionStats,
    MemoryCandidate,
    RejectedCandidate,
)


def test_memory_candidate_required_fields() -> None:
    cand = MemoryCandidate(
        text="users prefer dark mode",
        kind="preference",
        confidence=0.85,
        lede_source="key_fact",
        classifier_path="pattern_overlay",
        pattern_match="preference",
    )
    assert cand.text == "users prefer dark mode"
    assert cand.kind == "preference"
    assert cand.confidence == 0.85
    assert cand.lede_source == "key_fact"
    assert cand.classifier_path == "pattern_overlay"
    assert cand.pattern_match == "preference"


def test_memory_candidate_pattern_match_optional() -> None:
    cand = MemoryCandidate(
        text="The capital is Paris.",
        kind="fact",
        confidence=0.7,
        lede_source="key_fact",
        classifier_path="type_based",
    )
    assert cand.pattern_match is None


def test_memory_candidate_rejects_unknown_kind() -> None:
    with pytest.raises(PydanticValidationError):
        MemoryCandidate(
            text="x",
            kind="not_a_kind",  # type: ignore[arg-type]
            confidence=0.5,
            lede_source="key_fact",
            classifier_path="type_based",
        )


def test_accepted_candidate_carries_stored_id() -> None:
    cand = MemoryCandidate(
        text="x",
        kind="fact",
        confidence=0.8,
        lede_source="stat",
        classifier_path="type_based",
    )
    acc = AcceptedCandidate(candidate=cand, stored_id="mem_abc123")
    assert acc.stored_id == "mem_abc123"
    assert acc.candidate.text == "x"


def test_rejected_candidate_with_duplicate_reason() -> None:
    cand = MemoryCandidate(
        text="x",
        kind="fact",
        confidence=0.8,
        lede_source="stat",
        classifier_path="type_based",
    )
    rej = RejectedCandidate(candidate=cand, reason="duplicate", duplicate_of="mem_old")
    assert rej.reason == "duplicate"
    assert rej.duplicate_of == "mem_old"
    assert rej.error_message is None


def test_rejected_candidate_with_validation_error() -> None:
    cand = MemoryCandidate(
        text="x",
        kind="fact",
        confidence=0.8,
        lede_source="stat",
        classifier_path="type_based",
    )
    rej = RejectedCandidate(
        candidate=cand,
        reason="validation_error",
        error_message="some pydantic complaint",
    )
    assert rej.reason == "validation_error"
    assert rej.error_message == "some pydantic complaint"


def test_extraction_stats_defaults_to_zero() -> None:
    stats = ExtractionStats(candidate_count=0, accepted_count=0, rejected_count=0)
    assert stats.candidate_count == 0
    assert stats.accepted_count == 0


def test_extraction_report_empty_run() -> None:
    report = ExtractionReport(
        candidates=[],
        accepted=[],
        rejected=[],
        pii_flags=[],
        source_refs=["stele://default/abc"],
        stats=ExtractionStats(candidate_count=0, accepted_count=0, rejected_count=0),
        config_fingerprint="x" * 64,
    )
    assert report.candidates == []
    assert report.accepted == []
    assert report.source_refs == ["stele://default/abc"]
```

- [ ] **Step 3: Run the test, confirm it fails**

```bash
.venv/bin/pytest tests/unit/extraction/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'stele.extraction.models'`.

- [ ] **Step 4: Implement `models.py`**

Create `src/stele/extraction/models.py`:

```python
"""Extraction report shapes — single source of truth."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from stele.core.memory_record import MemoryKind

LedeSource = Literal["key_fact", "stat", "metadata", "phrase", "summary"]
ClassifierPath = Literal["type_based", "pattern_overlay"]
RejectionReason = Literal["below_threshold", "duplicate", "validation_error"]


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    kind: MemoryKind
    confidence: float
    lede_source: LedeSource
    classifier_path: ClassifierPath
    pattern_match: str | None = None


class AcceptedCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: MemoryCandidate
    stored_id: str


class RejectedCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: MemoryCandidate
    reason: RejectionReason
    duplicate_of: str | None = None
    error_message: str | None = None


class ExtractionStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_count: int
    accepted_count: int
    rejected_count: int


class ExtractionReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: list[MemoryCandidate]
    accepted: list[AcceptedCandidate]
    rejected: list[RejectedCandidate]
    pii_flags: list[str] = Field(default_factory=list)
    source_refs: list[str]
    stats: ExtractionStats
    config_fingerprint: str
```

- [ ] **Step 5: Wire up the package `__init__.py`**

Overwrite `src/stele/extraction/__init__.py`:

```python
"""Phase 2 — deterministic extraction."""

from stele.extraction.models import (
    AcceptedCandidate,
    ClassifierPath,
    ExtractionReport,
    ExtractionStats,
    LedeSource,
    MemoryCandidate,
    RejectedCandidate,
    RejectionReason,
)

__all__ = [
    "AcceptedCandidate",
    "ClassifierPath",
    "ExtractionReport",
    "ExtractionStats",
    "LedeSource",
    "MemoryCandidate",
    "RejectedCandidate",
    "RejectionReason",
]
```

- [ ] **Step 6: Run the test, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_models.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 7: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/extraction tests/unit/extraction
.venv/bin/mypy src/stele/extraction tests/unit/extraction
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/stele/extraction/__init__.py src/stele/extraction/models.py \
        tests/unit/extraction/__init__.py tests/unit/extraction/test_models.py
git commit -m "feat(extraction): add MemoryCandidate + ExtractionReport models (SC-001)"
```

---

### Task 3: Regex pattern packs in `extraction/patterns.py`

The pattern overlay's static data. Tested independently before the classifier uses it.

**Files:**
- Create: `src/stele/extraction/patterns.py`
- Test: `tests/unit/extraction/test_patterns.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/extraction/test_patterns.py`:

```python
"""Tests for the regex pattern packs."""

from __future__ import annotations

import pytest

from stele.extraction.patterns import (
    PATTERN_PACKS,
    PatternPack,
    match_first_kind,
)


def test_pattern_pack_kind_weights_in_range() -> None:
    for pack in PATTERN_PACKS:
        assert 0.0 < pack.kind_weight <= 1.0, pack.kind


def test_pattern_pack_declaration_order_is_stable() -> None:
    kinds = [p.kind for p in PATTERN_PACKS]
    assert kinds == [
        "preference",
        "decision",
        "commitment",
        "instruction",
        "issue",
    ]


@pytest.mark.parametrize(
    "text,expected_kind",
    [
        ("I prefer dark mode over light mode.", "preference"),
        ("I like Helix more than Vim.", "preference"),
        ("My favorite editor is Zed.", "preference"),
        ("We decided to switch to RBAC.", "decision"),
        ("Let's go with PostgreSQL for now.", "decision"),
        ("I'll send the report by Friday.", "commitment"),
        ("TODO: rewrite the auth middleware.", "commitment"),
        ("Please always use parameterized queries.", "instruction"),
        ("Never commit the .env file.", "instruction"),
        ("The login page is broken on Safari.", "issue"),
        ("Crash on startup with empty config.", "issue"),
    ],
)
def test_match_first_kind_positive(text: str, expected_kind: str) -> None:
    result = match_first_kind(text)
    assert result is not None
    assert result.kind == expected_kind


@pytest.mark.parametrize(
    "text",
    [
        "The capital of France is Paris.",
        "Population: 67 million.",
        "Q3 revenue grew 12 percent year over year.",
        "",
        "   ",
        "lorem ipsum dolor sit amet",
    ],
)
def test_match_first_kind_abstention(text: str) -> None:
    assert match_first_kind(text) is None


def test_pattern_pack_dataclass_fields() -> None:
    pack = PATTERN_PACKS[0]
    assert isinstance(pack, PatternPack)
    assert pack.kind == "preference"
    assert pack.kind_weight > 0
    assert len(pack.patterns) > 0
```

- [ ] **Step 2: Run the test, confirm it fails**

```bash
.venv/bin/pytest tests/unit/extraction/test_patterns.py -v
```

Expected: `ModuleNotFoundError: No module named 'stele.extraction.patterns'`.

- [ ] **Step 3: Implement `patterns.py`**

Create `src/stele/extraction/patterns.py`:

```python
"""Regex pattern packs for the pattern-overlay classifier.

Each pack is a (kind, kind_weight, patterns) bundle. Matching is set-membership:
a kind matches if any pattern in its pack matches. Across kinds, declaration
order in this file is the deterministic tie-break.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stele.core.memory_record import MemoryKind


@dataclass(frozen=True)
class PatternPack:
    kind: MemoryKind
    kind_weight: float
    patterns: tuple[re.Pattern[str], ...]


def _compile(*sources: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(s) for s in sources)


PREFERENCE = PatternPack(
    kind="preference",
    kind_weight=0.85,
    patterns=_compile(
        r"(?i)\bi\s+(prefer|like|love|hate|dislike|enjoy)\b",
        r"(?i)\bmy\s+favou?rite\b",
        r"(?i)\bi(?:'m|\s+am)\s+(?:not\s+)?a\s+fan\s+of\b",
    ),
)

DECISION = PatternPack(
    kind="decision",
    kind_weight=0.85,
    patterns=_compile(
        r"(?i)\b(we|i)('ve|\s+have)?\s+decided\b",
        r"(?i)\blet'?s\s+go\s+with\b",
        r"(?i)\bwe(?:'re|\s+are)?\s+going\s+to\b",
        r"(?i)\bdecision\s*:\s*\S",
    ),
)

COMMITMENT = PatternPack(
    kind="commitment",
    kind_weight=0.75,
    patterns=_compile(
        r"(?i)\b(by|before)\s+\w+day\b",
        r"(?i)\b(TODO|FIXME)\b",
        r"(?i)\bi('ll|\s+will)\s+\w+",
        r"(?i)\bdue\s+(by|on)\b",
    ),
)

INSTRUCTION = PatternPack(
    kind="instruction",
    kind_weight=0.75,
    patterns=_compile(
        r"(?i)\b(please|always|never|don'?t)\b.*\b(do|use|avoid|commit|skip|run)\b",
        r"(?i)\b(always|never)\s+\w+",
    ),
)

ISSUE = PatternPack(
    kind="issue",
    kind_weight=0.65,
    patterns=_compile(
        r"(?i)\b(bug|broken|fails?|error|crash(?:es|ed|ing)?)\b",
        r"(?i)\bdoesn'?t\s+work\b",
        r"(?i)\bregression\b",
    ),
)

# Declaration order = deterministic tie-break across kinds.
PATTERN_PACKS: tuple[PatternPack, ...] = (
    PREFERENCE,
    DECISION,
    COMMITMENT,
    INSTRUCTION,
    ISSUE,
)


def match_first_kind(text: str) -> PatternPack | None:
    """Return the highest-priority matching pack, or None.

    Tie-break: highest kind_weight wins; on equal weight, declaration order
    in PATTERN_PACKS wins.
    """
    matches: list[PatternPack] = []
    for pack in PATTERN_PACKS:
        for pattern in pack.patterns:
            if pattern.search(text):
                matches.append(pack)
                break  # one pattern in the pack is enough; move to next pack
    if not matches:
        return None
    # Sort by (-kind_weight, declaration_index). Stable sort preserves
    # PATTERN_PACKS order for ties.
    index_of = {pack: i for i, pack in enumerate(PATTERN_PACKS)}
    matches.sort(key=lambda p: (-p.kind_weight, index_of[p]))
    return matches[0]
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_patterns.py -v
```

Expected: all parametrized tests PASS.

- [ ] **Step 5: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/extraction/patterns.py tests/unit/extraction/test_patterns.py
.venv/bin/mypy src/stele/extraction/patterns.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/stele/extraction/patterns.py tests/unit/extraction/test_patterns.py
git commit -m "feat(extraction): regex pattern packs for agent-loop kinds (SC-007)"
```

---

### Task 4: Type-based classifier defaults in `extraction/classifier.py`

The classifier produces `(kind, confidence, classifier_path, pattern_match)`. Type-based defaults come first; overlay layers on top in Task 5.

**Files:**
- Create: `src/stele/extraction/classifier.py`
- Test: `tests/unit/extraction/test_classifier.py`

- [ ] **Step 1: Write the failing test (type-based only)**

Create `tests/unit/extraction/test_classifier.py`:

```python
"""Tests for the type-based classifier defaults."""

from __future__ import annotations

import pytest

from stele.extraction.classifier import ClassifierOutput, classify_kind


@pytest.mark.parametrize(
    "lede_source,expected_kind,expected_confidence",
    [
        ("key_fact", "fact", 0.7),
        ("stat", "fact", 0.8),
        ("metadata", "fact", 0.7),
        ("phrase", "fact", 0.5),
        ("summary", "summary", 0.9),
    ],
)
def test_type_based_defaults(
    lede_source: str, expected_kind: str, expected_confidence: float
) -> None:
    out = classify_kind(
        text="The capital of France is Paris.",
        lede_source=lede_source,  # type: ignore[arg-type]
        overlay_enabled=False,
    )
    assert out.kind == expected_kind
    assert out.confidence == pytest.approx(expected_confidence)
    assert out.classifier_path == "type_based"
    assert out.pattern_match is None


def test_classifier_output_is_frozen() -> None:
    out = classify_kind(
        text="x",
        lede_source="stat",
        overlay_enabled=False,
    )
    with pytest.raises(Exception):
        out.kind = "preference"  # type: ignore[misc]
```

- [ ] **Step 2: Run the test, confirm it fails**

```bash
.venv/bin/pytest tests/unit/extraction/test_classifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'stele.extraction.classifier'`.

- [ ] **Step 3: Implement the classifier (type-based path only)**

Create `src/stele/extraction/classifier.py`:

```python
"""Pure classifier: lede output type → MemoryKind, with optional pattern overlay."""

from __future__ import annotations

from dataclasses import dataclass

from stele.core.memory_record import MemoryKind
from stele.extraction.models import ClassifierPath, LedeSource

_TYPE_BASED_DEFAULTS: dict[LedeSource, tuple[MemoryKind, float]] = {
    "key_fact": ("fact", 0.7),
    "stat": ("fact", 0.8),
    "metadata": ("fact", 0.7),
    "phrase": ("fact", 0.5),
    "summary": ("summary", 0.9),
}


@dataclass(frozen=True)
class ClassifierOutput:
    kind: MemoryKind
    confidence: float
    classifier_path: ClassifierPath
    pattern_match: str | None


def classify_kind(
    *,
    text: str,
    lede_source: LedeSource,
    overlay_enabled: bool,
) -> ClassifierOutput:
    """Deterministically classify a candidate's kind.

    The lede output type provides a default kind + confidence. When
    overlay_enabled is True, a regex pack may override the default with a
    higher-confidence agent-loop kind.

    Args are keyword-only so callers can't accidentally swap text and
    lede_source.
    """
    default_kind, default_confidence = _TYPE_BASED_DEFAULTS[lede_source]
    if not overlay_enabled:
        return ClassifierOutput(
            kind=default_kind,
            confidence=default_confidence,
            classifier_path="type_based",
            pattern_match=None,
        )
    # Overlay layer arrives in Task 5; for now, stub to type-based.
    return ClassifierOutput(
        kind=default_kind,
        confidence=default_confidence,
        classifier_path="type_based",
        pattern_match=None,
    )
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_classifier.py -v
```

Expected: 6 parametrized cases + frozen test PASS.

- [ ] **Step 5: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/extraction/classifier.py
.venv/bin/mypy src/stele/extraction/classifier.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/stele/extraction/classifier.py tests/unit/extraction/test_classifier.py
git commit -m "feat(extraction): type-based classifier defaults (SC-004, SC-006)"
```

---

### Task 5: Pattern overlay in classifier + DC-002

Layer the regex overlay onto `classify_kind`. After this task, run DC-002.

**Files:**
- Modify: `src/stele/extraction/classifier.py`
- Test: `tests/unit/extraction/test_classifier.py` (append)

- [ ] **Step 1: Write failing tests for the overlay**

Append to `tests/unit/extraction/test_classifier.py`:

```python
def test_overlay_wins_when_pattern_matches_with_higher_weight() -> None:
    out = classify_kind(
        text="I prefer dark mode.",
        lede_source="key_fact",  # default confidence 0.7
        overlay_enabled=True,
    )
    assert out.kind == "preference"
    assert out.confidence == pytest.approx(0.85)
    assert out.classifier_path == "pattern_overlay"
    assert out.pattern_match == "preference"


def test_overlay_loses_when_default_confidence_already_higher() -> None:
    # summary defaults to 0.9; issue weight is only 0.65, so overlay must
    # not override.
    out = classify_kind(
        text="The login page is broken.",
        lede_source="summary",
        overlay_enabled=True,
    )
    assert out.kind == "summary"
    assert out.confidence == pytest.approx(0.9)
    assert out.classifier_path == "type_based"


def test_overlay_tie_break_by_declaration_order() -> None:
    # "we decided to do it by Friday" matches both decision (0.85) and
    # commitment (0.75). decision wins on higher kind_weight.
    out = classify_kind(
        text="We decided to ship it by Friday.",
        lede_source="key_fact",
        overlay_enabled=True,
    )
    assert out.kind == "decision"
    assert out.pattern_match == "decision"


def test_overlay_disabled_falls_back_to_type_based() -> None:
    # Same text as the first overlay test, but with the flag off.
    out = classify_kind(
        text="I prefer dark mode.",
        lede_source="key_fact",
        overlay_enabled=False,
    )
    assert out.kind == "fact"
    assert out.classifier_path == "type_based"
    assert out.pattern_match is None
```

- [ ] **Step 2: Run, confirm new tests fail**

```bash
.venv/bin/pytest tests/unit/extraction/test_classifier.py -v -k overlay
```

Expected: the four overlay tests FAIL.

- [ ] **Step 3: Implement the overlay in `classify_kind`**

Replace the stub at the bottom of `classify_kind` with real overlay logic.
The final function body in `src/stele/extraction/classifier.py` should be:

```python
def classify_kind(
    *,
    text: str,
    lede_source: LedeSource,
    overlay_enabled: bool,
) -> ClassifierOutput:
    default_kind, default_confidence = _TYPE_BASED_DEFAULTS[lede_source]
    if not overlay_enabled:
        return ClassifierOutput(
            kind=default_kind,
            confidence=default_confidence,
            classifier_path="type_based",
            pattern_match=None,
        )

    from stele.extraction.patterns import match_first_kind

    pack = match_first_kind(text)
    if pack is None or pack.kind_weight <= default_confidence:
        return ClassifierOutput(
            kind=default_kind,
            confidence=default_confidence,
            classifier_path="type_based",
            pattern_match=None,
        )

    return ClassifierOutput(
        kind=pack.kind,
        confidence=pack.kind_weight,
        classifier_path="pattern_overlay",
        pattern_match=pack.kind,
    )
```

- [ ] **Step 4: Run all classifier tests, confirm they pass**

```bash
.venv/bin/pytest tests/unit/extraction/test_classifier.py -v
```

Expected: all 11+ tests PASS.

- [ ] **Step 5: Run DC-002 — verify the disabled flag actually gates behavior**

```bash
.venv/bin/pytest tests/unit/extraction/test_classifier.py::test_overlay_disabled_falls_back_to_type_based -v
```

Expected: PASS. This is the load-bearing regression — if the overlay-disabled flag silently allowed overrides, this would fail. Confirm the output explicitly says `classifier_path == "type_based"` and `kind == "fact"`.

- [ ] **Step 6: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/extraction/classifier.py tests/unit/extraction/test_classifier.py
.venv/bin/mypy src/stele/extraction/classifier.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/stele/extraction/classifier.py tests/unit/extraction/test_classifier.py
git commit -m "feat(extraction): pattern overlay with kind_weight tie-break (SC-005, DC-002)"
```

---

### Task 6: Pure `extract_candidates` core + DC-001

Wraps lede.extract.* + classifier into the deterministic primitive. After this task, run DC-001.

**Files:**
- Create: `src/stele/extraction/candidates.py`
- Test: `tests/unit/extraction/test_candidates.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/extraction/test_candidates.py`:

```python
"""Tests for the pure extract_candidates core."""

from __future__ import annotations

from stele.extraction.candidates import extract_candidates
from stele.extraction.models import MemoryCandidate
from stele.pii.regex import RegexPIIScrubber


def _scrubber() -> RegexPIIScrubber:
    return RegexPIIScrubber()


SAMPLE = (
    "The 2026 Q1 product launch is on March 15. "
    "Revenue grew 12% year over year. "
    "I prefer dark mode for the dashboard."
)


def test_extract_candidates_returns_memory_candidates() -> None:
    out = extract_candidates(
        text=SAMPLE,
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    assert isinstance(out, list)
    for cand in out:
        assert isinstance(cand, MemoryCandidate)
        assert 0.0 <= cand.confidence <= 1.0
        assert cand.lede_source in {"key_fact", "stat", "metadata", "phrase", "summary"}


def test_extract_candidates_deterministic() -> None:
    a = extract_candidates(
        text=SAMPLE,
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    b = extract_candidates(
        text=SAMPLE,
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_extract_candidates_truncates_to_max() -> None:
    long_text = " ".join(
        f"Fact number {i} is that the year 202{i % 10} mattered."
        for i in range(100)
    )
    out = extract_candidates(
        text=long_text,
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=5,
    )
    assert len(out) <= 5


def test_extract_candidates_empty_text_returns_empty_list() -> None:
    out = extract_candidates(
        text="",
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    assert out == []


def test_extract_candidates_preference_is_classified_via_overlay() -> None:
    out = extract_candidates(
        text="I prefer dark mode.",
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    kinds = {c.kind for c in out}
    assert "preference" in kinds


def test_extract_candidates_overlay_disabled_means_no_overrides() -> None:
    out = extract_candidates(
        text="I prefer dark mode.",
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=False,
        max_candidates=50,
    )
    assert all(c.classifier_path == "type_based" for c in out)
    assert all(c.kind != "preference" for c in out)


def test_extract_candidates_scrubs_pii_in_candidate_text() -> None:
    # The default RegexPIIScrubber redacts emails.
    out = extract_candidates(
        text="Contact alice@example.com for the migration plan.",
        source_refs=["stele://default/abc"],
        scrubber=_scrubber(),
        overlay_enabled=True,
        max_candidates=50,
    )
    for cand in out:
        assert "alice@example.com" not in cand.text
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/extraction/test_candidates.py -v
```

Expected: `ModuleNotFoundError: No module named 'stele.extraction.candidates'`.

- [ ] **Step 3: Implement `candidates.py`**

Create `src/stele/extraction/candidates.py`:

```python
"""Pure deterministic extraction core.

This module is PURE — no clock, no filesystem, no DB, no backend. The
scrubber is a pure-object dependency (RegexPIIScrubber is in-memory regex);
its presence here does not violate purity.
"""

from __future__ import annotations

from typing import Protocol

from stele.core.artifact import ScrubResult
from stele.extraction.classifier import classify_kind
from stele.extraction.models import LedeSource, MemoryCandidate


class _Scrubber(Protocol):
    def scrub(self, text: str, *, context: dict[str, object] | None = None) -> ScrubResult: ...


def extract_candidates(
    *,
    text: str,
    source_refs: list[str],
    scrubber: _Scrubber,
    overlay_enabled: bool,
    max_candidates: int,
) -> list[MemoryCandidate]:
    """Run lede.extract.* over text, classify each item, return candidates.

    source_refs is accepted but not embedded in the candidate (the orchestrator
    composes the eventual MemoryRecord's source_refs from its input). We accept
    it here as a contract reminder: extraction is always source-traced.
    """
    del source_refs  # contract signal only

    if not text or not text.strip():
        return []

    raw_items = list(_lede_pass(text))
    candidates: list[MemoryCandidate] = []
    for item_text, lede_source in raw_items:
        if len(candidates) >= max_candidates:
            break
        scrubbed = scrubber.scrub(item_text)
        classification = classify_kind(
            text=scrubbed.text,
            lede_source=lede_source,
            overlay_enabled=overlay_enabled,
        )
        candidates.append(
            MemoryCandidate(
                text=scrubbed.text,
                kind=classification.kind,
                confidence=classification.confidence,
                lede_source=lede_source,
                classifier_path=classification.classifier_path,
                pattern_match=classification.pattern_match,
            )
        )
    return candidates


def _lede_pass(text: str) -> list[tuple[str, LedeSource]]:
    """Run the lede passes, returning (text, source) pairs.

    Empirically-grounded rules (verified against lede 0.x by inspecting
    short single-sentence inputs):

    - `lede.summarize` returns the input verbatim for short documents.
      Emitting it as a "summary" candidate then produces a duplicate of
      whatever the sentence/key_facts pass also emits. Suppress when
      the summary is identical to the input (trimmed).
    - `lede.extract.key_facts` returns an empty tuple for single-sentence
      inputs. Fall back to `lede.sentences(text)` and emit each sentence
      as a "key_fact"-source candidate so agent-loop one-liners
      ("I prefer dark mode.") still produce something the classifier
      can label.

    Order matters for determinism: same input → same sequence of items.
    """
    try:
        from lede import sentences, summarize
        from lede.extract import key_facts, metadata, phrases, stats
    except ModuleNotFoundError:
        return []

    items: list[tuple[str, LedeSource]] = []
    stripped = text.strip()

    # 1. summary: single document-level summary, suppressed when identical
    summary_result = summarize(text, max_length=1200)
    summary_text = str(getattr(summary_result, "summary", summary_result)).strip()
    if summary_text and summary_text != stripped:
        items.append((summary_text, "summary"))

    # 2. key_facts: list of sentence-level facts; fall back to sentences
    fact_results = key_facts(text) or ()
    if fact_results:
        for fact in fact_results:
            fact_text = str(fact).strip()
            if fact_text:
                items.append((fact_text, "key_fact"))
    else:
        for sentence in sentences(text) or ():
            sentence_text = str(sentence).strip()
            if sentence_text:
                items.append((sentence_text, "key_fact"))

    # 3. stats: list of Stat objects
    for stat in stats(text) or ():
        stat_text = str(stat).strip()
        if stat_text:
            items.append((stat_text, "stat"))

    # 4. metadata: doc-level metadata
    meta = metadata(text)
    if meta is not None:
        meta_text = str(meta).strip()
        if meta_text and meta_text != "Metadata(dates=(), amounts=(), urls=(), entities=())":
            items.append((meta_text, "metadata"))

    # 5. phrases: PhraseFact items
    for phrase in phrases(text) or ():
        phrase_text = str(phrase).strip()
        if phrase_text:
            items.append((phrase_text, "phrase"))

    return items
```

- [ ] **Step 4: Run all candidates tests, confirm they pass**

```bash
.venv/bin/pytest tests/unit/extraction/test_candidates.py -v
```

Expected: all 7 tests PASS. The `test_extract_candidates_preference_is_classified_via_overlay` test depends on the sentence-fallback path in `_lede_pass`: `lede.extract.key_facts("I prefer dark mode.")` returns `()` for single-sentence inputs, so the implementation falls back to `lede.sentences(text)` and emits each sentence as a `"key_fact"`-source candidate. The classifier's pattern overlay then catches `preference` (weight 0.85 > type-based key_fact default 0.7). If the test fails, verify `lede.sentences` actually returns a non-empty tuple for the input — older versions of lede may not export it.

- [ ] **Step 5: Run DC-001 — confirm no Phase 3+ drift**

```bash
grep -rn 'pg_raggraph\|chunkshop\|RecallPolicy\|SourceConnector\|UniversalSearch' src/stele/extraction/
```

Expected: empty output. If anything matches, STOP. The slice has drifted; remove the offending import before continuing.

- [ ] **Step 6: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/extraction/candidates.py tests/unit/extraction/test_candidates.py
.venv/bin/mypy src/stele/extraction/candidates.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/stele/extraction/candidates.py tests/unit/extraction/test_candidates.py
git commit -m "feat(extraction): pure extract_candidates core + scrubber (SC-002, SC-003, DC-001)"
```

---

### Task 7: Fixture JSON files

The five fixture categories. Each file has positive samples and abstention samples used by Tasks 8+.

**Files:**
- Create: `tests/fixtures/extraction/preferences.json`
- Create: `tests/fixtures/extraction/decisions.json`
- Create: `tests/fixtures/extraction/commitments.json`
- Create: `tests/fixtures/extraction/changed_facts.json`
- Create: `tests/fixtures/extraction/abstention.json`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p tests/fixtures/extraction
```

- [ ] **Step 2: Write `preferences.json`**

```bash
cat > tests/fixtures/extraction/preferences.json <<'EOF'
{
  "category": "preferences",
  "expected_kind": "preference",
  "positive": [
    "I prefer dark mode for the dashboard.",
    "My favorite editor is Helix.",
    "I'm not a fan of CamelCase in Python."
  ],
  "abstention": [
    "The dashboard supports both light and dark themes.",
    "Helix is a modern modal editor.",
    "Python uses snake_case by convention."
  ]
}
EOF
```

- [ ] **Step 3: Write `decisions.json`**

```bash
cat > tests/fixtures/extraction/decisions.json <<'EOF'
{
  "category": "decisions",
  "expected_kind": "decision",
  "positive": [
    "We decided to switch to RBAC.",
    "Let's go with PostgreSQL for the new service.",
    "Decision: ship the migration on May 30."
  ],
  "abstention": [
    "The migration is complicated.",
    "PostgreSQL has a permissive license.",
    "RBAC is a common authorization model."
  ]
}
EOF
```

- [ ] **Step 4: Write `commitments.json`**

```bash
cat > tests/fixtures/extraction/commitments.json <<'EOF'
{
  "category": "commitments",
  "expected_kind": "commitment",
  "positive": [
    "I'll send the report by Friday.",
    "TODO: rewrite the auth middleware.",
    "The deliverable is due by next Monday."
  ],
  "abstention": [
    "The report covers Q3 metrics.",
    "Auth middleware sits between requests and handlers.",
    "Monday is the first day of the week."
  ]
}
EOF
```

- [ ] **Step 5: Write `changed_facts.json`**

Changed facts are a special case: a new statement supersedes an old one. The extractor's job here is to recognize that the new statement is a *fact* (it doesn't classify the supersession relationship — that's Phase 1's `Memory.add(supersedes=...)`).

```bash
cat > tests/fixtures/extraction/changed_facts.json <<'EOF'
{
  "category": "changed_facts",
  "expected_kind": "fact",
  "positive": [
    "The new release date is 2026-06-30.",
    "Revenue is now 12 million.",
    "The deployment region has moved to us-west-2."
  ],
  "abstention": [
    "Release dates can shift.",
    "Revenue numbers are reported quarterly.",
    "Cloud regions are geographic deployment zones."
  ]
}
EOF
```

- [ ] **Step 6: Write `abstention.json`**

Pure-noise inputs. The extractor MAY produce candidates (lede always extracts something from non-trivial text), but they MUST NOT be classified as preference/decision/commitment/instruction/issue.

```bash
cat > tests/fixtures/extraction/abstention.json <<'EOF'
{
  "category": "abstention",
  "expected_kind": "fact",
  "positive": [],
  "abstention": [
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    "The quick brown fox jumps over the lazy dog.",
    "Population: 67 million. GDP: 2.9 trillion. Capital: Paris."
  ]
}
EOF
```

- [ ] **Step 7: Verify the fixtures load**

```bash
.venv/bin/python -c "
import json
from pathlib import Path
for f in sorted(Path('tests/fixtures/extraction').glob('*.json')):
    data = json.loads(f.read_text())
    print(f.name, '→', data['category'], 'positive=' + str(len(data['positive'])), 'abstention=' + str(len(data['abstention'])))
"
```

Expected:
```
abstention.json → abstention positive=0 abstention=3
changed_facts.json → changed_facts positive=3 abstention=3
commitments.json → commitments positive=3 abstention=3
decisions.json → decisions positive=3 abstention=3
preferences.json → preferences positive=3 abstention=3
```

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/extraction/
git commit -m "test(extraction): fixture sets for the 5 Phase-2 categories"
```

---

### Task 8: `MemoryExtractor` skeleton + `from_text`

The orchestrator class. Start with the simplest entry point — `from_text`, which already has explicit source_refs.

**Files:**
- Create: `src/stele/extraction/extractor.py`
- Test: `tests/unit/extraction/test_extractor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/extraction/test_extractor.py`:

```python
"""Tests for the MemoryExtractor orchestrator (from_text path)."""

from __future__ import annotations

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.exceptions import ValidationError
from stele.core.memory_record import MemoryScope
from stele.extraction.models import ExtractionReport


def _make_stele() -> Stele:
    return Stele(StashConfig())


def test_from_text_returns_extraction_report() -> None:
    stele = _make_stele()
    report = stele.extract.from_text(
        text="I prefer dark mode. Q1 revenue grew 12%.",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    assert isinstance(report, ExtractionReport)
    assert report.source_refs == ["stele://default/abc"]
    assert report.stats.candidate_count >= 1
    stele.close()


def test_from_text_rejects_empty_source_refs() -> None:
    stele = _make_stele()
    with pytest.raises(ValidationError, match="stele://"):
        stele.extract.from_text(
            text="x",
            source_refs=[],
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()


def test_from_text_rejects_non_stele_refs() -> None:
    stele = _make_stele()
    with pytest.raises(ValidationError, match="stele://"):
        stele.extract.from_text(
            text="x",
            source_refs=["http://example.com/abc"],
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()


def test_from_text_empty_text_returns_empty_accepted() -> None:
    stele = _make_stele()
    report = stele.extract.from_text(
        text="",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    assert report.accepted == []
    assert report.stats.candidate_count == 0
    stele.close()


def test_from_text_accepted_have_stored_ids() -> None:
    stele = _make_stele()
    report = stele.extract.from_text(
        text="I prefer dark mode.",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    for accepted in report.accepted:
        assert accepted.stored_id
        # Confirm the stored memory exists in the store
        stored = stele.memory.get(accepted.stored_id)
        assert stored is not None
        assert stored.text == accepted.candidate.text
    stele.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v -k from_text
```

Expected: `AttributeError: 'Stele' object has no attribute 'extract'`.

- [ ] **Step 3: Implement `MemoryExtractor` and `from_text`**

Create `src/stele/extraction/extractor.py`:

```python
"""MemoryExtractor — I/O orchestrator for Phase 2 extraction."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from stele.core.exceptions import (
    ArtifactNotFound,
    CapabilityError,
    SteleError,
    ValidationError,
)
from stele.core.memory_record import MemoryScope
from stele.extraction.candidates import extract_candidates
from stele.extraction.models import (
    AcceptedCandidate,
    ExtractionReport,
    ExtractionStats,
    MemoryCandidate,
    RejectedCandidate,
)

if TYPE_CHECKING:
    from stele.core.config import ExtractionConfig
    from stele.core.memory import Memory
    from stele.core.stash import Stele
    from stele.pii.regex import RegexPIIScrubber
    from stele.pii.scrubber import DisabledPIIScrubber


def _fingerprint(config: ExtractionConfig) -> str:
    return hashlib.sha256(
        json.dumps(config.model_dump(), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _validate_source_refs(source_refs: list[str]) -> None:
    if not source_refs:
        raise ValidationError(
            "every memory must cite at least one stele:// source_ref"
        )
    for ref in source_refs:
        if not ref.startswith("stele://"):
            raise ValidationError(
                f"source_refs entries must be stele:// URIs, got {ref!r}"
            )


class MemoryExtractor:
    def __init__(
        self,
        *,
        stele: Stele,
        memory: Memory,
        scrubber: RegexPIIScrubber | DisabledPIIScrubber,
        config: ExtractionConfig,
    ) -> None:
        self._stele = stele
        self._memory = memory
        self._scrubber = scrubber
        self._config = config

    def _check_enabled(self) -> None:
        if not self._config.enabled:
            raise CapabilityError("extraction is disabled in config")

    def _run_pure_core(
        self, *, text: str, source_refs: list[str]
    ) -> list[MemoryCandidate]:
        try:
            return extract_candidates(
                text=text,
                source_refs=source_refs,
                scrubber=self._scrubber,
                overlay_enabled=self._config.overlay_patterns_enabled,
                max_candidates=self._config.max_candidates_per_doc,
            )
        except Exception as exc:
            raise SteleError("Extraction failed during lede pass") from exc

    def from_text(
        self,
        *,
        text: str,
        source_refs: list[str],
        scope: MemoryScope,
    ) -> ExtractionReport:
        self._check_enabled()
        _validate_source_refs(source_refs)

        candidates = self._run_pure_core(text=text, source_refs=source_refs)
        accepted, rejected = self._commit_candidates(
            candidates=candidates,
            source_refs=source_refs,
            scope=scope,
        )
        return self._build_report(
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            source_refs=source_refs,
        )

    # ----- internals shared by all three entry points -----

    def _commit_candidates(
        self,
        *,
        candidates: list[MemoryCandidate],
        source_refs: list[str],
        scope: MemoryScope,
    ) -> tuple[list[AcceptedCandidate], list[RejectedCandidate]]:
        accepted: list[AcceptedCandidate] = []
        rejected: list[RejectedCandidate] = []
        fp = _fingerprint(self._config)
        for cand in candidates:
            if cand.confidence < self._config.min_confidence:
                rejected.append(RejectedCandidate(candidate=cand, reason="below_threshold"))
                continue
            try:
                result = self._memory.add(
                    text=cand.text,
                    kind=cand.kind,
                    source_refs=source_refs,
                    scope=scope,
                    confidence=cand.confidence,
                    metadata={"extraction_config": fp},
                )
            except ValidationError as exc:
                rejected.append(
                    RejectedCandidate(
                        candidate=cand,
                        reason="validation_error",
                        error_message=str(exc),
                    )
                )
                continue
            if result.duplicate_of is not None:
                rejected.append(
                    RejectedCandidate(
                        candidate=cand,
                        reason="duplicate",
                        duplicate_of=result.duplicate_of,
                    )
                )
                continue
            accepted.append(
                AcceptedCandidate(candidate=cand, stored_id=result.record.id)
            )
        return accepted, rejected

    def _build_report(
        self,
        *,
        candidates: list[MemoryCandidate],
        accepted: list[AcceptedCandidate],
        rejected: list[RejectedCandidate],
        source_refs: list[str],
    ) -> ExtractionReport:
        pii_flags = sorted(
            {flag for a in accepted for flag in self._collect_pii_flags(a)}
        )
        return ExtractionReport(
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            pii_flags=pii_flags,
            source_refs=source_refs,
            stats=ExtractionStats(
                candidate_count=len(candidates),
                accepted_count=len(accepted),
                rejected_count=len(rejected),
            ),
            config_fingerprint=_fingerprint(self._config),
        )

    def _collect_pii_flags(self, accepted: AcceptedCandidate) -> list[str]:
        stored = self._memory.get(accepted.stored_id)
        return list(stored.pii_flags) if stored else []

    def close(self) -> None:
        # The orchestrator owns no resources directly; Memory + Stele are
        # closed by their owners. This method exists for symmetry with
        # Stele.memory.close() so wire-up code can call it uniformly.
        pass
```

- [ ] **Step 4: Add the `Stele.extract` property to `core/stash.py`**

In `src/stele/core/stash.py`, near the `Stele.memory` property block, add:

```python
    @property
    def extract(self) -> MemoryExtractor:  # forward ref imported below
        if not hasattr(self, "_extractor"):
            from stele.extraction.extractor import MemoryExtractor

            self._extractor = MemoryExtractor(
                stele=self,
                memory=self.memory,
                scrubber=self.pii_scrubber,  # type: ignore[arg-type]
                config=self.config.extraction,
            )
        return self._extractor
```

Also extend `Stele.close()` to close the extractor if it was initialized:

```python
    def close(self) -> None:
        memory = getattr(self, "_memory", None)
        if memory is not None:
            memory.close()
        extractor = getattr(self, "_extractor", None)
        if extractor is not None:
            extractor.close()
```

Add the import block at top of file (with the other TYPE_CHECKING-guarded imports):

```python
if TYPE_CHECKING:
    from stele.core.memory import Memory
    from stele.extraction.extractor import MemoryExtractor
```

If `TYPE_CHECKING` isn't yet imported in `stash.py`, add `from typing import TYPE_CHECKING` to the existing imports.

- [ ] **Step 5: Run from_text tests, confirm they pass**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v -k from_text
```

Expected: all five `from_text` tests PASS.

- [ ] **Step 6: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/extraction/extractor.py src/stele/core/stash.py tests/unit/extraction/test_extractor.py
.venv/bin/mypy src/stele
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/stele/extraction/extractor.py src/stele/core/stash.py tests/unit/extraction/test_extractor.py
git commit -m "feat(extraction): MemoryExtractor + Stele.extract.from_text (SC-010, SC-012)"
```

---

### Task 9: `from_artifact` entry point

Pulls text via `Stele.fetch`, derives `source_refs` automatically.

**Files:**
- Modify: `src/stele/extraction/extractor.py`
- Test: `tests/unit/extraction/test_extractor.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/extraction/test_extractor.py`:

```python
def test_from_artifact_derives_source_refs() -> None:
    stele = _make_stele()
    stored = stele.store(
        data="I prefer dark mode. Q1 revenue grew 12%.",
        namespace="default",
    )
    report = stele.extract.from_artifact(
        artifact_id=stored.artifact_id,
        scope=MemoryScope(user_id="alice"),
    )
    # FetchResult.reference is the full stele:// URI; derived source_ref
    # equals the StoredResult.reference for the same artifact.
    assert report.source_refs == [stored.reference]
    assert report.stats.candidate_count >= 1
    stele.close()


def test_from_artifact_raises_for_missing_id() -> None:
    from stele.core.exceptions import ArtifactNotFound

    stele = _make_stele()
    with pytest.raises(ArtifactNotFound):
        stele.extract.from_artifact(
            artifact_id="nonexistent_id",
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v -k from_artifact
```

Expected: `AttributeError: 'MemoryExtractor' object has no attribute 'from_artifact'`.

- [ ] **Step 3: Add `from_artifact` to `MemoryExtractor`**

In `src/stele/extraction/extractor.py`, add this method on `MemoryExtractor` (right after `from_text`):

```python
    def from_artifact(
        self,
        *,
        artifact_id: str,
        scope: MemoryScope,
    ) -> ExtractionReport:
        self._check_enabled()
        fetched = self._stele.fetch(artifact_id)  # raises ArtifactNotFound
        # FetchResult.reference is already the full stele://<ns>/<id> URI.
        source_refs = [fetched.reference]
        text = (
            fetched.content
            if isinstance(fetched.content, str)
            else fetched.content.decode("utf-8", errors="replace")
        )
        candidates = self._run_pure_core(text=text, source_refs=source_refs)
        accepted, rejected = self._commit_candidates(
            candidates=candidates,
            source_refs=source_refs,
            scope=scope,
        )
        return self._build_report(
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            source_refs=source_refs,
        )
```

`FetchResult` is defined in `src/stele/core/artifact.py:122-133`. The
relevant fields are `reference: str` (the full `stele://ns/id` URI) and
`content: str | bytes`. The orchestrator uses `reference` directly to avoid
reconstructing the URI from parts.

- [ ] **Step 4: Run the test, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v -k from_artifact
```

Expected: both tests PASS.

- [ ] **Step 5: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/extraction/extractor.py
.venv/bin/mypy src/stele/extraction/extractor.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/stele/extraction/extractor.py tests/unit/extraction/test_extractor.py
git commit -m "feat(extraction): Stele.extract.from_artifact + auto source_refs (SC-008)"
```

---

### Task 10: `from_messages` with auto-stash

Accepts a list of message dicts, auto-stashes them as a single artifact, then runs extraction.

**Files:**
- Modify: `src/stele/extraction/extractor.py`
- Test: `tests/unit/extraction/test_extractor.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/extraction/test_extractor.py`:

```python
def test_from_messages_auto_stashes_and_extracts() -> None:
    stele = _make_stele()
    report = stele.extract.from_messages(
        messages=[
            {"role": "user", "content": "I prefer dark mode."},
            {"role": "assistant", "content": "Got it. Anything else?"},
        ],
        scope=MemoryScope(user_id="alice"),
    )
    assert len(report.source_refs) == 1
    assert report.source_refs[0].startswith("stele://")
    # The stashed artifact must be retrievable.
    ref = report.source_refs[0]
    artifact_id = ref.rsplit("/", 1)[-1]
    fetched = stele.fetch(artifact_id)
    assert "dark mode" in str(fetched.content)
    stele.close()


def test_from_messages_empty_list_returns_empty_report() -> None:
    stele = _make_stele()
    report = stele.extract.from_messages(
        messages=[],
        scope=MemoryScope(user_id="alice"),
    )
    assert report.candidates == []
    assert report.accepted == []
    # source_refs may be [] when nothing was stashed.
    stele.close()
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v -k from_messages
```

Expected: `AttributeError: 'MemoryExtractor' object has no attribute 'from_messages'`.

- [ ] **Step 3: Add `from_messages`**

In `src/stele/extraction/extractor.py`, add this method on `MemoryExtractor`:

```python
    def from_messages(
        self,
        *,
        messages: list[dict[str, str]],
        scope: MemoryScope,
    ) -> ExtractionReport:
        self._check_enabled()
        if not messages:
            return ExtractionReport(
                candidates=[],
                accepted=[],
                rejected=[],
                pii_flags=[],
                source_refs=[],
                stats=ExtractionStats(
                    candidate_count=0, accepted_count=0, rejected_count=0
                ),
                config_fingerprint=_fingerprint(self._config),
            )

        thread_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
        )

        if self._config.auto_stash_messages:
            stored = self._stele.store(data=thread_text, namespace="default")
            # StoredResult.reference is already the full stele:// URI.
            source_refs = [stored.reference]
        else:
            raise ValidationError(
                "from_messages requires auto_stash_messages=True or pre-stashed messages; "
                "use from_text with explicit source_refs instead"
            )

        candidates = self._run_pure_core(text=thread_text, source_refs=source_refs)
        accepted, rejected = self._commit_candidates(
            candidates=candidates,
            source_refs=source_refs,
            scope=scope,
        )
        return self._build_report(
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
            source_refs=source_refs,
        )
```

- [ ] **Step 4: Run the test, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v -k from_messages
```

Expected: both tests PASS.

- [ ] **Step 5: Type-check and lint clean**

```bash
.venv/bin/ruff check src/stele/extraction/extractor.py
.venv/bin/mypy src/stele/extraction/extractor.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/stele/extraction/extractor.py tests/unit/extraction/test_extractor.py
git commit -m "feat(extraction): Stele.extract.from_messages + auto-stash (SC-009)"
```

---

### Task 11: Confidence threshold rejection test

Confirm candidates below `min_confidence` land in `rejected` with reason `below_threshold`. The behavior already exists from Task 8 — this task locks the regression test.

**Files:**
- Test: `tests/unit/extraction/test_extractor.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/extraction/test_extractor.py`:

```python
def test_below_threshold_candidates_appear_in_rejected() -> None:
    from stele.core.config import StashConfig

    # Set min_confidence very high so all candidates fall below.
    cfg = StashConfig.load({"extraction": {"min_confidence": 0.99}})
    stele = Stele(cfg)
    report = stele.extract.from_text(
        text="The capital of France is Paris.",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    assert report.accepted == []
    assert report.rejected
    assert all(r.reason == "below_threshold" for r in report.rejected)
    stele.close()
```

- [ ] **Step 2: Run, confirm it passes (no impl change needed)**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py::test_below_threshold_candidates_appear_in_rejected -v
```

Expected: PASS. If it fails, the threshold logic in `_commit_candidates` is broken — fix before committing.

- [ ] **Step 3: Commit (test-only commit)**

```bash
git add tests/unit/extraction/test_extractor.py
git commit -m "test(extraction): below-threshold candidates land in rejected[]"
```

---

### Task 12: Duplicate detection rejection test

Confirm candidates that hit Phase 1's duplicate detection land in `rejected` with `reason="duplicate"`. Already-existing logic; this task locks the test.

**Files:**
- Test: `tests/unit/extraction/test_extractor.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/extraction/test_extractor.py`:

```python
def test_duplicate_candidate_appears_in_rejected() -> None:
    stele = _make_stele()
    text = "I prefer dark mode."
    report_a = stele.extract.from_text(
        text=text,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    # First run should accept the preference.
    assert any(a.candidate.kind == "preference" for a in report_a.accepted)

    # Second run on identical text → duplicate detection fires.
    report_b = stele.extract.from_text(
        text=text,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    duplicates = [r for r in report_b.rejected if r.reason == "duplicate"]
    assert duplicates, "expected at least one duplicate rejection on re-run"
    for dup in duplicates:
        assert dup.duplicate_of is not None
    stele.close()
```

- [ ] **Step 2: Run the test, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py::test_duplicate_candidate_appears_in_rejected -v
```

Expected: PASS. The behavior comes from Phase 1's `MemoryAddResult.duplicate_of`.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/extraction/test_extractor.py
git commit -m "test(extraction): duplicate candidates land in rejected[] with duplicate_of (SC-011)"
```

---

### Task 13: `CapabilityError` when extraction is disabled

**Files:**
- Test: `tests/unit/extraction/test_extractor.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_extract_raises_capability_error_when_disabled() -> None:
    from stele.core.config import StashConfig
    from stele.core.exceptions import CapabilityError

    cfg = StashConfig.load({"extraction": {"enabled": False}})
    stele = Stele(cfg)
    with pytest.raises(CapabilityError, match="disabled"):
        stele.extract.from_text(
            text="anything",
            source_refs=["stele://default/abc"],
            scope=MemoryScope(user_id="alice"),
        )
    with pytest.raises(CapabilityError, match="disabled"):
        stele.extract.from_messages(
            messages=[{"role": "user", "content": "x"}],
            scope=MemoryScope(user_id="alice"),
        )
    stele.close()
```

- [ ] **Step 2: Run, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py -v -k disabled
```

Expected: PASS (the `_check_enabled` guard is already on all three entry points).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/extraction/test_extractor.py
git commit -m "test(extraction): disabled config raises CapabilityError (SC-016)"
```

---

### Task 14: `config_fingerprint` stamped on memory metadata

Every accepted memory must carry the fingerprint so Phase 3 can detect config drift.

**Files:**
- Test: `tests/unit/extraction/test_extractor.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_accepted_memories_carry_config_fingerprint() -> None:
    stele = _make_stele()
    report = stele.extract.from_text(
        text="I prefer dark mode.",
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    assert report.accepted
    for accepted in report.accepted:
        stored = stele.memory.get(accepted.stored_id)
        assert stored is not None
        assert stored.metadata.get("extraction_config") == report.config_fingerprint
    stele.close()
```

- [ ] **Step 2: Run, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py::test_accepted_memories_carry_config_fingerprint -v
```

Expected: PASS (already wired in Task 8).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/extraction/test_extractor.py
git commit -m "test(extraction): config_fingerprint propagates to memory metadata (SC-017)"
```

---

### Task 15: `lede` raise → `SteleError`, atomic discard

If `lede.extract.*` raises mid-run, the whole extraction must be discarded. No partial commits.

**Files:**
- Test: `tests/unit/extraction/test_extractor.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_lede_failure_raises_steleerror_no_partial_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    from stele.core.exceptions import SteleError

    def _boom(text: str, *_: object, **__: object) -> object:
        raise RuntimeError("simulated lede failure")

    monkeypatch.setattr("lede.extract.key_facts", _boom)

    stele = _make_stele()
    pre_count = len(stele.memory.list(scope=MemoryScope(user_id="alice")))
    with pytest.raises(SteleError, match="Extraction failed"):
        stele.extract.from_text(
            text="I prefer dark mode.",
            source_refs=["stele://default/abc"],
            scope=MemoryScope(user_id="alice"),
        )
    post_count = len(stele.memory.list(scope=MemoryScope(user_id="alice")))
    assert pre_count == post_count, "no memory rows should be stored after a lede failure"
    stele.close()
```

- [ ] **Step 2: Run, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_extractor.py::test_lede_failure_raises_steleerror_no_partial_commits -v
```

Expected: PASS. The `_run_pure_core` wrapper raises before any commits happen.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/extraction/test_extractor.py
git commit -m "test(extraction): lede failure raises SteleError + no partial commits (SC-018)"
```

---

### Task 16: Re-export public types + DC-003

Make the Phase 2 public types importable from the top-level `stele` package, then run DC-003.

**Files:**
- Modify: `src/stele/__init__.py`

- [ ] **Step 1: Add the imports**

Append to `src/stele/__init__.py` (in the import block, alphabetical):

```python
from stele.extraction.models import (
    AcceptedCandidate,
    ExtractionReport,
    ExtractionStats,
    MemoryCandidate,
    RejectedCandidate,
)
```

And append to `__all__`:

```python
    "AcceptedCandidate",
    "ExtractionReport",
    "ExtractionStats",
    "MemoryCandidate",
    "RejectedCandidate",
```

(Inserted alphabetically — keep the list sorted.)

- [ ] **Step 2: Verify imports work**

```bash
.venv/bin/python -c "
from stele import (
    AcceptedCandidate,
    ExtractionReport,
    ExtractionStats,
    MemoryCandidate,
    RejectedCandidate,
)
print('all imports OK')
"
```

Expected: `all imports OK`.

- [ ] **Step 3: Run DC-003 — confirm extraction does not bypass `Memory`**

```bash
grep -rn 'MemoryStore\|_store\.' src/stele/extraction/
```

Expected: empty output. If matched, extraction is reaching past `Memory.add` into the store directly. Fix before continuing.

- [ ] **Step 4: Full ruff + mypy + pytest**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest tests/unit/extraction -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/stele/__init__.py
git commit -m "feat(extraction): export public types from stele package root (DC-003)"
```

---

### Task 17: PII invariant test

Prove that:
1. The double-scrub is idempotent (no PII leaks through stored memory).
2. Memory.search hits remain scrubbed.

**Files:**
- Test: `tests/unit/extraction/test_pii_invariant.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/extraction/test_pii_invariant.py`:

```python
"""PII scrubbing invariants across the extraction pipeline."""

from __future__ import annotations

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope
from stele.pii.regex import RegexPIIScrubber


PII_INPUT = (
    "Contact alice@example.com or call 415-555-0199 for migration questions. "
    "The deadline is 2026-06-30."
)


def test_extracted_candidates_have_scrubbed_text() -> None:
    stele = Stele(StashConfig())
    report = stele.extract.from_text(
        text=PII_INPUT,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    for cand in report.candidates:
        assert "alice@example.com" not in cand.text
        assert "415-555-0199" not in cand.text
    stele.close()


def test_stored_memory_text_remains_scrubbed() -> None:
    stele = Stele(StashConfig())
    report = stele.extract.from_text(
        text=PII_INPUT,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    for accepted in report.accepted:
        stored = stele.memory.get(accepted.stored_id)
        assert stored is not None
        assert "alice@example.com" not in stored.text
        assert "415-555-0199" not in stored.text
    stele.close()


def test_memory_search_hits_remain_scrubbed() -> None:
    stele = Stele(StashConfig())
    stele.extract.from_text(
        text=PII_INPUT,
        source_refs=["stele://default/abc"],
        scope=MemoryScope(user_id="alice"),
    )
    hits = stele.memory.search(
        MemoryQuery(
            query="migration",
            scope=MemoryScope(user_id="alice"),
        )
    )
    for hit in hits:
        assert "alice@example.com" not in hit.text
        assert "415-555-0199" not in hit.text
    stele.close()


def test_double_scrub_is_idempotent() -> None:
    scrubber = RegexPIIScrubber()
    once = scrubber.scrub(PII_INPUT).text
    twice = scrubber.scrub(once).text
    assert once == twice
```

- [ ] **Step 2: Run, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_pii_invariant.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/extraction/test_pii_invariant.py
git commit -m "test(extraction): PII invariants + double-scrub idempotence (SC-014)"
```

---

### Task 18: Abstention tests

Run the abstention fixtures through the extractor and confirm zero agent-loop-kind acceptances.

**Files:**
- Test: `tests/unit/extraction/test_abstention.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/extraction/test_abstention.py`:

```python
"""Abstention behavior — pure-noise inputs never produce agent-loop kinds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "extraction"
AGENT_LOOP_KINDS = {"preference", "decision", "commitment", "instruction", "issue"}


def _load(name: str) -> dict[str, list[str]]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "fixture_name",
    [
        "preferences.json",
        "decisions.json",
        "commitments.json",
        "changed_facts.json",
        "abstention.json",
    ],
)
def test_abstention_samples_never_produce_agent_loop_kinds(fixture_name: str) -> None:
    fixture = _load(fixture_name)
    stele = Stele(StashConfig())
    for text in fixture["abstention"]:
        report = stele.extract.from_text(
            text=text,
            source_refs=["stele://default/abc"],
            scope=MemoryScope(user_id="abstention"),
        )
        for accepted in report.accepted:
            assert accepted.candidate.kind not in AGENT_LOOP_KINDS, (
                f"{fixture_name} abstention sample produced agent-loop kind: "
                f"{accepted.candidate.kind!r} on text {text!r}"
            )
    stele.close()


def test_positive_samples_produce_expected_kind() -> None:
    for fixture_name in (
        "preferences.json",
        "decisions.json",
        "commitments.json",
    ):
        fixture = _load(fixture_name)
        expected = fixture["expected_kind"]
        stele = Stele(StashConfig())
        for text in fixture["positive"]:
            report = stele.extract.from_text(
                text=text,
                source_refs=["stele://default/abc"],
                scope=MemoryScope(user_id="positive"),
            )
            kinds = {a.candidate.kind for a in report.accepted}
            assert expected in kinds, (
                f"{fixture_name} positive sample failed to produce {expected!r}: "
                f"text={text!r}, kinds={kinds!r}"
            )
        stele.close()
```

- [ ] **Step 2: Run, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_abstention.py -v
```

Expected: all parametrized tests PASS. If any abstention sample produces an agent-loop kind, the regex pack is too aggressive — tighten the offending pattern in `patterns.py`. Do not relax the test.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/extraction/test_abstention.py
git commit -m "test(extraction): abstention + positive fixtures across 5 categories (SC-007, SC-012)"
```

---

### Task 19: Cross-backend contract test

Parametrize the extraction flow across `memory`, `sqlite`, and `postgres`.

**Files:**
- Test: `tests/contract/test_extraction_contract.py`

- [ ] **Step 1: Write the test**

Create `tests/contract/test_extraction_contract.py`:

```python
"""Cross-backend extraction contract — memory + sqlite + postgres."""

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
        ("sqlite", {"backend": {"type": "sqlite", "path": str(tmp / "stele.db")}}),
    )
    pg_dsn = os.environ.get("STELE_PG_DSN")
    if pg_dsn:
        configs.append(("postgres", {"backend": {"type": "postgres", "dsn": pg_dsn}}))
    return configs


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_extraction_contract_basic_flow(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        report = stele.extract.from_text(
            text="I prefer dark mode. Q1 revenue grew 12%.",
            source_refs=["stele://default/abc"],
            scope=MemoryScope(user_id="contract"),
        )
        assert report.stats.candidate_count >= 1
        assert isinstance(report.config_fingerprint, str)
        assert len(report.config_fingerprint) == 64
        for accepted in report.accepted:
            stored = stele.memory.get(accepted.stored_id)
            assert stored is not None
            assert stored.text == accepted.candidate.text
            assert stored.source_refs == ["stele://default/abc"]
    finally:
        stele.close()
```

- [ ] **Step 2: Run with memory + sqlite**

```bash
.venv/bin/pytest tests/contract/test_extraction_contract.py -v
```

Expected: 2 parametrized cases PASS (memory + sqlite).

- [ ] **Step 3: Run with Postgres if available**

```bash
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
scripts/postgres-up.sh
.venv/bin/pytest tests/contract/test_extraction_contract.py -v
```

Expected: 3 parametrized cases PASS (memory + sqlite + postgres).

- [ ] **Step 4: Commit**

```bash
git add tests/contract/test_extraction_contract.py
git commit -m "test(extraction): cross-backend contract memory+sqlite+postgres (SC-013, SC-015)"
```

---

### Task 20: Demo script

Human-readable proof. Reads the fixtures, runs extraction, prints the report.

**Files:**
- Create: `scripts/demo-extraction.sh`

- [ ] **Step 1: Write the script**

Create `scripts/demo-extraction.sh`:

```bash
#!/usr/bin/env bash
#
# Phase 2 demo: extracts from the five fixture categories and shows the
# resulting ExtractionReport for each. Human-readable proof of behavior.

set -euo pipefail

cd "$(dirname "$0")/.."

.venv/bin/python - <<'PY'
import json
from pathlib import Path

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope

FIXTURE_DIR = Path("tests/fixtures/extraction")
stele = Stele(StashConfig())

for fixture_path in sorted(FIXTURE_DIR.glob("*.json")):
    fixture = json.loads(fixture_path.read_text())
    print("=" * 72)
    print(f"category: {fixture['category']}  (expected kind: {fixture['expected_kind']})")
    print("=" * 72)
    for label, samples in (("POSITIVE", fixture["positive"]), ("ABSTENTION", fixture["abstention"])):
        for text in samples:
            print(f"\n[{label}] {text}")
            report = stele.extract.from_text(
                text=text,
                source_refs=["stele://default/demo"],
                scope=MemoryScope(user_id="demo"),
            )
            print(f"  candidates={report.stats.candidate_count}  "
                  f"accepted={report.stats.accepted_count}  "
                  f"rejected={report.stats.rejected_count}")
            for accepted in report.accepted:
                cand = accepted.candidate
                print(f"  ACCEPTED  kind={cand.kind!r:14s} "
                      f"conf={cand.confidence:.2f}  "
                      f"source={cand.lede_source}  path={cand.classifier_path}")
            for rejected in report.rejected:
                print(f"  REJECTED  reason={rejected.reason!r}  "
                      f"kind={rejected.candidate.kind!r}")

stele.close()
print("\ndone.")
PY
```

- [ ] **Step 2: Make it executable and run**

```bash
chmod +x scripts/demo-extraction.sh
scripts/demo-extraction.sh
```

Expected: prints five fixture sections; each shows `candidates`, `accepted`, `rejected` counts; positive samples have at least one ACCEPTED line with the expected kind; abstention samples have zero accepted agent-loop kinds.

- [ ] **Step 3: Commit**

```bash
git add scripts/demo-extraction.sh
git commit -m "feat(demo): scripts/demo-extraction.sh proves all five fixture categories"
```

---

### Task 21: Architecture import-layer check

Mirror Phase 1's SC-011 invariant: extraction lives in its own layer; the orchestrator only consumes `Memory` through its public API.

**Files:**
- Test: `tests/unit/extraction/test_architecture.py`

- [ ] **Step 1: Write the test**

Create `tests/unit/extraction/test_architecture.py`:

```python
"""Architectural import-layer checks for the extraction package."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

EXTRACTION_ROOT = Path(__file__).resolve().parents[3] / "src" / "stele" / "extraction"

FORBIDDEN_MODULES = {
    "stele.storage.memory_store",
    "stele.storage.memory_store.base",
    "stele.storage.memory_store.memory",
    "stele.storage.memory_store.sqlite",
    "stele.storage.memory_store.postgres",
    "stele.storage.memory_store.mariadb",
    "stele.storage.memory_store.clickhouse",
}

FORBIDDEN_PREFIXES = (
    "pg_raggraph",
    "chunkshop",
)


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


@pytest.mark.parametrize("module_path", sorted(EXTRACTION_ROOT.rglob("*.py")))
def test_no_forbidden_imports(module_path: Path) -> None:
    imports = _imports(module_path)
    illegal = {m for m in imports if m in FORBIDDEN_MODULES}
    assert not illegal, f"{module_path} imports {illegal} — must consume Memory facade only"
    for imp in imports:
        for prefix in FORBIDDEN_PREFIXES:
            assert prefix not in imp, (
                f"{module_path} imports {imp!r} — Phase 4/5 drift detected"
            )
```

- [ ] **Step 2: Run, confirm it passes**

```bash
.venv/bin/pytest tests/unit/extraction/test_architecture.py -v
```

Expected: all parametrized cases PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/extraction/test_architecture.py
git commit -m "test(extraction): import-layer check (SC-013 invariant + DC-001 lock)"
```

---

### Task 22: DC-FINAL coverage check

Confirm every SC-001..SC-018 has a passing test cited.

**Files:**
- Read-only: the spec, the test files, the git log

- [ ] **Step 1: Write the SC → test mapping document**

This is a check, not a commit. Run:

```bash
cat <<'EOF' > /tmp/phase2-sc-coverage.txt
SC-001 → tests/unit/extraction/test_models.py
SC-002 → tests/unit/extraction/test_candidates.py::test_extract_candidates_returns_memory_candidates + test_architecture.py
SC-003 → tests/unit/extraction/test_candidates.py::test_extract_candidates_deterministic
SC-004 → tests/unit/extraction/test_classifier.py::test_type_based_defaults
SC-005 → tests/unit/extraction/test_classifier.py::test_overlay_wins_when_pattern_matches_with_higher_weight + test_overlay_tie_break_by_declaration_order
SC-006 → tests/unit/extraction/test_classifier.py::test_overlay_disabled_falls_back_to_type_based + test_candidates.py::test_extract_candidates_overlay_disabled_means_no_overrides
SC-007 → tests/unit/extraction/test_patterns.py + test_abstention.py::test_positive_samples_produce_expected_kind
SC-008 → tests/unit/extraction/test_extractor.py::test_from_artifact_derives_source_refs
SC-009 → tests/unit/extraction/test_extractor.py::test_from_messages_auto_stashes_and_extracts
SC-010 → tests/unit/extraction/test_extractor.py::test_from_text_rejects_empty_source_refs + test_from_text_rejects_non_stele_refs
SC-011 → tests/unit/extraction/test_extractor.py::test_duplicate_candidate_appears_in_rejected
SC-012 → tests/unit/extraction/test_abstention.py::test_abstention_samples_never_produce_agent_loop_kinds + test_extractor.py::test_from_text_empty_text_returns_empty_accepted
SC-013 → tests/contract/test_extraction_contract.py + test_architecture.py
SC-014 → tests/unit/extraction/test_pii_invariant.py (all 4 tests)
SC-015 → tests/contract/test_extraction_contract.py::test_extraction_contract_basic_flow (parametrized)
SC-016 → tests/unit/extraction/test_extractor.py::test_extract_raises_capability_error_when_disabled
SC-017 → tests/unit/extraction/test_extractor.py::test_accepted_memories_carry_config_fingerprint
SC-018 → tests/unit/extraction/test_extractor.py::test_lede_failure_raises_steleerror_no_partial_commits
EOF
cat /tmp/phase2-sc-coverage.txt
```

- [ ] **Step 2: Verify every cited test exists and passes**

```bash
.venv/bin/pytest tests/unit/extraction tests/contract/test_extraction_contract.py -v 2>&1 | tail -50
```

Expected: every test name in the mapping appears in the pytest run and reports PASS.

- [ ] **Step 3: Re-run the four drift checkpoints one more time**

```bash
echo "=== DC-001 ==="
grep -rn 'pg_raggraph\|chunkshop\|RecallPolicy\|SourceConnector\|UniversalSearch' src/stele/extraction/ || echo "(empty — OK)"

echo "=== DC-002 ==="
.venv/bin/pytest tests/unit/extraction/test_classifier.py::test_overlay_disabled_falls_back_to_type_based -v

echo "=== DC-003 ==="
grep -rn 'MemoryStore\|_store\.' src/stele/extraction/ || echo "(empty — OK)"
```

Expected: DC-001 empty, DC-002 passes, DC-003 empty.

- [ ] **Step 4: Confirm Out-of-Scope items are untouched**

```bash
echo "=== Out-of-Scope check ==="
grep -rn 'RecallPolicy\|SourceConnector\|UniversalSearch\|pg_raggraph\|chunkshop' src/stele/ tests/ || echo "(empty across src+tests — OK)"
echo "=== Memory contract files untouched ==="
git log main..HEAD --name-only | grep -E 'src/stele/core/memory.py|src/stele/core/memory_record.py|src/stele/storage/memory_store/' && echo "WARN: Phase-1 file modified on this branch" || echo "(no Phase-1 contract files touched — OK)"
```

Expected: out-of-scope grep empty (excluding spec/plan markdown which legitimately mentions the names); no Phase 1 contract files modified.

- [ ] **Step 5: Note the test count delta**

```bash
.venv/bin/pytest 2>&1 | tail -3
```

Compare against the count noted in Task 0 Step 2. Expected: pytest count increased by exactly the Phase 2 tests added (≈ 45–55 new tests).

- [ ] **Step 6: Commit the SC mapping doc (optional but recommended)**

```bash
cp /tmp/phase2-sc-coverage.txt docs/superpowers/specs/2026-05-13-phase2-sc-coverage.txt
git add docs/superpowers/specs/2026-05-13-phase2-sc-coverage.txt
git commit -m "docs(phase2): SC-001..SC-018 → test mapping for DC-FINAL"
```

---

### Task 23: Full repo verification + merge prep

Final lint + types + tests, then ready to merge the branch back into main.

**Files:**
- None (verification only)

- [ ] **Step 1: Run the full before-commit trio**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest
```

Expected: all three pass.

- [ ] **Step 2: Verify the Phase 2 commits**

```bash
git log main..HEAD --oneline
```

Expected: ~22 commits between the `main` branch tip and the current HEAD, matching the tasks above.

- [ ] **Step 3: Check that nothing outside the planned files was modified**

```bash
git diff --name-only main..HEAD
```

Expected: the diff includes only:
- `src/stele/__init__.py`
- `src/stele/core/config.py`
- `src/stele/core/stash.py`
- `src/stele/extraction/*.py`
- `tests/unit/core/test_config.py`
- `tests/unit/extraction/*.py`
- `tests/contract/test_extraction_contract.py`
- `tests/fixtures/extraction/*.json`
- `scripts/demo-extraction.sh`
- `docs/superpowers/specs/*` (spec + SC mapping)
- `docs/superpowers/plans/2026-05-13-phase2-deterministic-extraction.md` (this plan)

If any other file appears, investigate before merging.

- [ ] **Step 4: Tag the slice (optional)**

```bash
git tag phase2-deterministic-extraction
```

- [ ] **Step 5: Merge prep**

If the user wants to fast-forward into main:

```bash
git switch main
git merge --ff-only phase2-deterministic-extraction
git log --oneline -5
```

If main has moved (Phase 1 work landed in parallel), do a non-fast-forward merge with a real merge commit. Do NOT rebase Phase 2 onto Phase 1 work without confirming with the user first — pattern overlay regex changes are sensitive to text snippets that Phase 1's longrun benchmark may have introduced as fixtures.

---

## Parallel-with-Phase-1 Notes

If Phase 1 work resumes while Phase 2 is in progress, the conflict surface is small:

| File | Phase 1 may touch | Phase 2 may touch | Conflict risk |
|---|---|---|---|
| `src/stele/core/stash.py` | `Stele.memory` property, `Stele.close()` | Adds `Stele.extract` property, extends `Stele.close()` | Low — both edits are additive; merge resolves cleanly with both blocks present |
| `src/stele/__init__.py` | May export new memory types | Exports extraction types | Low — both add to `__all__` and import block |
| `benchmarks/longrun.py` | Active in Task 19 of Phase 1 | Untouched in Phase 2 | None |
| `tests/contract/test_memory_contract.py` | Phase 1's contract test | Untouched (Phase 2 has its own `test_extraction_contract.py`) | None |

If a merge conflict appears on `stash.py` or `__init__.py`, accept BOTH sides — both phases are adding non-overlapping content.

---

## Definition of Ready For Each Task

A task is ready to start when:

- Its predecessor task is committed.
- The cited test file exists or this task creates it.
- The required Phase 1 surfaces work (`.venv/bin/pytest tests/contract/test_memory_contract.py` passes).
- The required optional dependencies are installed (`lede` is already a runtime dep).

## Definition of Done For Each Task

A task is done when:

- The new test(s) pass.
- `ruff check .` and `mypy` on the touched files are clean.
- The commit was created with the documented message style (`feat`/`test`/`docs` + scope + imperative).
- Any cited DC-XXX checkpoint passed.
- No file outside the task's declared `Files:` list was modified.
