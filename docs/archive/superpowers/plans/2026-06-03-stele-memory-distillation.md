# Stele Per-Mode Memory Distillation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `stele/distill/` subsystem exposing six discrete async functions (`distill_facts`, `distill_precedents`, `distill_state`, `distill_skills`, `distill_best_practices`, `distill_rules`) that turn raw agent material into distilled, structured, externally-consumable views, reproducing this session's hand-sorted gold.

**Architecture:** `distill/` mirrors `recall/`: a facade (`Stele.distill`) over per-mode modules that consume ONLY public facades (`Stele.memory` / `.extract` / `.recall` / `.fetch`), never storage internals, with no LLM client imported at module top (the LLM is injected, opt-in). The classification fix that lets rules be tagged as rules lives in `extraction/` (patterns + classifier), not in `distill/`. Each function is an awaitable coroutine plus a `ThreadPoolExecutor`-backed background submit/result path.

**Tech Stack:** Python 3.12, Pydantic models, `lede` (via the extract facade) for fact extraction, deterministic regex pattern packs for classification, optional OpenAI-compatible LLM (injected) for synthesis, postgres backend (`STELE_PG_DSN`), pytest.

**Mission brief:** `skill-output/mission-brief/Mission-Brief-stele-memory-distillation.md`. Success criteria SC-001..SC-011 and drift checkpoints DC-001..DC-FINAL are referenced inline.

---

## File Structure

**New (`src/stele/distill/`):**
- `__init__.py` — exports `Distill`, the `DistilledView` models.
- `models.py` — `DistilledItem`, `DistilledView`, `Rule` (with `dont`/`do_instead`), per-mode result types. Frozen Pydantic.
- `base.py` — shared helpers: `_active_memories(scope)`, dedup, evidence-ref collection, the `LLMSynthesizer` Protocol (injected, optional).
- `facade.py` — `Distill` class: the six `async def distill_*` methods + `submit`/`result` background path.
- `facts.py` — `distill_facts` core (lede structured facts via extract facade).
- `precedents.py` — `distill_precedents` core (episodes via recall).
- `state.py` — `distill_state` core (supersession head + WorkGraph reconstruction).
- `behavioral.py` — `distill_skills`, `distill_best_practices`, `distill_rules` cores (classify + synthesize; rules produce `dont`/`do_instead`).
- `jobs.py` — `DistillJob` handle + `ThreadPoolExecutor` runner for the background path.

**Modified:**
- `src/stele/extraction/patterns.py` — add `pitfall` pack (prohibition language) and `remediation` pack ("use X instead" / "prefer X"); these are the classification fix.
- `src/stele/extraction/classifier.py` — map remediation matches to `workaround`/`tool_recommendation`; ensure prohibition maps to `pitfall` over `instruction` when negative.
- `src/stele/core/stash.py` — add the lazy `@property def distill(self) -> Distill` (mirror `recall`, near line 1023).
- `src/stele/core/config.py` — add `DistillConfig` (overlay-on default, synthesis mode), wire into `StashConfig`.
- `src/stele/mcp/tools.py` — register `stele_distill_<mode>` tools.
- `src/stele/cli/commands/distill.py` (new) + `src/stele/cli/__init__.py` — `stele distill <mode>` verb via `data_plane.invoke`.

**Tests:**
- `tests/unit/distill/test_architecture.py` — import-layer assertion (mirror recall).
- `tests/unit/distill/test_models.py`, `test_facts.py`, `test_precedents.py`, `test_state.py`, `test_behavioral.py`, `test_jobs.py`.
- `tests/unit/extraction/test_classifier_rules.py` — per-kind classification on a labeled fixture (the bottleneck).
- `tests/contract/test_distill_surface_parity.py` — MCP/CLI parity (mirror `test_memory_modes_surface_parity.py`).
- `benchmarks/external/memory_modes/distill_gold.py` — frozen gold from this session's hand-sorted fixtures + a scorer.

---

## Task 1: DistilledView models + package skeleton

**Files:**
- Create: `src/stele/distill/__init__.py`, `src/stele/distill/models.py`
- Test: `tests/unit/distill/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/distill/test_models.py
from stele.distill.models import DistilledItem, DistilledView, Rule


def test_rule_carries_dont_and_do_instead_and_evidence():
    r = Rule(dont="use gpt-4o", do_instead="use gpt-5-mini", domain="config",
             confidence=0.9, source_refs=["stele://default/abc"])
    assert r.dont and r.do_instead
    assert r.source_refs  # SC-011 evidence


def test_view_is_json_serializable_and_typed():
    v = DistilledView(mode="rules", items=[
        DistilledItem(summary="gpt-4o is outdated", source_refs=["stele://default/abc"])
    ])
    blob = v.model_dump_json()
    assert '"mode":"rules"' in blob.replace(" ", "")
    assert v.items[0].source_refs == ["stele://default/abc"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/distill/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stele.distill'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/stele/distill/models.py
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field

class DistilledItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    summary: str
    detail: str = ""
    confidence: float = 1.0
    source_refs: list[str] = Field(default_factory=list)  # SC-011

class Rule(DistilledItem):
    """A guardrail distilled as a don't/do pair (SC-005)."""
    dont: str = ""
    do_instead: str = ""        # in-family remediation only (NEVER cross-vendor)
    domain: str = "prose"

class DistilledView(BaseModel):
    model_config = ConfigDict(frozen=True)
    mode: str                    # facts|precedents|state|skills|best_practices|rules
    items: list[DistilledItem] = Field(default_factory=list)
    used_llm: bool = False
    stats: dict[str, float] = Field(default_factory=dict)
```

```python
# src/stele/distill/__init__.py
from stele.distill.models import DistilledItem, DistilledView, Rule
__all__ = ["DistilledItem", "DistilledView", "Rule"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/distill/test_models.py -v` → Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stele/distill/ tests/unit/distill/test_models.py
git commit -m "feat(distill): DistilledView/Rule models + package skeleton"
```

---

## Task 2: Architecture test (facade-only, no LLM client at top) — SC-010

**Files:**
- Create: `tests/unit/distill/test_architecture.py`
- Create: `src/stele/distill/base.py` (minimal, to have something to import-check)

- [ ] **Step 1: Write the failing test** (mirror `tests/unit/recall/test_architecture.py`)

```python
# tests/unit/distill/test_architecture.py
from __future__ import annotations
import ast
from pathlib import Path
import pytest

DISTILL_ROOT = Path(__file__).resolve().parents[3] / "src" / "stele" / "distill"
FORBIDDEN_PREFIXES = ("openai", "anthropic", "pg_raggraph", "chunkshop")  # LLM is INJECTED
FORBIDDEN_EXACT = {
    "stele.storage.memory_store.base", "stele.storage.memory_store.memory",
    "stele.storage.memory_store.sqlite", "stele.storage.memory_store.postgres",
    "stele.storage.memory_store.mariadb", "stele.storage.memory_store.clickhouse",
}

def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names

@pytest.mark.parametrize("py", sorted(DISTILL_ROOT.glob("*.py")))
def test_distill_imports_only_public_facades(py: Path) -> None:
    imports = _imports(py)
    for imp in imports:
        assert imp not in FORBIDDEN_EXACT, f"{py.name} imports storage internal {imp}"
        assert not any(imp == p or imp.startswith(p + ".") for p in FORBIDDEN_PREFIXES), \
            f"{py.name} imports forbidden {imp} (LLM must be injected)"
```

- [ ] **Step 2: Run → FAIL** (no `base.py`): `.venv/bin/pytest tests/unit/distill/test_architecture.py -v`

- [ ] **Step 3: Implement minimal `base.py`**

```python
# src/stele/distill/base.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
from stele.core.memory_record import MemoryRecord, MemoryScope

@runtime_checkable
class LLMSynthesizer(Protocol):
    """Injected, optional. distill imports NO llm client at module top (SC-010)."""
    def __call__(self, prompt: str) -> str: ...

def active_memories(memory, scope: MemoryScope, limit: int = 1000) -> list[MemoryRecord]:
    """All active (newest-valid) memories in scope, via the public facade only."""
    return memory.list(scope, None, limit=limit)
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit**

```bash
git add src/stele/distill/base.py tests/unit/distill/test_architecture.py
git commit -m "test(distill): architecture import-layer gate (facade-only, LLM injected)"
```

---

## Task 3: Freeze the gold + scorer — SC-001

**Files:**
- Create: `benchmarks/external/memory_modes/distill_gold.py`
- Test: `tests/benchmarks_smoke/test_distill_gold.py`

The gold is this session's hand-sorted output. Import the existing fixtures so the gold tracks them.

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmarks_smoke/test_distill_gold.py
from benchmarks.external.memory_modes.distill_gold import GOLD, score_view

def test_gold_has_all_six_modes():
    assert set(GOLD) == {"facts","precedents","state","skills","best_practices","rules"}
    assert GOLD["rules"]  # includes the gpt-4o -> gpt-5-mini pair

def test_scorer_returns_precision_recall():
    s = score_view("facts", predicted_ids=["pg-raggraph","lede"])
    assert 0.0 <= s["recall"] <= 1.0 and 0.0 <= s["precision"] <= 1.0
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** (pull from `validate_on_yonk_tools.py` so gold == hand-sorted)

```python
# benchmarks/external/memory_modes/distill_gold.py
"""Frozen gold = this session's hand-sorted distillation. The distill_* functions
must reproduce THIS. Sourced from validate_on_yonk_tools (real yonk-tools data)."""
from __future__ import annotations
from benchmarks.external.memory_modes.validate_on_yonk_tools import FACTS, PRECEDENTS

GOLD: dict[str, list[dict]] = {
    "facts": [{"id": proj, "text": purpose} for proj, purpose, _q in FACTS],
    "precedents": [{"id": sha, "query": q} for q, sha in PRECEDENTS],
    "rules": [
        {"dont": "use gpt-4o", "do_instead": "use gpt-5-mini", "domain": "config",
         "in_family": True},
        {"dont": "use a single connection", "do_instead": "use a connection pool",
         "domain": "python"},
        {"dont": "edit the vendored llama.cpp test dir", "do_instead": "update the vendored copy deliberately",
         "domain": "path"},
    ],
    "skills": [{"id": "async-pools", "text": "all DB ops async, use pools"}],
    "best_practices": [{"id": "determinism", "text": "prefer a deterministic check over an LLM judge"}],
    "state": [{"id": "headroom-hypothesis", "gold": "abandoned"},
              {"id": "pg-lexicon-phase-f", "gold": "done"}],
}

def score_view(mode: str, predicted_ids: list[str]) -> dict[str, float]:
    gold_ids = {g.get("id") or g.get("dont") for g in GOLD[mode]}
    pred = set(predicted_ids)
    tp = len(gold_ids & pred)
    recall = tp / len(gold_ids) if gold_ids else 0.0
    precision = tp / len(pred) if pred else 0.0
    return {"recall": recall, "precision": precision, "hit_at_1": float(bool(tp))}
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit**: `git commit -am "bench(distill): freeze hand-sorted gold + scorer (SC-001)"`

---

## Task 4: Classification fix — pitfall + remediation packs — SC-002 / ⛔ DC-002

**Files:**
- Modify: `src/stele/extraction/patterns.py` (add packs)
- Modify: `src/stele/extraction/classifier.py` (default overlay on for distill path)
- Test: `tests/unit/extraction/test_classifier_rules.py`

- [ ] **Step 1: Write the failing test** (the bottleneck the PoC exposed)

```python
# tests/unit/extraction/test_classifier_rules.py
import pytest
from stele.extraction.classifier import classify_kind

# (text, expected_kind) — real rule language from yonk-tools CLAUDE.md files
CASES = [
    ("NEVER use gpt-4o, it is outdated", "pitfall"),
    ("do not edit the vendored llama.cpp test directory", "pitfall"),
    ("always use a connection pool, never a single connection", "instruction"),
    ("use gpt-5-mini instead", "workaround"),
    ("prefer a deterministic check over an LLM judge", "preference"),
    ("the prod database moved to us-west-2 on 1 April 2024", "fact"),
]

@pytest.mark.parametrize("text,expected", CASES)
def test_rule_language_is_not_collapsed_to_fact(text, expected):
    out = classify_kind(text=text, lede_source="key_fact", overlay_enabled=True)
    assert out.kind == expected, f"{text!r} -> {out.kind}, expected {expected}"
```

- [ ] **Step 2: Run → FAIL** (no `pitfall`/`workaround` packs; prohibitions fall to `instruction` or `fact`)

- [ ] **Step 3: Implement** — add packs to `patterns.py` BEFORE the `instruction` pack (first-match wins per `match_first_kind`):

```python
# in PATTERN_PACKS, ordered so pitfall/remediation are tried before instruction:
PatternPack(kind="pitfall", kind_weight=0.85, patterns=[
    re.compile(r"(?i)\bnever\b.*\b(use|do|edit|call|import|run)\b"),
    re.compile(r"(?i)\b(do not|don'?t)\b.*\b(use|edit|call|import|widen|bypass)\b"),
    re.compile(r"(?i)\b(outdated|deprecated|forbidden|banned)\b"),
]),
PatternPack(kind="workaround", kind_weight=0.8, patterns=[
    re.compile(r"(?i)\buse\b.+\binstead\b"),
    re.compile(r"(?i)\b(instead of|rather than|in place of)\b"),
]),
```

Keep the existing `instruction` pack (positive "always/please do") and `preference` pack after these. The classifier already returns the pack kind when `pack.kind_weight > default_confidence`; pitfall (0.85) and workaround (0.8) beat the `key_fact` default (0.7), so they win.

- [ ] **Step 4: Run → PASS** (all 6 cases classify correctly). Then full extraction suite: `.venv/bin/pytest tests/unit/extraction -q` (no regressions).

- [ ] **⛔ DC-002 gate:** Re-read the mission brief. Verify SC-002: run the classifier on a hand-labeled sample of a real CLAUDE.md and confirm rule-kinds recall/precision >= 0.70. If below floor, reassess (more packs vs LLM-assisted classify) before continuing.

- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat(extraction): pitfall + remediation pattern packs so rules aren't collapsed to fact (SC-002, DC-002)"`

---

## Task 5: Distill facade + Stele.distill property + DistillConfig

**Files:**
- Create: `src/stele/distill/facade.py`
- Modify: `src/stele/core/stash.py` (lazy property near line 1023), `src/stele/core/config.py` (DistillConfig)
- Test: `tests/unit/distill/test_facade.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/distill/test_facade.py
from stele import Stele

def test_distill_facade_attaches_and_lists_methods():
    s = Stele.from_config({"backend": {"type": "memory"}})
    d = s.distill
    for m in ("facts","precedents","state","skills","best_practices","rules"):
        assert callable(getattr(d, m))
```

- [ ] **Step 2: Run → FAIL** (`Stele has no attribute distill`)

- [ ] **Step 3: Implement** the facade with async methods delegating to per-mode cores, plus `DistillConfig`, plus the lazy property in `stash.py`:

```python
# src/stele/distill/facade.py
from __future__ import annotations
from stele.core.memory_record import MemoryScope
from stele.distill.base import LLMSynthesizer
from stele.distill.models import DistilledView

class Distill:
    def __init__(self, *, stele, memory, extract, recall, config, llm: LLMSynthesizer | None = None):
        self._stele, self._memory, self._extract = stele, memory, extract
        self._recall, self._config, self._llm = recall, config, llm

    async def facts(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.facts import distill_facts
        return await distill_facts(self, scope)
    async def precedents(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.precedents import distill_precedents
        return await distill_precedents(self, scope)
    async def state(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.state import distill_state
        return await distill_state(self, scope)
    async def skills(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.behavioral import distill_skills
        return await distill_skills(self, scope)
    async def best_practices(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.behavioral import distill_best_practices
        return await distill_best_practices(self, scope)
    async def rules(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.behavioral import distill_rules
        return await distill_rules(self, scope)
```

```python
# src/stele/core/config.py — add near other sub-configs
class DistillConfig(BaseModel):
    overlay_patterns_enabled: bool = True   # rules must not collapse to fact
    synthesis: str = "auto"                  # "auto" uses LLM if injected, else deterministic
# and: distill: DistillConfig = Field(default_factory=DistillConfig) on StashConfig
```

```python
# src/stele/core/stash.py — mirror the recall property (~line 1023)
@property
def distill(self) -> "Distill":
    if not hasattr(self, "_distill"):
        from stele.distill.facade import Distill
        self._distill = Distill(
            stele=self, memory=self.memory, extract=self.extract,
            recall=self.recall, config=self.config.distill,
            llm=getattr(self, "_distill_llm", None),
        )
    return self._distill
```

- [ ] **Step 4: Run → FAIL** (cores not implemented yet) — acceptable: the facade test only checks methods are callable, not invoked. Confirm `test_facade.py` PASSES (methods exist) and `mypy src/stele/distill src/stele/core/stash.py` clean.

- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat(distill): Distill facade + Stele.distill property + DistillConfig"`

---

## Task 6: distill_facts (deterministic, lede-backed) — SC-003 / ⛔ DC-001

**Files:** Create `src/stele/distill/facts.py`; Test `tests/unit/distill/test_facts.py`

distill_facts groups active `kind=fact` memories (which lede's structured extraction produced), dedups, returns a `DistilledView`. No LLM.

- [ ] **Step 1: Write the failing test** (populate facts, assert reproduction against gold)

```python
# tests/unit/distill/test_facts.py
import pytest
from stele import Stele
from stele.core.memory_record import MemoryScope

@pytest.mark.asyncio
async def test_distill_facts_reproduces_stored_facts():
    s = Stele.from_config({"backend": {"type": "memory"}})
    scope = MemoryScope(namespace="t-facts")
    ref = str(s.store("pg-raggraph does GraphRAG on plain Postgres", namespace="t-facts").reference)
    s.memory.add(text="pg-raggraph does GraphRAG on plain Postgres", kind="fact",
                 source_refs=[ref], scope=scope, summary="pg-raggraph: GraphRAG on plain Postgres")
    view = await s.distill.facts(scope)
    assert view.mode == "facts"
    assert any("pg-raggraph" in it.summary for it in view.items)
    assert all(it.source_refs for it in view.items)  # SC-011
```

(Requires `pytest-asyncio`; if not present, add to dev deps or use `asyncio.run` in a sync test wrapper — check `pyproject.toml` first and follow the repo's async-test convention.)

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

```python
# src/stele/distill/facts.py
from __future__ import annotations
from stele.core.memory_record import MemoryScope
from stele.distill.base import active_memories
from stele.distill.models import DistilledItem, DistilledView

async def distill_facts(d, scope: MemoryScope) -> DistilledView:
    mems = [m for m in active_memories(d._memory, scope) if m.kind == "fact"]
    seen, items = set(), []
    for m in mems:
        key = (m.summary or m.text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(DistilledItem(summary=m.summary or m.text, detail=m.detail or "",
                                   confidence=m.confidence, source_refs=list(m.source_refs)))
    return DistilledView(mode="facts", items=items, used_llm=False,
                         stats={"n": float(len(items))})
```

- [ ] **Step 4: Run → PASS.** Then a gold test: populate the 12 gold facts, call distill_facts, assert hit-rate >= 10/12 against `distill_gold.GOLD["facts"]`.
- [ ] **⛔ DC-001 gate:** Verify SC-003 reproduced before building harder modes.
- [ ] **Step 5: Commit**: `git commit -am "feat(distill): distill_facts (deterministic, lede-backed) (SC-003)"`

---

## Task 7: distill_precedents — SC-004 / ⛔ DC-001

**Files:** Create `src/stele/distill/precedents.py`; Test `tests/unit/distill/test_precedents.py`

Episodes are `kind=decision` memories; distill ranks them by recall on a descriptor or returns the set. Mirror `precedent_recall` retrieval via `memory.search_with_score` (vector when configured).

- [ ] **Step 1: failing test** — store 3 episodes, `await s.distill.precedents(scope)`, assert each item has summary + source_refs and the set reproduces stored episodes.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `distill_precedents`: filter active `kind=decision`, dedup by summary, emit `DistilledItem(summary, detail=tool/result/next-step, source_refs)`. (Optional `query` arg ranks via `d._memory.search_with_score`.)
- [ ] **Step 4: run → PASS** + gold test: hit@1 >= 0.70 vs `GOLD["precedents"]` on the real commit episodes (vector leg on).
- [ ] **⛔ DC-001 gate.**
- [ ] **Step 5: commit** `feat(distill): distill_precedents (SC-004)`

---

## Task 8: distill_state — SC-006

**Files:** Create `src/stele/distill/state.py`; Test `tests/unit/distill/test_state.py`

Reconstruct current truth per entity from the supersession head (newest active memory per entity tag) + optional WorkGraph node status. NOT extraction-from-chat.

- [ ] **Step 1: failing test** — add superseding events for an entity, assert distill_state returns the latest state and marks an absent entity `absent`.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `distill_state`: group active memories by entity (summary prefix or metadata `entity`), take the head; classify state via the existing `resume_task_state._classify_text` helper or node status if a WorkGraph is supplied. Emit `DistilledItem(summary=entity, detail=state, source_refs)`.
- [ ] **Step 4: run → PASS** + gold slice (`headroom-hypothesis -> abandoned`, `pg-lexicon-phase-f -> done`).
- [ ] **Step 5: commit** `feat(distill): distill_state (current-truth reconstruction) (SC-006)`

---

## Task 9: distill_skills, distill_best_practices, distill_rules — SC-005 / SC-006 / ⛔ DC-003

**Files:** Create `src/stele/distill/behavioral.py`; Test `tests/unit/distill/test_behavioral.py`

Skills = active `kind=instruction` (positive). Best-practices = `kind=preference` (suggest-only, NO enforcement field). Rules = `kind=pitfall` paired with a nearby `workaround`/`tool_recommendation` to form `dont`/`do_instead`. Pairing is deterministic (same source_ref / adjacency); the LLM (if injected) refines the pairing and remediation. In-family remediation enforced.

- [ ] **Step 1: failing tests**

```python
# tests/unit/distill/test_behavioral.py (rules case)
@pytest.mark.asyncio
async def test_distill_rules_pairs_dont_with_do_instead_in_family():
    s = Stele.from_config({"backend": {"type": "memory"}})
    scope = MemoryScope(namespace="t-rules")
    ref = str(s.store("gpt-4o is outdated", namespace="t-rules").reference)
    s.memory.add(text="gpt-4o is outdated, do not use it", kind="pitfall",
                 source_refs=[ref], scope=scope, summary="gpt-4o outdated",
                 detail="use gpt-5-mini instead", metadata={"do_instead": "gpt-5-mini"})
    view = await s.distill.rules(scope)
    rule = view.items[0]
    assert "gpt-4o" in rule.dont
    assert "gpt-5-mini" in rule.do_instead
    assert "claude" not in rule.do_instead.lower()  # in-family only (NEVER cross-vendor)

@pytest.mark.asyncio
async def test_best_practices_have_no_enforcement_field():
    # suggest-not-force: DistilledItem has no 'enforce'/'gate' attribute
    s = Stele.from_config({"backend": {"type": "memory"}})
    view = await s.distill.best_practices(MemoryScope(namespace="t-bp"))
    assert not hasattr(view.items[0] if view.items else object(), "enforce")
```

- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** the three cores in `behavioral.py`. For `distill_rules`: collect `pitfall` items, find the `do_instead` from `metadata['do_instead']` / a same-ref `workaround` / (if `d._llm`) an LLM synthesis pass; build `Rule(dont, do_instead, domain, source_refs)`. Guard: if `do_instead` names a different vendor than `dont`, drop it to "" and flag (in-family rule). Set `used_llm=bool(d._llm and config.synthesis != 'deterministic')`.
- [ ] **Step 4: run → PASS** + gold test vs `GOLD["rules"]` incl the gpt-4o→gpt-5-mini pair; run once with no LLM (deterministic) and once with a fake LLM, assert both produce valid views (SC-009).
- [ ] **⛔ DC-003 gate:** Verify the don't/do pairing reproduces the gold with in-family remediation, and no enforcement field leaked (suggest-not-force).
- [ ] **Step 5: commit** `feat(distill): distill_skills/best_practices/rules with in-family don't/do pairing (SC-005,006,009,DC-003)`

---

## Task 10: Async background-job path (submit/result) — SC-007

**Files:** Create `src/stele/distill/jobs.py`; Modify `facade.py` (add `submit`/`result`); Test `tests/unit/distill/test_jobs.py`

Mirror the revisor's `ThreadPoolExecutor` precedent for the heavy/whole-corpus path.

- [ ] **Step 1: failing test** — `job = s.distill.submit("facts", scope)`; poll `s.distill.result(job.id)` returns a `DistilledView` when done.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** `DistillJob` (id, future) + a module-level `ThreadPoolExecutor`; `submit(mode, scope)` runs `asyncio.run(getattr(self, mode)(scope))` in the executor, returns a handle; `result(id)` returns the view or a "pending" sentinel. Keep awaitable methods as the inline path (already built).
- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** `feat(distill): background submit/result job path (SC-007)`

---

## Task 11: MCP tools + CLI verb (one shared handler) — SC-008 / ⛔ DC-004

**Files:** Modify `src/stele/mcp/tools.py`; Create `src/stele/cli/commands/distill.py`; Modify `src/stele/cli/__init__.py`; Test `tests/contract/test_distill_surface_parity.py`

- [ ] **Step 1: failing parity test** (mirror `test_memory_modes_surface_parity.py`): bind handlers, populate, assert `stele_distill_rules` over MCP returns the same items the facade `await s.distill.rules(scope)` returns.
- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** one MCP handler `distill(mode, namespace)` that runs `asyncio.run(getattr(stele.distill, mode)(scope))` and returns `view.model_dump()`; register `stele_distill_<mode>` (or one `stele_distill` with a `mode` arg). CLI `stele distill <mode> --namespace` routes through `data_plane.invoke("stele_distill", {...})` (one code path, no drift).
- [ ] **Step 4: run → PASS** + `mypy src tests` clean.
- [ ] **⛔ DC-004 gate:** Verify distill imports only public facades (run `test_architecture.py`) and every returned item carries evidence refs (SC-011).
- [ ] **Step 5: commit** `feat(distill): MCP tool + CLI verb via shared handler (SC-008,DC-004)`

---

## Task 12: End-to-end demo + DC-FINAL

**Files:** Create `benchmarks/external/memory_modes/distill_demo.py` (successor to `validate_on_yonk_tools.py`)

- [ ] **Step 1:** Write a script that, for a chosen project, ingests real raw sources (CLAUDE.md + git log + one session) via `s.extract`, then calls all six `await s.distill.*` and prints each `DistilledView`, plus the gold score per mode (`distill_gold.score_view`).
- [ ] **Step 2:** Run against pg-agent: `STELE_PG_DSN=... .venv/bin/python -m benchmarks.external.memory_modes.distill_demo --project pg-agent`. Eyeball that the six views reproduce the hand-sorted gold; confirm the rules view shows `gpt-4o -> gpt-5-mini`.
- [ ] **⛔ DC-FINAL:** Re-read the mission brief. Verify EVERY SC-001..SC-011 has evidence; re-confirm the deterministic (no-LLM) path works; re-confirm no per-mode score regressed against gold; re-confirm suggest-not-force (no enforcement field) and facade-only imports.
- [ ] **Step 3: full gate**: `.venv/bin/ruff check . && .venv/bin/mypy src tests benchmarks && STELE_PG_DSN=... .venv/bin/pytest -q`
- [ ] **Step 4: Commit** `bench(distill): end-to-end demo over real project sources + DC-FINAL`

---

## Self-Review Notes
- **Spec coverage:** SC-001 (Task 3), SC-002 (Task 4), SC-003 (Task 6), SC-004 (Task 7), SC-005 (Task 9), SC-006 (Tasks 8,9), SC-007 (Task 10), SC-008 (Task 11), SC-009 (Task 9), SC-010 (Task 2), SC-011 (Tasks 6-9,11). DC-001 (Tasks 6,7), DC-002 (Task 4), DC-003 (Task 9), DC-004 (Task 11), DC-FINAL (Task 12).
- **Async-test convention:** confirm `pytest-asyncio` is configured in `pyproject.toml` at Task 6; if not, wrap async cores with `asyncio.run` in sync tests rather than adding a dep without the ASK-FIRST check.
- **Type consistency:** `DistilledView(mode, items, used_llm, stats)`, `Rule(dont, do_instead, domain, ...)`, `Distill.<mode>(scope) -> DistilledView` used identically across tasks.
- **Unverified interfaces to pin during implementation (do not fabricate):** lede's exact structured-fact call path is reached via `Stele.extract` (already working), not imported directly; the LLM synthesis prompt in Task 9 is injected and its output parsed defensively (deterministic fallback on parse failure).
