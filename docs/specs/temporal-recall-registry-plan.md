# Subject Registry (Temporal Recall, Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve entity identity deterministically BEFORE commit so cross-session evolving-fact supersession works even when the LLM labels the same entity differently, and so different users / self-referential facts never collide.

**Architecture:** A pure, scoped Subject Registry (`resolve_subject`) maps a raw LLM `subject_label` to a stable `subject_id` via exact-normalized match, an explicit alias map, self-referential resolution (pronoun to the scope user), or minting. Consolidation's slot key changes from `(canonical_subject, aspect)` to `(scope_key, subject_type, subject_id, aspect)`. Extraction resolves subjects against the active subjects already in scope (and nudges the LLM to reuse them) before slotting. A one-time additive backfill maps existing 0.6.3 chains into the new key without touching immutable memory rows.

**Tech Stack:** Python >=3.12, src/ layout, Pydantic config, pytest (`pythonpath = ["src", "."]`), ruff (`E,F,I,UP,B,SIM`), mypy --strict.

**Scope:** This is Phase 1 (registry only). `state` / `knowledge` / `both` recall modes, the materialized current-state projection, and horizon isolation are SEPARATE later plans (see `temporal-recall-spec.md`). Relative-date anchoring (Q1) is a sibling extraction-grounding feature, NOT in this plan.

**Review-driven revisions (abe: gemma + qwen + codex, fix-first):** the plain alias map + prompt nudge does NOT move the 60% on its own (it only fixes curated aliases + self-reference). The real fix is a deterministic KNOWN-SUBJECT HANDOFF (Task 6): the LLM returns an existing `subject_id` when a fact is about a known entity, and the system validates it EXACTLY against the active set (no cosine, no auto-merge). Added Task 0 (settle `SessionMemory` schema + the `canonical_scope_key` function form). Backfill stays additive `update_metadata` (codex: rewrite-by-supersession is worse) but is now explicitly idempotent + version-marked. Dependency: assumes PR #68 (`consolidation_enabled`) is merged.

## Global Constraints

- Python `>=3.12`; ruff clean (`E,F,I,UP,B,SIM`); `mypy --strict` over `src tests benchmarks` clean.
- Memory is immutable: evolution only by supersession (`add(supersedes=[...])`), never in-place edit. The backfill (Task 8) must NOT rewrite existing memory rows.
- Recall stays LLM-free and deterministic. Registry resolution is deterministic and LLM-free (the LLM only proposes the raw label).
- Every memory cites `source_refs` (`stele://` URIs). Unchanged by this plan.
- Over-merge is worse than under-merge: normalization/suffix rules PROPOSE candidates; only an explicit alias entry or self-ref rule BINDS. Ambiguous resolution refuses or mints, never silently merges. No cosine/embedding merge over fact text.
- New backend-visible behavior gets a parametrized contract test (memory + sqlite by default).
- Docs: no em-dashes (use period/colon/comma/parens).

---

## File Structure

- `src/stele/extraction/identity.py` (modify): add `SEEDED_SUBJECT_TYPES`, `canonical_subject_type`, `is_self_referential`. Existing `canonical_subject`/`canonical_aspect` unchanged.
- `src/stele/extraction/registry.py` (create): pure `resolve_subject` + `ExistingSubject` + `SubjectDisambiguationError`. No I/O, no LLM.
- `src/stele/extraction/consolidation.py` (modify): `SlotKey` gains `scope_key`, `subject_type`, `subject_id` (replacing bare `canonical_subject`); `slot_for` takes a resolved `subject_id`; `overlap_warnings` keys on `subject_id`.
- `src/stele/extraction/extractor.py` (modify): in `from_session`, gather active subjects in scope, resolve each fact's subject before slotting, thread `subject_id`/`subject_type` through `_commit` metadata, and match `_cross_session_superseded` on `subject_id`.
- `src/stele/extraction/session.py` (modify): the extract prompt gains a "reuse these existing subject names" vocabulary line (variance reducer).
- `src/stele/core/config.py` (modify): `ExtractionConfig.subject_aliases: dict[str, str]` (alias map) and reuse of the existing `consolidation_enabled` gate.
- `src/stele/extraction/migration.py` (create): `backfill_subject_ids(memory, scope)` additive backfill for pre-registry stores.
- Tests: `tests/unit/extraction/test_identity.py` (modify), `tests/unit/extraction/test_registry.py` (create), `tests/unit/extraction/test_consolidation_plan.py` (modify), `tests/contract/test_subject_registry.py` (create), `tests/contract/test_consolidation_from_session.py` (modify).

---

## Task 0: Settle interfaces (schema + scope-key)

**Files:**
- Modify: `src/stele/extraction/session.py` (SessionMemory + the extract JSON parser)
- Verify: `src/stele/core/memory_record.py` (`canonical_scope_key` is a module FUNCTION at line ~148, not a method)
- Test: `tests/unit/extraction/test_session.py`

**Why:** the registry path needs two fields the current extract schema lacks, and the scope-key helper is a function, not a method. Settle these before wiring (Tasks 3, 5). Dependency: this plan assumes PR #68 (`ExtractionConfig.consolidation_enabled`) is merged; the registry path runs inside the chain branch #68 gates.

**Interfaces:**
- Produces: `SessionMemory` gains `subject_type: str = "entity"` and `subject_id: str | None = None` (LLM-proposed, optional). Both default safely, so non-fact and legacy paths are unaffected.
- All plan code uses `canonical_scope_key(scope)` (module function), NOT `scope.canonical_scope_key()`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/extraction/test_session.py
def test_session_memory_has_subject_type_and_id():
    from stele.extraction.session import SessionMemory
    m = SessionMemory(kind="fact", summary="x", detail="",
                      subject_label="postgres", aspect="version")
    assert m.subject_type == "entity"   # safe default
    assert m.subject_id is None
    m2 = SessionMemory(kind="fact", summary="x", detail="", subject_label="postgres",
                       aspect="version", subject_type="service",
                       subject_id="service:postgres")
    assert m2.subject_type == "service" and m2.subject_id == "service:postgres"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_session.py -q -k subject_type_and_id`
Expected: FAIL (unexpected keyword `subject_type`).

- [ ] **Step 3: Implement**

Add `subject_type: str = "entity"` and `subject_id: str | None = None` to the `SessionMemory` model, and have the extract JSON parser (`extract_session_memories`) read the optional `subject_type` / `subject_id` keys when present (absent keys keep the defaults). Confirm `canonical_scope_key` is imported as a function from `memory_record`.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/unit/extraction/test_session.py -q -k subject_type_and_id`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/session.py tests/unit/extraction/test_session.py
git commit -m "feat(extraction): SessionMemory gains subject_type + proposed subject_id"
```

---

## Task 1: subject_type vocabulary + self-referential detection

**Files:**
- Modify: `src/stele/extraction/identity.py`
- Test: `tests/unit/extraction/test_identity.py`

**Interfaces:**
- Produces: `SEEDED_SUBJECT_TYPES: tuple[str, ...]`; `canonical_subject_type(s: str) -> str` (normalizes, unknown stays distinct, empty -> `"entity"`); `is_self_referential(label: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/extraction/test_identity.py
from stele.extraction.identity import canonical_subject_type, is_self_referential


def test_subject_type_seeded_and_default():
    assert canonical_subject_type("Service") == "service"
    assert canonical_subject_type("") == "entity"        # empty -> default
    assert canonical_subject_type("widget") == "widget"  # unknown kept distinct


def test_self_referential_detection():
    assert is_self_referential("I")
    assert is_self_referential("me")
    assert is_self_referential("the user")
    assert not is_self_referential("postgres")
    assert not is_self_referential("Test 1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_identity.py -q`
Expected: FAIL (ImportError: cannot import name `canonical_subject_type`).

- [ ] **Step 3: Implement**

```python
# add to src/stele/extraction/identity.py
SEEDED_SUBJECT_TYPES: tuple[str, ...] = (
    "service", "component", "project", "package", "person", "user", "config",
    "environment", "entity",
)

_SELF_REFERENTIAL: frozenset[str] = frozenset({
    "i", "me", "my", "myself", "mine", "the user", "current user", "user",
})


def canonical_subject_type(subject_type: str) -> str:
    """Normalize a subject_type. Empty -> 'entity'. Unknown types are kept
    distinct (lowercased token), never folded, biasing to false-negatives."""
    s = canonical_subject(subject_type)
    return s.replace(" ", "_") if s else "entity"


def is_self_referential(label: str) -> bool:
    """True when the subject label refers to the scope's user ('I', 'me', ...)."""
    return canonical_subject(label) in _SELF_REFERENTIAL
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/unit/extraction/test_identity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/identity.py tests/unit/extraction/test_identity.py
git commit -m "feat(identity): subject_type vocab + self-referential detection"
```

---

## Task 2: pure `resolve_subject` (the registry core)

**Files:**
- Create: `src/stele/extraction/registry.py`
- Test: `tests/unit/extraction/test_registry.py`

**Interfaces:**
- Consumes: `canonical_subject`, `canonical_subject_type`, `is_self_referential` (Task 1).
- Produces:
  - `class ExistingSubject` (frozen): `subject_id: str`, `subject_type: str`, `normalized_label: str`.
  - `class SubjectDisambiguationError(Exception)`.
  - `def resolve_subject(*, scope_key: str, subject_type: str, raw_label: str, user_id: str | None, existing: list[ExistingSubject], aliases: dict[str, str], proposed_subject_id: str | None = None, on_ambiguous: str = "refuse") -> str` returns a `subject_id`.

Resolution order (deterministic, no LLM in this function, no embeddings):
1. self-referential label -> `f"user:{user_id}"` (requires `user_id`; if `None`, fall through).
2. VALIDATED HANDOFF: if `proposed_subject_id` (the extractor LLM's choice) exactly matches an id in `existing` -> return it. The LLM may only SELECT an active id, never invent one (unknown proposals are ignored). This is what merges unaliased cross-session drift ("production" handed off to `service:postgres`) without cosine or auto-merge.
3. alias map hit (`aliases[normalized_label]`) -> that target id.
4. exact match against `existing` (same `subject_type` AND `normalized_label`) -> its id; more than one match -> ambiguous.
5. mint: `subject_id = f"{subject_type}:{normalized_label}"` (deterministic; same label re-mints the same id; handoff and aliases bind DIFFERENT labels).
6. ambiguous -> `on_ambiguous == "mint"` mints a fresh id, else raises `SubjectDisambiguationError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/extraction/test_registry.py
import pytest

from stele.extraction.registry import (
    ExistingSubject, SubjectDisambiguationError, resolve_subject,
)


def _resolve(label, *, existing=None, aliases=None, user_id=None,
             subject_type="service", on_ambiguous="refuse", proposed_subject_id=None):
    return resolve_subject(
        scope_key="ns=proj", subject_type=subject_type, raw_label=label,
        user_id=user_id, existing=existing or [], aliases=aliases or {},
        proposed_subject_id=proposed_subject_id, on_ambiguous=on_ambiguous,
    )


def test_mint_is_deterministic_same_label():
    assert _resolve("postgres") == _resolve("postgres") == "service:postgres"


def test_alias_binds_different_label_to_same_id():
    # the #69 fix (curated path): "production" is an explicit alias of postgres
    aliases = {"production": "service:postgres"}
    assert _resolve("production", aliases=aliases) == "service:postgres"


def test_validated_handoff_selects_existing_id():
    # the #69 fix (no manual alias): the extractor LLM saw the active subjects and
    # handed back the existing id for a drifted label.
    existing = [ExistingSubject("service:postgres", "service", "postgres")]
    assert _resolve("production", existing=existing,
                    proposed_subject_id="service:postgres") == "service:postgres"


def test_invalid_handoff_is_ignored_then_mints():
    # the LLM may only SELECT an active id; an unknown proposal is ignored.
    assert _resolve("production", proposed_subject_id="service:bogus") == "service:production"


def test_distinct_labels_stay_distinct_without_alias():
    # no auto-merge: over-merge is worse than under-merge
    assert _resolve("postgres") != _resolve("mysql")


def test_self_referential_resolves_to_user():
    assert _resolve("I", user_id="u42", subject_type="user") == "user:u42"
    assert _resolve("the user", user_id="u42", subject_type="user") == "user:u42"


def test_ambiguous_refuses_by_default():
    existing = [
        ExistingSubject("service:pg-a", "service", "postgres"),
        ExistingSubject("service:pg-b", "service", "postgres"),
    ]
    with pytest.raises(SubjectDisambiguationError):
        _resolve("postgres", existing=existing)


def test_ambiguous_mints_when_policy_allows():
    existing = [
        ExistingSubject("service:pg-a", "service", "postgres"),
        ExistingSubject("service:pg-b", "service", "postgres"),
    ]
    out = _resolve("postgres", existing=existing, on_ambiguous="mint")
    assert out == "service:postgres"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_registry.py -q`
Expected: FAIL (module `registry` not found).

- [ ] **Step 3: Implement**

```python
# src/stele/extraction/registry.py
"""Pure, deterministic subject-identity resolution. No DB, no LLM, no embeddings.
The LLM proposes a raw label; this resolves it to a stable subject_id keyed within
a scope. Over-merge is worse than under-merge: only an explicit alias or a
self-referential rule binds different labels; everything else stays distinct."""
from __future__ import annotations

from dataclasses import dataclass

from stele.extraction.identity import canonical_subject, canonical_subject_type


@dataclass(frozen=True)
class ExistingSubject:
    subject_id: str
    subject_type: str
    normalized_label: str


class SubjectDisambiguationError(Exception):
    """Raised when a label matches more than one existing subject in scope and
    the policy is to refuse rather than mint."""


def resolve_subject(
    *,
    scope_key: str,
    subject_type: str,
    raw_label: str,
    user_id: str | None,
    existing: list[ExistingSubject],
    aliases: dict[str, str],
    proposed_subject_id: str | None = None,
    on_ambiguous: str = "refuse",
) -> str:
    stype = canonical_subject_type(subject_type)
    norm = canonical_subject(raw_label)
    from stele.extraction.identity import is_self_referential
    if user_id and is_self_referential(raw_label):
        return f"user:{user_id}"
    if proposed_subject_id and proposed_subject_id in {e.subject_id for e in existing}:
        return proposed_subject_id   # validated LLM handoff (select-only, never invent)
    if norm in aliases:
        return aliases[norm]
    matches = [e for e in existing if e.subject_type == stype and e.normalized_label == norm]
    if len(matches) == 1:
        return matches[0].subject_id
    if len(matches) > 1:
        if on_ambiguous == "mint":
            return f"{stype}:{norm}"
        raise SubjectDisambiguationError(
            f"label {raw_label!r} ({stype}) is ambiguous in scope {scope_key!r}: "
            f"{[m.subject_id for m in matches]}"
        )
    return f"{stype}:{norm}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/unit/extraction/test_registry.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/registry.py tests/unit/extraction/test_registry.py
git commit -m "feat(registry): pure deterministic resolve_subject (exact/alias/self-ref/mint/disambiguate)"
```

---

## Task 3: SlotKey gains scope + type + subject_id

**Files:**
- Modify: `src/stele/extraction/consolidation.py`
- Test: `tests/unit/extraction/test_consolidation_plan.py`

**Interfaces:**
- Produces: `SlotKey(scope_key: str, subject_type: str, subject_id: str, aspect: str)`; `slot_for(mem, *, scope_key, subject_id, subject_type) -> SlotKey | None`. `plan_chains` unchanged in shape; `overlap_warnings` keys on `subject_id`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/extraction/test_consolidation_plan.py
from stele.extraction.consolidation import SlotKey, slot_for
from stele.extraction.session import SessionMemory


def test_slot_key_includes_scope_type_subject_id():
    mem = SessionMemory(kind="fact", summary="Postgres 16", detail="",
                        subject_label="postgres", aspect="version")
    slot = slot_for(mem, scope_key="ns=proj", subject_id="service:postgres",
                    subject_type="service")
    assert slot == SlotKey("ns=proj", "service", "service:postgres", "version")


def test_non_fact_has_no_slot():
    mem = SessionMemory(kind="instruction", summary="do x", detail="",
                        subject_label="", aspect="")
    assert slot_for(mem, scope_key="ns=proj", subject_id="x", subject_type="entity") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_consolidation_plan.py -q`
Expected: FAIL (`SlotKey` takes 2 positional args / `slot_for` signature mismatch).

- [ ] **Step 3: Implement**

```python
# src/stele/extraction/consolidation.py  (replace SlotKey, slot_for, overlap_warnings)
@dataclass(frozen=True)
class SlotKey:
    scope_key: str
    subject_type: str
    subject_id: str
    aspect: str


def slot_for(mem: SessionMemory, *, scope_key: str, subject_id: str,
             subject_type: str) -> SlotKey | None:
    if mem.kind != "fact":
        return None
    asp = canonical_aspect(mem.aspect)
    if not subject_id or not asp:
        return None
    return SlotKey(scope_key, subject_type, subject_id, asp)


def overlap_warnings(chains: dict[SlotKey, list[Slotted]]) -> list[tuple[str, list[str]]]:
    """Aspect-drift detector (log-only): one subject_id carrying >1 aspect slot."""
    by_subject: dict[str, list[str]] = {}
    for slot in chains:
        by_subject.setdefault(slot.subject_id, []).append(slot.aspect)
    return [(s, asp) for s, asp in by_subject.items() if len(asp) > 1]
```

Remove the now-unused `canonical_subject` import if ruff flags it (`canonical_aspect` is still used).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/unit/extraction/test_consolidation_plan.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/consolidation.py tests/unit/extraction/test_consolidation_plan.py
git commit -m "feat(consolidation): slot key gains scope_key + subject_type + subject_id"
```

---

## Task 4: alias config

**Files:**
- Modify: `src/stele/core/config.py`
- Test: `tests/unit/core/test_config.py` (or the existing config test module)

**Interfaces:**
- Produces: `ExtractionConfig.subject_aliases: dict[str, str]` (default `{}`), normalized-label -> subject_id.

- [ ] **Step 1: Write the failing test**

```python
def test_extraction_config_subject_aliases_default_empty():
    from stele.core.config import ExtractionConfig
    assert ExtractionConfig().subject_aliases == {}
    cfg = ExtractionConfig(subject_aliases={"production": "service:postgres"})
    assert cfg.subject_aliases["production"] == "service:postgres"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/unit/core/test_config.py -q -k subject_aliases`
Expected: FAIL (no attribute `subject_aliases`).

- [ ] **Step 3: Implement**

```python
# in ExtractionConfig (src/stele/core/config.py), alongside consolidation_enabled
    # Explicit alias map: normalized subject label -> subject_id. The deterministic
    # bind for cross-session entities the LLM names differently (the #69 fix).
    # Empty by default; never auto-populated. Keys are canonical_subject() output.
    subject_aliases: dict[str, str] = {}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/unit/core/test_config.py -q -k subject_aliases`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stele/core/config.py tests/unit/core/test_config.py
git commit -m "feat(config): ExtractionConfig.subject_aliases for explicit subject binding"
```

---

## Task 5: resolve subjects in `from_session` + key cross-session on subject_id

**Files:**
- Modify: `src/stele/extraction/extractor.py`
- Test: `tests/contract/test_consolidation_from_session.py` (existing tests must stay green)

**Interfaces:**
- Consumes: `resolve_subject`, `ExistingSubject` (Task 2); `slot_for` new signature (Task 3); `ExtractionConfig.subject_aliases` (Task 4).
- Produces: each committed fact's metadata carries `subject_id` and `subject_type`; `_cross_session_superseded` matches on `subject_id`.

Helper to derive a scope_key without session (reuse the existing scope-key convention):

- [ ] **Step 1: Write the failing test (existing same-session chain still works under the new key)**

The existing `test_same_session_supersedes_within_slot` already asserts the chain. Add an assertion that `subject_id` metadata is now written:

```python
# add to tests/contract/test_consolidation_from_session.py
def test_committed_facts_carry_subject_id(tmp_path):
    s = _stele(tmp_path)
    scope = MemoryScope(namespace="sid", session_id="s1")
    transcript = [
        {"role": "user", "content": "Test 1 not run; covers RAG. " + "x" * 4100},
        {"role": "assistant", "content": "Test 1 passed; covers RAG and graph. " + "y" * 4100},
    ]
    s.extract.from_session(transcript=transcript, scope=scope, llm=_fake_llm, source_ref=None)
    hits = s.memory.search(MemoryQuery(query="Test 1", scope=scope, limit=50,
                                       include_superseded=True))
    assert all(m.metadata.get("subject_id") for m in hits if m.metadata.get("aspect"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/contract/test_consolidation_from_session.py -q`
Expected: the new test FAILS (no `subject_id` metadata); existing tests may also fail once `slot_for` changes, which is expected mid-task.

- [ ] **Step 3: Implement**

In `from_session`, before the slotting loop, build the resolution context and resolve per fact. Replace the `slotted.append(...)` body:

```python
# extractor.py, inside from_session
scope_key = _scope_key_no_session(scope)          # see helper below
active = _active_subjects(self._memory, scope)     # list[ExistingSubject]
aliases = self._config.subject_aliases
slotted: list[Slotted] = []
for w_idx, window in windows(turns, max_chars=4000, limit=max_windows):
    for e_idx, mem in enumerate(extract_session_memories(llm, window)):
        slot = None
        if mem.kind == "fact" and canonical_subject(mem.subject_label):
            stype = canonical_subject_type(mem.subject_type or "entity")
            sid = resolve_subject(
                scope_key=scope_key, subject_type=stype,
                raw_label=mem.subject_label, user_id=scope.user_id,
                existing=active, aliases=aliases,
                proposed_subject_id=mem.subject_id,   # validated handoff (Task 6)
                on_ambiguous="refuse",
            )
            slot = slot_for(mem, scope_key=scope_key, subject_id=sid, subject_type=stype)
        slotted.append(Slotted(order=(w_idx, e_idx), memory=mem, slot=slot))
```

Add module-level helpers:

```python
def _scope_key_no_session(scope: MemoryScope) -> str:
    # canonical_scope_key is a MODULE FUNCTION in memory_record.py, not a method.
    return canonical_scope_key(scope.model_copy(update={"session_id": None}))

def _active_subjects(memory: object, scope: MemoryScope) -> list[ExistingSubject]:
    lookup = scope.model_copy(update={"session_id": None})
    rows = memory.list(lookup, status_filter=["active"], limit=500)  # type: ignore[attr-defined]
    out: list[ExistingSubject] = []
    for r in rows:
        meta = r.metadata or {}
        sid, stype = meta.get("subject_id"), meta.get("subject_type")
        if sid and stype:
            out.append(ExistingSubject(sid, stype, canonical_subject(meta.get("canonical_subject", ""))))
    return out
```

Thread the new metadata in the slot-commit loop (where `slot_meta` is built):

```python
slot_meta: dict[str, object] = {
    "canonical_subject": canonical_subject(it.memory.subject_label),
    "aspect": slot.aspect,
    "subject_id": slot.subject_id,
    "subject_type": slot.subject_type,
}
```

Update `_cross_session_superseded` to match on `subject_id` (and keep aspect):

```python
for r in results:
    meta = r.metadata or {}
    if meta.get("subject_id") != slot.subject_id:
        continue
    if meta.get("aspect") != slot.aspect:
        continue
    if not is_newer(this_recency, _record_recency(meta, r.effective_from)):
        continue
    out.append(r.id)
```

Wrap the per-fact resolution in a try/except so a `SubjectDisambiguationError` downgrades that fact to standalone (never crashes a session) and logs a warning.

- [ ] **Step 4: Run to verify all pass**

Run: `.venv/bin/pytest tests/contract/test_consolidation_from_session.py -q`
Expected: PASS (same-session, cross-session, as_of, the new subject_id test, and the `consolidation_enabled=False` test all green).

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/extractor.py tests/contract/test_consolidation_from_session.py
git commit -m "feat(extraction): resolve subjects via registry; key supersession on subject_id"
```

---

## Task 6: Known-subject handoff (prompt side) -- the efficacy fix

**Files:**
- Modify: `src/stele/extraction/session.py` (extract prompt)
- Modify: `src/stele/extraction/extractor.py` (pass active subjects WITH ids into the prompt)
- Test: `tests/unit/extraction/test_session.py`

**Interfaces:**
- Produces: when active subjects exist in scope, the extract prompt lists them as `subject_id (name)` pairs and instructs the LLM to set each fact's `subject_id` to an EXISTING id when the fact is about that entity, else leave it null. The returned id flows to `resolve_subject(proposed_subject_id=...)` (Task 5), which validates it EXACTLY against the active set. This is the deterministic merge path for unaliased cross-session drift (the abe-review headline). The LLM only SELECTS from active ids; it never invents identity, and recall plus the registry stay deterministic (no cosine, no auto-merge).

- [ ] **Step 1: Write the failing test**

```python
def test_prompt_offers_known_subjects_for_handoff():
    from stele.extraction.session import build_extract_prompt
    known = [("service:postgres", "postgres"), ("project:ci", "ci")]
    p = build_extract_prompt(window="...", known_subjects=known)
    assert "service:postgres" in p and "postgres" in p
    assert "subject_id" in p   # instructs the model to return an existing id
    p2 = build_extract_prompt(window="...", known_subjects=[])
    assert "service:postgres" not in p2   # nothing injected when none known
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/unit/extraction/test_session.py -q -k handoff`
Expected: FAIL (`build_extract_prompt` has no `known_subjects` param).

- [ ] **Step 3: Implement**

Add an optional `known_subjects: list[tuple[str, str]] | None = None` (id, name) to the prompt builder; when non-empty, append one deterministic block listing the pairs and instructing: "If a fact is about one of these known subjects, set its `subject_id` to that exact id; otherwise leave `subject_id` null." In `from_session`, pass `[(e.subject_id, e.normalized_label) for e in active]`.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/unit/extraction/test_session.py -q -k handoff`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/session.py src/stele/extraction/extractor.py tests/unit/extraction/test_session.py
git commit -m "feat(extraction): known-subject handoff so the LLM selects an existing subject_id"
```

---

## Task 7: contract tests for #69, scope isolation, self-reference

**Files:**
- Create: `tests/contract/test_subject_registry.py`

**Interfaces:**
- Consumes: the full from_session path (Tasks 1-6).

- [ ] **Step 1: Write the tests**

```python
# tests/contract/test_subject_registry.py
"""Contract: registry-backed identity fixes cross-session label drift (#69),
keeps different users isolated, and resolves self-referential subjects."""
from __future__ import annotations

import json

from stele.core.config import StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope
from stele.core.stash import Stele


def _stele(tmp_path, **aliases):
    cfg = StashConfig.model_validate({
        "backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")},
        "extraction": {"enabled": True, "subject_aliases": aliases},
    })
    return Stele(cfg)


def _llm(subject_label, value):
    def _fake(_window):
        return json.dumps([{"kind": "fact", "summary": value, "detail": "",
                            "subject_label": subject_label, "aspect": "version"}])
    return _fake


def test_alias_resolves_cross_session_label_drift(tmp_path):
    # #69: day1 says "postgres", day2 says "production" for the same entity.
    s = _stele(tmp_path, production="service:postgres")
    ns = "p69"
    s.extract.from_session(transcript=[{"role": "user", "content": "pg 14 " + "x" * 4100}],
                           scope=MemoryScope(namespace=ns, session_id="d1"),
                           llm=_llm("postgres", "Postgres 14"), source_ref=None)
    s.extract.from_session(transcript=[{"role": "user", "content": "pg 16 " + "y" * 4100}],
                           scope=MemoryScope(namespace=ns, session_id="d2"),
                           llm=_llm("production", "Postgres 16"), source_ref=None)
    active = s.memory.search(MemoryQuery(query="Postgres", scope=MemoryScope(namespace=ns), limit=50))
    summaries = {m.summary for m in active}
    assert "Postgres 16" in summaries
    assert "Postgres 14" not in summaries          # superseded via alias -> one head


def test_no_alias_keeps_distinct_no_silent_merge(tmp_path):
    # Without an alias, distinct labels stay distinct (false-negative bias).
    s = _stele(tmp_path)
    ns = "pnoalias"
    s.extract.from_session(transcript=[{"role": "user", "content": "pg 14 " + "x" * 4100}],
                           scope=MemoryScope(namespace=ns, session_id="d1"),
                           llm=_llm("postgres", "Postgres 14"), source_ref=None)
    s.extract.from_session(transcript=[{"role": "user", "content": "pg 16 " + "y" * 4100}],
                           scope=MemoryScope(namespace=ns, session_id="d2"),
                           llm=_llm("production", "Postgres 16"), source_ref=None)
    active = s.memory.search(MemoryQuery(query="Postgres", scope=MemoryScope(namespace=ns), limit=50))
    summaries = {m.summary for m in active}
    assert summaries == {"Postgres 14", "Postgres 16"}   # both active, nothing merged


def test_handoff_merges_cross_session_without_alias(tmp_path):
    # The efficacy path: no alias configured. Day2's extractor LLM performs the
    # handoff, returning the existing subject_id for the drifted label "production".
    s = _stele(tmp_path)
    ns = "phandoff"
    s.extract.from_session(transcript=[{"role": "user", "content": "pg 14 " + "x" * 4100}],
                           scope=MemoryScope(namespace=ns, session_id="d1"),
                           llm=_llm("postgres", "Postgres 14"), source_ref=None)

    def _llm_handoff(_w):
        # day1 minted "entity:postgres" (subject_type defaults to "entity"); the
        # handoff returns that exact id for the drifted label.
        return json.dumps([{"kind": "fact", "summary": "Postgres 16", "detail": "",
                            "subject_label": "production", "aspect": "version",
                            "subject_id": "entity:postgres"}])

    s.extract.from_session(transcript=[{"role": "user", "content": "pg 16 " + "y" * 4100}],
                           scope=MemoryScope(namespace=ns, session_id="d2"),
                           llm=_llm_handoff, source_ref=None)
    active = {m.summary for m in s.memory.search(MemoryQuery(query="Postgres",
                scope=MemoryScope(namespace=ns), limit=50))}
    assert "Postgres 16" in active and "Postgres 14" not in active   # merged via handoff


def test_two_users_do_not_collide(tmp_path):
    # Same label + aspect, different user_id -> separate chains, no supersession.
    s = _stele(tmp_path)
    ns = "pusers"
    s.extract.from_session(transcript=[{"role": "user", "content": "loc " + "x" * 4100}],
                           scope=MemoryScope(namespace=ns, user_id="A", session_id="s"),
                           llm=_llm("location", "Paris"), source_ref=None)
    s.extract.from_session(transcript=[{"role": "user", "content": "loc " + "y" * 4100}],
                           scope=MemoryScope(namespace=ns, user_id="B", session_id="s"),
                           llm=_llm("location", "London"), source_ref=None)
    a = {m.summary for m in s.memory.search(MemoryQuery(query="loc",
            scope=MemoryScope(namespace=ns, user_id="A"), limit=50))}
    b = {m.summary for m in s.memory.search(MemoryQuery(query="loc",
            scope=MemoryScope(namespace=ns, user_id="B"), limit=50))}
    assert "Paris" in a and "London" not in a
    assert "London" in b and "Paris" not in b


def test_self_referential_same_user_supersedes(tmp_path):
    # Same user moving: "I" in Paris then "I" in London -> one active head.
    s = _stele(tmp_path)
    ns = "pself"
    for sess, city in (("d1", "Paris"), ("d2", "London")):
        s.extract.from_session(
            transcript=[{"role": "user", "content": f"i am in {city} " + "z" * 4100}],
            scope=MemoryScope(namespace=ns, user_id="u9", session_id=sess),
            llm=_llm("I", city), source_ref=None)
    active = {m.summary for m in s.memory.search(MemoryQuery(query="city",
            scope=MemoryScope(namespace=ns, user_id="u9"), limit=50))}
    assert "London" in active and "Paris" not in active   # self-ref -> user:u9 chain
```

- [ ] **Step 2: Run to verify they fail, then pass after fixes**

Run: `.venv/bin/pytest tests/contract/test_subject_registry.py -q`
Expected: PASS once Tasks 1-6 are integrated. If `test_two_users_do_not_collide` fails, confirm `memory.list` honors `user_id` in scope; if it does not, that is a real scope-matching bug to fix in the memory backend (raise it, do not weaken the test).

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_subject_registry.py
git commit -m "test(registry): #69 alias resolution, scope isolation, self-reference contracts"
```

---

## Task 8: additive backfill for existing 0.6.3 stores

**Files:**
- Create: `src/stele/extraction/migration.py`
- Test: `tests/contract/test_subject_registry.py` (add a backfill case)

**Interfaces:**
- Produces: `def backfill_subject_ids(memory, scope, *, default_subject_type="entity") -> int` returns count backfilled. For each memory (active + superseded) with `canonical_subject` + `aspect` metadata but no `subject_id`, write `subject_id = f"{default_subject_type}:{canonical_subject}"` and `subject_type = default_subject_type` via the metadata-update path (NOT a text edit). Existing memory text and supersession links are untouched.
- Why this is invariant-safe (abe-adjudicated): `subject_id` is a DERIVED index key, not the immutable fact text. Supersession links and `effective_from`/`effective_until` are untouched, so `as_of` recovery is preserved. (codex: additive metadata patch beats rewrite-by-supersession, which would fabricate new active heads and effective times.) Idempotent: rows that already carry `subject_id` are skipped, so re-running is a no-op.

- [ ] **Step 1: Write the failing test**

```python
def test_backfill_maps_legacy_chains(tmp_path):
    # Simulate a pre-registry store: a memory with canonical_subject but no subject_id.
    s = _stele(tmp_path)
    ns = "pbf"
    scope = MemoryScope(namespace=ns)
    rec = s.memory.add(text="Postgres 14", kind="fact", source_refs=["stele://x/y"],
                       scope=MemoryScope(namespace=ns, session_id="d1"),
                       summary="Postgres 14", confidence=0.8,
                       metadata={"canonical_subject": "postgres", "aspect": "version"})
    from stele.extraction.migration import backfill_subject_ids
    n = backfill_subject_ids(s.memory, scope)
    assert n == 1
    got = s.memory.get(rec.record.id)
    assert got.metadata["subject_id"] == "entity:postgres"
    assert got.metadata["subject_type"] == "entity"
    assert backfill_subject_ids(s.memory, scope) == 0   # idempotent: re-run is a no-op
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/contract/test_subject_registry.py -q -k backfill`
Expected: FAIL (module `migration` not found).

- [ ] **Step 3: Implement**

```python
# src/stele/extraction/migration.py
"""Additive backfill: give pre-registry (0.6.3) memories a subject_id without
rewriting immutable memory text. Idempotent: rows that already have subject_id are
skipped. Ambiguous legacy collisions are left as integrity warnings, never merged."""
from __future__ import annotations

import logging

from stele.core.memory_record import MemoryScope
from stele.extraction.identity import canonical_subject

_log = logging.getLogger(__name__)


def backfill_subject_ids(memory: object, scope: MemoryScope, *,
                         default_subject_type: str = "entity") -> int:
    rows = memory.list(scope, status_filter=["active", "superseded"], limit=10_000)  # type: ignore[attr-defined]
    n = 0
    for r in rows:
        meta = dict(r.metadata or {})
        if meta.get("subject_id") or not meta.get("canonical_subject") or not meta.get("aspect"):
            continue
        norm = canonical_subject(meta["canonical_subject"])
        meta["subject_id"] = f"{default_subject_type}:{norm}"
        meta["subject_type"] = default_subject_type
        memory.update_metadata(r.id, meta)  # type: ignore[attr-defined]  # metadata only, text immutable
        n += 1
    return n
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/contract/test_subject_registry.py -q -k backfill`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stele/extraction/migration.py tests/contract/test_subject_registry.py
git commit -m "feat(migration): additive subject_id backfill for pre-registry stores"
```

---

## Final gate

- [ ] Run the before-commit trio:

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest
```
Expected: all green (the full suite was ~1054 passing before this plan; new tests add to that).

- [ ] Confirm the `consolidation_enabled=False` path still commits everything standalone (the existing toggle test stays green): registry resolution only runs inside the chain path.

---

## Self-Review

**Spec coverage:** Interfaces / schema -> Task 0. Subject Registry (spec "Subject Registry") -> Tasks 1, 2, 4, 5. Supersession key `(scope, subject_type, subject_id, aspect)` -> Tasks 3, 5. Known-subject handoff, the efficacy fix for unaliased drift (abe headline) -> Tasks 0, 2, 6, 7. Self-referential subject (the Q2c gap) -> Tasks 1, 2, 7. Over-merge protection / no silent merge -> Tasks 2, 7. Additive backfill (spec "Migration") -> Task 8. NOT in this plan (correctly deferred): `state`/`knowledge`/`both` modes, materialized projection, horizon isolation, relative-date anchoring.

**Open decisions surfaced for the implementer:** (1) RESOLVED by abe review and Task 0: `canonical_scope_key(scope)` is a module function (not a method), and `SessionMemory` gains `subject_type` + `subject_id`. (2) whether `subject_id` is unique within `scope` or within `(scope, subject_type)` (this plan mints `{subject_type}:{label}`, i.e. unique within `(scope, subject_type)`); confirm before Task 3. (3) Backfill default `subject_type` is `"entity"`; if a store has type-able subjects, a richer backfill is a follow-on.

**Validation:** reviewed by abe (gemma + qwen + codex), fix-first verdict applied: added Task 0, the known-subject handoff (Task 6 + the `proposed_subject_id` path in Task 2), backfill hardening (Task 8), and the `canonical_scope_key` function fix (Task 5).

**Placeholder scan:** no TBD/TODO; every code step has real code.

**Type consistency:** `ExistingSubject(subject_id, subject_type, normalized_label)` used identically in Tasks 2, 5; `SlotKey(scope_key, subject_type, subject_id, aspect)` used in Tasks 3, 5; `resolve_subject(...)` signature identical in Tasks 2, 5.
