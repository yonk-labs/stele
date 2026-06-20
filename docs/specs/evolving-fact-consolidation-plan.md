# Evolving-Fact Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile evolving facts extracted from agent session transcripts so recall returns the current state, deterministically and LLM-free, by superseding within `(scope, kind=fact, canonical_subject, aspect)` slots.

**Architecture:** Extraction emits a human-visible `subject_label` + `aspect`; deterministic code makes the slot key. `from_session` buffers a session's facts, groups them into slots, orders each slot chronologically, and commits a supersession chain (each state `add(supersedes=[prior])`). Cross-session, it also supersedes active memories in the same slot when the new evidence is strictly newer. Recall is unchanged (it already filters to `active`).

**Tech Stack:** Python ≥3.12, pydantic models, pytest. Source under `src/stele/`, tests under `tests/`.

## Global Constraints

- Evolution is supersession only: `memory.add(..., supersedes=[id])`. Never edit memory text in place; never `delete` to "fix".
- Recall stays LLM-free by default. The LLM is used only inside extraction (already injected as `llm: Callable[[str], str]`).
- Extraction uses only the public memory facade (`add` / `list` / `search` / `get`), never storage internals.
- Every memory cites `source_refs` (stele:// URIs); `from_session` already supplies the stashed transcript ref.
- Facts only: never consolidate `decision` / `pitfall` / `instruction` / `preference` / others.
- Bias to false-negatives: consolidate only when subject is explicit AND aspect non-empty; otherwise commit standalone (today's behavior).
- Lint/types/tests gate: `.venv/bin/ruff check .`, `.venv/bin/mypy src tests`, `.venv/bin/pytest`.

---

### Task 1: Pure identity module

**Files:**
- Create: `src/stele/extraction/identity.py`
- Test: `tests/unit/extraction/test_identity.py`

**Interfaces:**
- Produces: `canonical_subject(label: str) -> str`, `canonical_aspect(aspect: str) -> str`, `SEEDED_ASPECTS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/extraction/test_identity.py
from stele.extraction.identity import canonical_subject, canonical_aspect

def test_subject_variants_collapse():
    assert canonical_subject("Test 1") == canonical_subject("test1") == canonical_subject("test-1") == "test 1"

def test_distinct_subjects_stay_distinct():
    assert canonical_subject("Test 1") != canonical_subject("Test 2")

def test_empty_subject_is_empty():
    assert canonical_subject("  ") == ""

def test_aspect_synonyms_fold():
    assert canonical_aspect("reliability") == "status"
    assert canonical_aspect("scope") == "coverage"

def test_unknown_aspect_kept_distinct_not_other():
    # never silently folded to a wrong/shared bucket
    assert canonical_aspect("latency") == "latency"

def test_empty_aspect_is_empty():
    assert canonical_aspect("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_identity.py -v`
Expected: FAIL (module `stele.extraction.identity` does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# src/stele/extraction/identity.py
"""Pure entity-identity helpers for evolving-fact consolidation.

The LLM emits a human-visible subject_label + aspect; deterministic code turns
them into stable keys, so inconsistent LLM identifiers (test1/Test 1/test-1)
collapse without trusting an opaque LLM slug. No LLM, no I/O."""
from __future__ import annotations

import re
import unicodedata

# Aspect vocabulary the extractor is asked to prefer. Synonyms fold in; unknown
# aspects are kept DISTINCT (never folded to a shared bucket), biasing toward
# false-negatives over false merges.
SEEDED_ASPECTS: tuple[str, ...] = (
    "status", "coverage", "version", "owner", "location", "config",
)
_ASPECT_SYNONYMS: dict[str, str] = {
    "result": "status", "outcome": "status", "state": "status",
    "reliability": "status", "health": "status",
    "scope": "coverage", "covers": "coverage",
    "path": "location", "dir": "location", "directory": "location",
    "ver": "version", "assignee": "owner", "responsible": "owner",
    "configuration": "config", "settings": "config",
}

_PUNCT = re.compile(r"[^\w\s]")
_ALNUM_SPLIT = re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")
_WS = re.compile(r"\s+")


def canonical_subject(label: str) -> str:
    s = unicodedata.normalize("NFKC", label or "").strip()
    if not s:
        return ""
    s = _ALNUM_SPLIT.sub(" ", s)   # test1 -> test 1
    s = _PUNCT.sub(" ", s)          # test-1 -> test 1
    return _WS.sub(" ", s).strip().casefold()


def canonical_aspect(aspect: str) -> str:
    s = unicodedata.normalize("NFKC", aspect or "").strip().casefold()
    if not s:
        return ""
    s = _WS.sub(" ", _PUNCT.sub(" ", s)).strip().replace(" ", "_")
    return _ASPECT_SYNONYMS.get(s, s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/extraction/test_identity.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/identity.py tests/unit/extraction/test_identity.py
git commit -m "feat(extraction): pure subject/aspect canonicalization for fact consolidation"
```

---

### Task 2: Extraction emits subject_label + aspect

**Files:**
- Modify: `src/stele/extraction/session.py` (`SessionMemory` ~34-39, `_EXTRACT_PROMPT` ~220-242, `extract_session_memories` ~273-292)
- Test: `tests/unit/extraction/test_session_subject_aspect.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SessionMemory(kind, summary, detail, subject_label="", aspect="")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/extraction/test_session_subject_aspect.py
import json
from stele.extraction.session import extract_session_memories

def test_extract_captures_subject_and_aspect():
    payload = json.dumps([
        {"kind": "fact", "summary": "Test 1 passed", "detail": "",
         "subject_label": "Test 1", "aspect": "status"},
        {"kind": "fact", "summary": "no subject here", "detail": ""},
    ])
    out = extract_session_memories(lambda _p: payload, "WINDOW")
    assert out[0].subject_label == "Test 1" and out[0].aspect == "status"
    assert out[1].subject_label == "" and out[1].aspect == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_session_subject_aspect.py -v`
Expected: FAIL (`SessionMemory` has no `subject_label`).

- [ ] **Step 3: Add the dataclass fields**

In `src/stele/extraction/session.py`, replace the `SessionMemory` dataclass:

```python
@dataclass(frozen=True)
class SessionMemory:
    kind: str  # a MemoryKind value
    summary: str
    detail: str
    subject_label: str = ""  # human-visible entity name; code canonicalizes the key
    aspect: str = ""         # which attribute of the subject this fact is about
```

- [ ] **Step 4: Capture the fields in the parser**

In `extract_session_memories`, replace the append block:

```python
        if kind in KIND_VALUES and summary:
            detail = str(obj.get("detail", "")).strip()
            out.append(SessionMemory(
                kind=kind, summary=summary, detail=detail,
                subject_label=str(obj.get("subject_label", "")).strip(),
                aspect=str(obj.get("aspect", "")).strip(),
            ))
```

- [ ] **Step 5: Extend the extraction prompt (additive)**

In `_EXTRACT_PROMPT`, replace the keys sentence and append subject/aspect guidance:

```text
Return ONLY a JSON array (no prose, no code fences). Each item is an object with
keys "kind", "summary" (one specific line), and "detail" (short; include the
failing command or approach if relevant).

For "fact" items about a NAMED, trackable entity (a test, file, service, branch,
config), ALSO include "subject_label" (the entity's visible name, e.g. "Test 1")
and "aspect" (which attribute the fact is about). Prefer an aspect from:
status, coverage, version, owner, location, config. If none fits, use a short
lowercase noun. Omit both for general facts with no named subject.
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/extraction/test_session_subject_aspect.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stele/extraction/session.py tests/unit/extraction/test_session_subject_aspect.py
git commit -m "feat(extraction): emit subject_label + aspect for named-entity facts"
```

---

### Task 3: Windows carry their original (chronological) index

**Files:**
- Modify: `src/stele/extraction/session.py` (`windows` ~197-217)
- Test: `tests/unit/extraction/test_windows_index.py`

**Interfaces:**
- Produces: `windows(turns, max_chars=4000, limit=3) -> list[tuple[int, str]]` where the int is the window's position in ORIGINAL transcript order, and the list is returned in ascending original order (failure-bearing windows are still preferred for SELECTION, but order is chronological).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/extraction/test_windows_index.py
from stele.extraction.session import Turn, windows

def test_windows_return_indexed_in_original_order():
    turns = [Turn("user", "x" * 4100), Turn("assistant", "y" * 4100),
             Turn("result", "boom", is_error=True)]
    out = windows(turns, max_chars=4000, limit=3)
    assert all(isinstance(w, tuple) and isinstance(w[0], int) for w in out)
    idxs = [w[0] for w in out]
    assert idxs == sorted(idxs)  # chronological
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_windows_index.py -v`
Expected: FAIL (`windows` returns `list[str]`).

- [ ] **Step 3: Reimplement `windows`**

```python
def windows(turns: list[Turn], max_chars: int = 4000, limit: int = 3) -> list[tuple[int, str]]:
    """Group already-reduced turns into ~max_chars windows. Failure-bearing
    windows are preferred for SELECTION (richest), but the result is returned in
    ORIGINAL (chronological) order with each window's original index, so
    consolidation can order an evolving fact's states by time. Turns arrive
    pre-reduced from `reduce_event`."""
    grouped: list[tuple[str, bool]] = []
    buf: list[str] = []
    size = 0
    has_err = False
    for t in turns:
        line = _line(t)
        buf.append(line)
        size += len(line)
        has_err = has_err or t.is_error
        if size >= max_chars:
            grouped.append(("\n".join(buf), has_err))
            buf, size, has_err = [], 0, False
    if buf:
        grouped.append(("\n".join(buf), has_err))
    indexed = list(enumerate(grouped))  # (original_index, (text, has_err))
    indexed.sort(key=lambda w: (not w[1][1], -len(w[1][0])))  # failure-first SELECTION
    selected = indexed[:limit]
    selected.sort(key=lambda w: w[0])  # return chronological
    return [(idx, text) for idx, (text, _err) in selected]
```

- [ ] **Step 4: Run the new test AND the existing session tests**

Run: `.venv/bin/pytest tests/unit/extraction/test_windows_index.py tests/unit/extraction -k window -v`
Expected: PASS. If a pre-existing test asserted `windows()` returned `list[str]`, update it to unpack `(idx, text)` — the SELECTION (which windows, failure-first) is unchanged; only the return shape and ordering changed.

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/session.py tests/unit/extraction/test_windows_index.py
git commit -m "refactor(extraction): windows() returns chronological (index, text) pairs"
```

---

### Task 4: Pure consolidation planner

**Files:**
- Create: `src/stele/extraction/consolidation.py`
- Test: `tests/unit/extraction/test_consolidation_plan.py`

**Interfaces:**
- Consumes: `SessionMemory` (Task 2), `canonical_subject`/`canonical_aspect` (Task 1).
- Produces:
  - `SlotKey(canonical_subject: str, aspect: str)` (frozen)
  - `Slotted(order: tuple[int, int], memory: SessionMemory, slot: SlotKey | None)` (frozen)
  - `slot_for(mem: SessionMemory) -> SlotKey | None`
  - `plan_chains(items: list[Slotted]) -> tuple[dict[SlotKey, list[Slotted]], list[Slotted]]`
  - `overlap_warnings(chains: dict[SlotKey, list[Slotted]]) -> list[tuple[str, list[str]]]`
  - `is_newer(this_recency: float | None, other_recency: float | None) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/extraction/test_consolidation_plan.py
from stele.extraction.session import SessionMemory
from stele.extraction.consolidation import (
    SlotKey, Slotted, slot_for, plan_chains, overlap_warnings, is_newer,
)

def _fact(summary, subject="", aspect="", kind="fact"):
    return SessionMemory(kind=kind, summary=summary, detail="",
                         subject_label=subject, aspect=aspect)

def test_slot_for_only_facts_with_subject_and_aspect():
    assert slot_for(_fact("x", "Test 1", "status")) == SlotKey("test 1", "status")
    assert slot_for(_fact("x", "Test 1", "")) is None       # no aspect
    assert slot_for(_fact("x", "", "status")) is None        # no subject
    assert slot_for(_fact("x", "Test 1", "status", kind="pitfall")) is None

def test_plan_chains_groups_and_orders():
    items = [
        Slotted((1, 0), _fact("passed", "Test 1", "status"), SlotKey("test 1", "status")),
        Slotted((0, 0), _fact("not run", "Test 1", "status"), SlotKey("test 1", "status")),
        Slotted((0, 1), _fact("chitchat"), None),
    ]
    chains, standalone = plan_chains(items)
    assert [s.memory.summary for s in chains[SlotKey("test 1", "status")]] == ["not run", "passed"]
    assert [s.memory.summary for s in standalone] == ["chitchat"]

def test_overlap_warnings_flags_multi_aspect_subject():
    chains = {SlotKey("test 1", "status"): [], SlotKey("test 1", "coverage"): []}
    assert overlap_warnings(chains) == [("test 1", ["status", "coverage"])]

def test_is_newer():
    assert is_newer(10.0, 5.0) is True
    assert is_newer(5.0, 10.0) is False
    assert is_newer(None, 5.0) is False   # unknown recency never supersedes on mtime
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_consolidation_plan.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Write the planner**

```python
# src/stele/extraction/consolidation.py
"""Pure planner for evolving-fact consolidation: assign session memories to
(subject, aspect) slots and order each slot chronologically. No DB, no LLM."""
from __future__ import annotations

from dataclasses import dataclass

from stele.extraction.identity import canonical_aspect, canonical_subject
from stele.extraction.session import SessionMemory


@dataclass(frozen=True)
class SlotKey:
    canonical_subject: str
    aspect: str


@dataclass(frozen=True)
class Slotted:
    order: tuple[int, int]          # (window_index, emission_index): chronological
    memory: SessionMemory
    slot: SlotKey | None            # None => commit standalone (today's behavior)


def slot_for(mem: SessionMemory) -> SlotKey | None:
    if mem.kind != "fact":
        return None
    subj = canonical_subject(mem.subject_label)
    asp = canonical_aspect(mem.aspect)
    if not subj or not asp:
        return None
    return SlotKey(subj, asp)


def plan_chains(
    items: list[Slotted],
) -> tuple[dict[SlotKey, list[Slotted]], list[Slotted]]:
    """(chains, standalone). chains[slot] = states in chronological order;
    standalone = memories with no slot, committed unchanged."""
    chains: dict[SlotKey, list[Slotted]] = {}
    standalone: list[Slotted] = []
    for it in sorted(items, key=lambda x: x.order):
        if it.slot is None:
            standalone.append(it)
        else:
            chains.setdefault(it.slot, []).append(it)
    return chains, standalone


def overlap_warnings(chains: dict[SlotKey, list[Slotted]]) -> list[tuple[str, list[str]]]:
    """Aspect-drift detector (log-only): a canonical_subject carrying >1 aspect
    slot. Returns (subject, [aspects]) for review. Never auto-merges."""
    by_subject: dict[str, list[str]] = {}
    for slot in chains:
        by_subject.setdefault(slot.canonical_subject, []).append(slot.aspect)
    return [(s, asp) for s, asp in by_subject.items() if len(asp) > 1]


def is_newer(this_recency: float | None, other_recency: float | None) -> bool:
    """Strictly-newer compare on recency floats. Unknown `this_recency` never
    wins on mtime (caller falls back to store timestamp)."""
    if this_recency is None or other_recency is None:
        return False
    return this_recency > other_recency
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/extraction/test_consolidation_plan.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/consolidation.py tests/unit/extraction/test_consolidation_plan.py
git commit -m "feat(extraction): pure consolidation planner (slots, chains, drift detector)"
```

---

### Task 5: Wire consolidation into from_session (same + cross session)

**Files:**
- Modify: `src/stele/extraction/extractor.py` (`from_session` ~235-314; add module helpers + imports near top)
- Test: `tests/contract/test_consolidation_from_session.py`

**Interfaces:**
- Consumes: `windows` (Task 3), `extract_session_memories`/`SessionMemory` (Task 2), `Slotted`/`slot_for`/`plan_chains`/`overlap_warnings`/`is_newer` (Task 4), facade `memory.add(..., supersedes=[...], metadata=...)` and `memory.list(scope, status_filter, limit)`.
- Produces: unchanged `ExtractionReport`.

- [ ] **Step 1: Write the failing test**

```python
# tests/contract/test_consolidation_from_session.py
import json
from datetime import UTC, datetime
from stele.core.stash import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope

# Backend with supersession + as_of (sqlite). Memory facade enables extraction.
def _stele(tmp_path):
    cfg = StashConfig.model_validate({
        "backend": {"type": "sqlite", "dsn": f"sqlite:///{tmp_path}/m.db"},
        "extraction": {"enabled": True},
    })
    return Stele(cfg)

# Fake LLM: emits Test-1 status + coverage states, keyed off window content.
def _fake_llm(window: str) -> str:
    if "not run" in window:
        return json.dumps([
            {"kind": "fact", "summary": "Test 1 not run", "detail": "",
             "subject_label": "Test 1", "aspect": "status"},
            {"kind": "fact", "summary": "Test 1 covers RAG", "detail": "",
             "subject_label": "Test 1", "aspect": "coverage"},
        ])
    return json.dumps([
        {"kind": "fact", "summary": "Test 1 passed", "detail": "",
         "subject_label": "Test 1", "aspect": "status"},
        {"kind": "fact", "summary": "Test 1 covers RAG and graph", "detail": "",
         "subject_label": "Test 1", "aspect": "coverage"},
    ])

def test_same_session_supersedes_within_slot(tmp_path):
    s = _stele(tmp_path)
    scope = MemoryScope(namespace="t", session_id="s1")
    transcript = [
        {"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100},
        {"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100},
    ]
    s.extract.from_session(transcript=transcript, scope=scope, llm=_fake_llm, source_ref=None)
    active = s.memory.search(MemoryQuery(query="Test 1", scope=scope, limit=50))
    summaries = {m.summary for m in active}
    assert "Test 1 passed" in summaries
    assert "Test 1 covers RAG and graph" in summaries
    assert "Test 1 not run" not in summaries          # superseded
    assert "Test 1 covers RAG" not in summaries        # superseded (coverage chain)

def test_as_of_returns_historical_state(tmp_path):
    s = _stele(tmp_path)
    scope = MemoryScope(namespace="t2", session_id="s1")
    transcript = [
        {"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100},
        {"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100},
    ]
    s.extract.from_session(transcript=transcript, scope=scope, llm=_fake_llm, source_ref=None)
    hist = s.memory.search(MemoryQuery(query="Test 1", scope=scope, limit=50,
                                       include_superseded=True))
    assert "Test 1 not run" in {m.summary for m in hist}   # history preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/contract/test_consolidation_from_session.py -v`
Expected: FAIL (stale states still active; "Test 1 not run" present).

- [ ] **Step 3: Add imports + module helpers at the top of `extractor.py`**

Below the existing imports in `src/stele/extraction/extractor.py`:

```python
import logging
from datetime import UTC, datetime

from stele.core.memory_record import MemoryScope
from stele.extraction.consolidation import (
    Slotted, SlotKey, is_newer, overlap_warnings, plan_chains, slot_for,
)

_log = logging.getLogger(__name__)


def _record_recency(metadata: dict[str, object], effective_from: datetime) -> float:
    mt = metadata.get("session_mtime")
    if isinstance(mt, (int, float)):
        return float(mt)
    return effective_from.timestamp()


def _cross_session_superseded(
    memory: object, lookup_scope: MemoryScope, slot: SlotKey, this_recency: float,
) -> list[str]:
    """Active memories in the SAME slot from other sessions that this session's
    fact supersedes. Bias to false-negatives: exact subject+aspect match AND
    strictly newer (by recency)."""
    out: list[str] = []
    for r in memory.list(lookup_scope, status_filter=["active"], limit=500):  # type: ignore[attr-defined]
        meta = r.metadata or {}
        if meta.get("canonical_subject") != slot.canonical_subject:
            continue
        if meta.get("aspect") != slot.aspect:
            continue
        if not is_newer(this_recency, _record_recency(meta, r.effective_from)):
            continue
        out.append(r.id)
    return out
```

- [ ] **Step 4: Replace the commit loop in `from_session`**

Replace the block from `candidates: list[MemoryCandidate] = []` through the `for window in windows(...)` loop (the per-window immediate-add loop, ~287-311) with:

```python
        slotted: list[Slotted] = []
        for w_idx, window in windows(turns, max_chars=4000, limit=max_windows):
            for e_idx, mem in enumerate(extract_session_memories(llm, window)):
                slotted.append(Slotted(order=(w_idx, e_idx), memory=mem, slot=slot_for(mem)))
        chains, standalone = plan_chains(slotted)

        candidates: list[MemoryCandidate] = []
        accepted: list[AcceptedCandidate] = []
        rejected: list[RejectedCandidate] = []

        def _commit(mem: SessionMemory, *, supersedes: list[str], extra_meta: dict[str, object]) -> str | None:
            cand = MemoryCandidate(
                text=mem.summary, kind=mem.kind, confidence=0.8,  # type: ignore[arg-type]
                lede_source="key_fact", classifier_path="pattern_overlay",
            )
            candidates.append(cand)
            meta = dict(base_meta)
            meta.update(extra_meta)
            try:
                result = self._memory.add(
                    text=mem.detail or mem.summary, kind=mem.kind,  # type: ignore[arg-type]
                    source_refs=[ref], scope=scope, summary=mem.summary,
                    detail=mem.detail, confidence=0.8, metadata=meta,
                    supersedes=supersedes,
                )
            except ValidationError as exc:
                rejected.append(RejectedCandidate(
                    candidate=cand, reason="validation_error", error_message=str(exc)))
                return None
            if result.duplicate_of is not None and not supersedes:
                rejected.append(RejectedCandidate(
                    candidate=cand, reason="duplicate", duplicate_of=result.duplicate_of))
                return None
            accepted.append(AcceptedCandidate(candidate=cand, stored_id=result.record.id))
            return result.record.id

        for it in standalone:
            _commit(it.memory, supersedes=[], extra_meta={})

        this_recency = session_mtime if session_mtime is not None else datetime.now(UTC).timestamp()
        lookup_scope = scope.model_copy(update={"session_id": None})
        for slot, states in chains.items():
            slot_meta: dict[str, object] = {
                "canonical_subject": slot.canonical_subject, "aspect": slot.aspect,
            }
            cross_ids = _cross_session_superseded(self._memory, lookup_scope, slot, this_recency)
            prev_id: str | None = None
            for it in states:  # already chronological from plan_chains
                supersedes = [prev_id] if prev_id is not None else cross_ids
                new_id = _commit(it.memory, supersedes=supersedes, extra_meta=slot_meta)
                if new_id is not None:
                    prev_id = new_id

        for subj, aspects in overlap_warnings(chains):
            _log.info(
                "evolving-fact: subject %r carries multiple active aspects %s "
                "(possible aspect drift; left distinct, not merged)", subj, aspects,
            )
```

(The `return self._build_report(...)` line that follows is unchanged.)

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv/bin/pytest tests/contract/test_consolidation_from_session.py -v`
Expected: PASS (2 passed). If `extraction.enabled` config key differs, set it per `tests/contract/test_extraction_contract.py`'s fixture.

- [ ] **Step 6: Add the cross-session test**

```python
# append to tests/contract/test_consolidation_from_session.py
def test_cross_session_supersedes_prior(tmp_path):
    s = _stele(tmp_path)
    ns = "t3"
    yest = [{"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100}]
    s.extract.from_session(transcript=yest, scope=MemoryScope(namespace=ns, session_id="day1"),
                           llm=_fake_llm, source_ref=None)
    today = [{"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100}]
    s.extract.from_session(transcript=today, scope=MemoryScope(namespace=ns, session_id="day2"),
                           llm=_fake_llm, source_ref=None)
    # Query across the namespace (session_id=None matches all sessions).
    active = s.memory.search(MemoryQuery(query="Test 1",
                                         scope=MemoryScope(namespace=ns), limit=50))
    summaries = {m.summary for m in active}
    assert "Test 1 passed" in summaries
    assert "Test 1 not run" not in summaries   # day2 superseded day1 in the status slot
```

- [ ] **Step 7: Run all consolidation tests + types**

Run: `.venv/bin/pytest tests/contract/test_consolidation_from_session.py -v && .venv/bin/mypy src/stele/extraction`
Expected: PASS; mypy clean.

- [ ] **Step 8: Commit**

```bash
git add src/stele/extraction/extractor.py tests/contract/test_consolidation_from_session.py
git commit -m "feat(extraction): consolidate evolving facts into subject/aspect supersede chains"
```

---

### Task 6: Regression sweep + docs note

**Files:**
- Modify: `docs/project/current-status.md` (note the new capability)
- Test: full suites already written above.

- [ ] **Step 1: Run the gate trio**

Run: `.venv/bin/ruff check . && .venv/bin/mypy src tests && .venv/bin/pytest -q`
Expected: all clean. Pay attention to `tests/unit/extraction` and `tests/contract/test_extraction_contract.py` (the `windows()` shape change in Task 3 is the likeliest regression).

- [ ] **Step 2: Real-transcript spot check (manual, no assertion)**

Run `from_session` over a LARGE real transcript with an injected real LLM; eyeball: are facts about the same entity collapsing to current state? Capture any false merges (wrongly collapsed distinct facts) or zombie facts (aspect drift). Record findings in the commit message; do not let a curated easy case stand in for this.

- [ ] **Step 3: Update status doc**

Add one line under the appropriate section of `docs/project/current-status.md`:

```markdown
- Evolving-fact consolidation: from_session reconciles same-entity facts into
  (subject, aspect) supersession chains (same- and cross-session); recall returns
  current state, as_of preserves history. Spec: docs/specs/evolving-fact-consolidation-design.md.
```

- [ ] **Step 4: Commit**

```bash
git add docs/project/current-status.md
git commit -m "docs: note evolving-fact consolidation in current-status"
```

---

## Self-Review

**Spec coverage:**
- Slot = (scope, kind=fact, canonical_subject, aspect) → Task 4 `slot_for`.
- Supersession chain → Task 5 commit loop.
- Identity (LLM label, code key) → Tasks 1 + 2.
- Aspect-scoping solves partial-update → Tasks 1 (aspect) + 4 (slot per aspect) + 5 (independent chains).
- Same + cross session → Task 5 (standalone+chains; `_cross_session_superseded`).
- Facts only / false-negative bias → `slot_for` (kind=fact, requires subject+aspect).
- Aspect-drift detector (log-only) → Task 4 `overlap_warnings` + Task 5 logging.
- Ordering by source index (failure-first selection) → Task 3.
- No consumer change → recall/`distill_rules` already filter `active`; verified, no task needed.

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `SlotKey`, `Slotted`, `slot_for`, `plan_chains`, `overlap_warnings`, `is_newer` are defined in Task 4 and consumed with the same signatures in Task 5. `SessionMemory(..., subject_label, aspect)` defined in Task 2, used in Tasks 4–5. `windows() -> list[tuple[int, str]]` defined in Task 3, consumed in Task 5.

**Known limitations (carried from spec, not bugs):** aspect drift left distinct (logged, not merged); cross-aspect coherence out of scope; backfill of a no-`session_mtime` transcript falls back to store timestamp for cross-session recency.
