---
phase: 2
title: Deterministic Extraction
created: 2026-05-13
status: design-approved
depends-on: Phase 1 complete (Tasks 0–21 of `docs/superpowers/plans/2026-05-12-phase1-memory-supersession.md`)
---

# Phase 2: Deterministic Extraction — Design

## TL;DR

Phase 2 ships a deterministic, source-traced extraction layer that turns text
(from artifacts, agent-message threads, or raw input) into accepted
`MemoryRecord` rows via Phase 1's `Memory.add()`. Extraction is fully
deterministic — no LLM, no embeddings — built on `lede.extract.*` plus a small
type-based classifier with a regex pattern overlay for agent-loop kinds.
Acceptance is gated by a static confidence threshold; rejected candidates
appear in the `ExtractionReport` with a reason. Phase 3 will replace the
static filter with a policy engine.

## Goal

Add a `stele.extract` namespace that exposes three entry points
(`from_artifact`, `from_messages`, `from_text`), all funnelling through a pure
deterministic core. Every accepted candidate becomes a `MemoryRecord` with at
least one `stele://` source_ref, a confidence score, a `MemoryKind` label, and
metadata recording which `lede` output type produced it. Every call returns an
`ExtractionReport` summarising candidates, accepted/rejected counts, PII
flags, and a config fingerprint.

## The Four Headline Proofs

1. **Fixture coverage** — five fixture categories (preferences, decisions,
   commitments, changed facts, abstention) each have passing tests proving the
   extractor produces the right kind, the right count, and the right *zero*
   (abstention).
2. **Determinism** — running extraction on the same text twice with the same
   config produces byte-identical `ExtractionReport.candidates`.
3. **PII invariant preserved** — extraction never bypasses Phase 1's PII
   scrubber on memory text.
4. **Source-ref invariant preserved** — extraction never produces a memory
   without a valid `stele://` source_ref. Phase 1's `ValidationError` fires
   if it tries.

## Locked Architectural Decisions

These were settled during brainstorming; they constrain the rest of the design.

1. **End-to-end `extract_and_store`.** The orchestrator commits accepted
   candidates via `Memory.add()`. The report includes stored memory IDs.
2. **All three inputs, one internal core.** `from_artifact`, `from_messages`,
   `from_text` all funnel through a pure
   `extract_candidates(text, source_refs)`.
3. **Type-based classifier + pattern overlay.** Default kind comes from the
   `lede` output type (`Stat`/`PhraseFact`/`key_fact` → `fact`,
   `summarize` → `summary`). A regex pattern overlay can override to
   `preference` / `decision` / `instruction` / `commitment` / `issue`.
4. **Phase 1 assumed complete.** The plan reads as if Phase 1 Tasks 10–21
   are done. Phase 2 freely depends on the full memory contract across
   memory + sqlite + postgres.
5. **Pure core + thin orchestrator.** `extract_candidates(...)` is a pure
   function (no I/O, no clock, no DB). `MemoryExtractor` is the I/O wiring.
   Mirrors the `build_reference` / `Stele` separation already present in
   `src/stele/core/reference.py`.

## Public API

### Three entry points on the `Stele` facade

```python
# 1. From a stashed artifact — source_refs derived automatically
report: ExtractionReport = stele.extract.from_artifact(
    artifact_id="abc123",
    scope=MemoryScope(user_id="alice"),
)

# 2. From a list of agent messages — auto-stashes the thread,
#    uses the resulting stele:// ref as source
report = stele.extract.from_messages(
    messages=[
        {"role": "user", "content": "I prefer dark mode"},
        {"role": "assistant", "content": "Got it."},
    ],
    scope=MemoryScope(user_id="alice"),
)

# 3. From raw text + explicit refs — caller supplies provenance
report = stele.extract.from_text(
    text="The migration deadline is 2026-06-30.",
    source_refs=["stele://default/abc123"],
    scope=MemoryScope(user_id="alice"),
)
```

`stele.extract` is a `@property` on `Stele` returning a bound `MemoryExtractor`
instance — same pattern Phase 1 uses for `Stele.memory`.

### Return shape — `ExtractionReport`

```python
class ExtractionStats(BaseModel):
    candidate_count: int
    accepted_count: int
    rejected_count: int

class ExtractionReport(BaseModel):
    candidates: list[MemoryCandidate]
    accepted: list[AcceptedCandidate]
    rejected: list[RejectedCandidate]
    pii_flags: list[str]
    source_refs: list[str]
    stats: ExtractionStats
    config_fingerprint: str
```

### Candidate models

```python
LedeSource = Literal["key_fact", "stat", "metadata", "phrase", "summary"]
ClassifierPath = Literal["type_based", "pattern_overlay"]

class MemoryCandidate(BaseModel):
    text: str
    kind: MemoryKind
    confidence: float
    lede_source: LedeSource
    classifier_path: ClassifierPath
    pattern_match: str | None = None  # regex name when overlay fired

class AcceptedCandidate(BaseModel):
    candidate: MemoryCandidate
    stored_id: str

class RejectedCandidate(BaseModel):
    candidate: MemoryCandidate
    reason: Literal[
        "below_threshold",
        "duplicate",
        "validation_error",
    ]
    duplicate_of: str | None = None
    error_message: str | None = None
```

## File Layout

### New files

| Path | Responsibility |
|---|---|
| `src/stele/extraction/__init__.py` | Re-exports `MemoryCandidate`, `ExtractionReport`, `ExtractionStats`, `AcceptedCandidate`, `RejectedCandidate` |
| `src/stele/extraction/models.py` | All pydantic models above |
| `src/stele/extraction/candidates.py` | PURE: `extract_candidates(text, source_refs, scrubber) -> list[MemoryCandidate]`; wraps `lede.extract.{key_facts, stats, metadata, phrases}` + `lede.summarize`. Scrubber is injected (Phase 1's `RegexPIIScrubber` or `DisabledPIIScrubber`) so candidate text in the report matches what `Memory.add` will store. The scrubber is itself pure (no I/O) so the core stays deterministic. |
| `src/stele/extraction/classifier.py` | PURE: `classify_kind(text, lede_source) -> tuple[MemoryKind, float, ClassifierPath, str|None]` |
| `src/stele/extraction/patterns.py` | Regex packs for `preference` / `decision` / `instruction` / `commitment` / `issue` kinds; each pattern carries a confidence weight |
| `src/stele/extraction/extractor.py` | `MemoryExtractor` — I/O orchestrator; `.from_artifact`, `.from_messages`, `.from_text`; builds source_refs, calls `Memory.add`, builds `ExtractionReport` |
| `tests/unit/extraction/__init__.py` | Package marker |
| `tests/unit/extraction/test_candidates.py` | Pure-core determinism, lede output mapping |
| `tests/unit/extraction/test_classifier.py` | Type-based defaults + pattern overlay matrix |
| `tests/unit/extraction/test_patterns.py` | Regex pack coverage for the five fixture kinds |
| `tests/unit/extraction/test_extractor.py` | Orchestrator: three entry points, duplicate handling, validation propagation |
| `tests/unit/extraction/test_abstention.py` | Zero-candidate inputs return empty `accepted`, never raise |
| `tests/unit/extraction/test_pii_invariant.py` | Double-scrub idempotence + PII fixture pass-through |
| `tests/contract/test_extraction_contract.py` | Parametrized across `memory + sqlite + postgres`; structural equivalence of `accepted_count` and `stored_id` shape |
| `tests/fixtures/extraction/preferences.json` | ≥3 positive + ≥3 abstention samples |
| `tests/fixtures/extraction/decisions.json` | Same |
| `tests/fixtures/extraction/commitments.json` | Same |
| `tests/fixtures/extraction/changed_facts.json` | Same |
| `tests/fixtures/extraction/abstention.json` | Pure-noise inputs |
| `scripts/demo-extraction.sh` | Human-readable extraction demo across the five categories |

### Modified files

| Path | Change |
|---|---|
| `src/stele/core/config.py` | Add `ExtractionConfig` Pydantic model + `extraction: ExtractionConfig` on the top-level config |
| `src/stele/core/stash.py` | Add `Stele.extract` property (~10 lines, parallel to `Stele.memory`) and wire it into `Stele.close()` |
| `src/stele/__init__.py` | Re-export `MemoryCandidate`, `ExtractionReport`, `ExtractionStats`, `AcceptedCandidate`, `RejectedCandidate` |
| `pyproject.toml` | None — `lede` is already a runtime dep for the summary adapter |

## Data Flow

```
INPUT                              PURE CORE (no I/O)                         ORCHESTRATOR (I/O)
─────                              ──────────────────                         ──────────────────

from_artifact(artifact_id, scope)
        │
        │ stele.fetch(artifact_id) ──► artifact.text, stele://ns/<id>
        ▼
                                   extract_candidates(text, source_refs, scrubber)
                                          │
                                          │ 1. lede.extract.key_facts(text)
                                          │ 2. lede.extract.stats(text)
                                          │ 3. lede.extract.metadata(text)
                                          │ 4. lede.extract.phrases(text)
                                          │ 5. lede.summarize(text)
                                          ▼
                                   raw_items: list[(text, lede_source, score)]
                                          │
                                          │ scrubber.scrub(text) per item
                                          ▼
                                   scrubbed_items + pii_flags
                                          │
                                          ▼
                                   classify_kind(text, lede_source)
                                          │  • type_based default
                                          │  • pattern_overlay override
                                          ▼
                                   list[MemoryCandidate]   ◄── PURE CORE STOPS HERE
                                                                          │
                                                                          ▼
                                                                  filter by min_confidence
                                                                          │
                                                                          ▼
                                                                  for each accepted:
                                                                    Memory.add(text, kind,
                                                                               source_refs, scope)
                                                                       │
                                                                       │ MemoryAddResult.duplicate_of?
                                                                       │   ├── yes → rejected[duplicate]
                                                                       │   └── no  → accepted[stored_id]
                                                                       ▼
                                                                  build ExtractionReport
                                                                          │
                                                                          ▼
                                                                       RETURN
```

### Flow invariants

- **PII scrubbing happens twice, intentionally.** Once in the pure core (so
  candidates *in the report* are scrubbed) and again inside `Memory.add`
  (Phase 1's invariant). `RegexPIIScrubber.scrub` is idempotent for the
  current regex set; `test_pii_invariant.py` proves this. The second pass
  is the load-bearing one.
- **The pure core never touches the clock, filesystem, or backend.** That's
  why determinism holds. `created_at` / `effective_from` are stamped inside
  `Memory.add` during the orchestrator phase.
- **Confidence threshold filtering lives in the orchestrator, not the core.**
  Phase 3's policy engine can call `extract_candidates(...)` directly and
  inspect every candidate before any filter applies.

## Configuration

New section in `core/config.py`:

```python
class ExtractionConfig(BaseModel):
    enabled: bool = True
    min_confidence: float = 0.6
    max_candidates_per_doc: int = 50
    overlay_patterns_enabled: bool = True
    summary_kind: MemoryKind = "summary"
    auto_stash_messages: bool = True
```

Defaults are picked so the showcase fixtures pass without tuning.

`config_fingerprint` on `ExtractionReport` is
`sha256(json.dumps(config.model_dump(), sort_keys=True))`. Same fingerprint
gets stored on each accepted memory's `metadata["extraction_config"]` so Phase
3 can detect drift.

## Classifier Design

### Type-based default table

| `lede_source` | Default `MemoryKind` | Default confidence |
|---|---|---|
| `key_fact` | `fact` | `0.7` |
| `stat` | `fact` | `0.8` |
| `metadata` | `fact` | `0.7` |
| `phrase` | `fact` | `0.5` |
| `summary` | `summary` | `0.9` |

### Pattern overlay

Each agent-loop kind has a regex pack in `patterns.py`. Each pack carries a
fixed `kind_weight` (a per-kind confidence) shared by every pattern in the
pack — the pattern list is "any of these strings is evidence for this kind",
not "each pattern has its own weight."

Matching rules:

1. **Per kind:** the kind matches if **any** pattern in its pack matches.
   Pattern order within the pack is irrelevant; matching is set-membership.
2. **Across kinds:** if multiple kinds match the same candidate text, the
   kind with the highest `kind_weight` wins. Ties are broken by declaration
   order in `patterns.py` (deterministic).
3. **Override:** if a kind matched and its `kind_weight > type_based_confidence`,
   `classifier_path` flips to `pattern_overlay`, `kind` becomes the matched
   kind, `confidence` becomes `kind_weight`, and `pattern_match` records the
   pack name (e.g., `"preference"`).
4. **No match:** `classifier_path` stays `type_based`, `pattern_match` is
   `None`, kind and confidence stay at the type-based defaults.

Sketch (full list lives in `patterns.py`):

| Kind | Sample patterns (any-of) | `kind_weight` |
|---|---|---|
| `preference` | `(?i)\bi (prefer|like|love|hate|dislike)\b`, `(?i)\bmy favou?rite\b` | `0.85` |
| `decision` | `(?i)\b(we|i)('ve)? decided\b`, `(?i)\blet'?s go with\b` | `0.85` |
| `instruction` | `(?i)\b(please|always|never|don'?t)\b.*\b(do|use|avoid)\b` | `0.75` |
| `commitment` | `(?i)\b(by|before)\s+\w+day\b`, `(?i)\b(TODO|FIXME)\b`, `(?i)\bi('ll| will)\s+\w+` | `0.75` |
| `issue` | `(?i)\b(bug|broken|fails?|error|crash)\b` | `0.65` |

Patterns are deliberately conservative — false negatives are better than false
positives. The fixtures lock the regression boundary.

When `overlay_patterns_enabled=False`, the overlay step is skipped entirely;
only the type-based table is used.

## Error Handling

| Condition | Behavior |
|---|---|
| `extraction.enabled = False` | `Stele.extract.*` raises `CapabilityError("extraction is disabled in config")` |
| `from_artifact(artifact_id)` for missing id | Propagates Phase 1's `ArtifactNotFound` |
| `from_messages([])` (empty list) | Returns an empty `ExtractionReport` (abstention) |
| `from_text("")` (empty text) | Returns an empty `ExtractionReport` |
| `from_text(text, source_refs=[])` | Raises `ValidationError` — Phase 1's message |
| `from_text(text, source_refs=["http://..."])` | Raises `ValidationError` — refs must be `stele://` |
| Candidate text fails `Memory.add` validation downstream | Recorded in `rejected[]` with `reason="validation_error"` and `error_message=<msg>`; extraction does NOT abort |
| `lede` raises | Wrap in `SteleError("Extraction failed during lede pass")` and re-raise. Partial results discarded — the run is atomic from the caller's view. |

**Why "candidate fails → recorded, don't abort":** a single malformed
candidate shouldn't kill the whole run. Failures become data in the report.

**Why "`lede` raises → discard everything":** `lede` failures usually
indicate malformed input (binary, encoding issues, etc.), not a per-candidate
problem. Partial extraction on bad input produces hard-to-debug ghost
memories.

## Success Criteria

- **SC-001:** `MemoryCandidate`, `AcceptedCandidate`, `RejectedCandidate`,
  `ExtractionStats`, `ExtractionReport` models exist with the fields listed
  above. Validated by `test_candidates.py`.
- **SC-002:** `extract_candidates(text, source_refs)` is a pure function
  (no I/O, no clock, no backend). Verified by a static check (no imports of
  `datetime.now`, `os`, `time`, `Memory`, `MemoryStore` in `candidates.py`).
- **SC-003:** Re-running `extract_candidates` on the same input produces
  byte-identical output. Verified by `test_candidates.py::test_deterministic`.
- **SC-004:** Type-based classifier returns the table-defined `MemoryKind`
  for each `lede_source`. Verified by
  `test_classifier.py::test_type_based_defaults`.
- **SC-005:** Pattern overlay overrides the type-based default when a
  pattern matches with weight > type-based confidence. Verified by
  `test_classifier.py::test_pattern_overlay_wins`.
- **SC-006:** When `overlay_patterns_enabled=False`, no overrides apply.
  Verified by `test_classifier.py::test_overlay_disabled`.
- **SC-007:** Each of the five fixture categories (preferences, decisions,
  commitments, changed_facts, abstention) has ≥3 positive and ≥3 abstention
  samples; each category test passes both positive and abstention cases.
  Verified by `test_patterns.py` × 5.
- **SC-008:** `Stele.extract.from_artifact(...)` auto-derives source_refs as
  `[f"stele://{namespace}/{artifact_id}"]`. Verified by
  `test_extractor.py::test_from_artifact_derives_refs`.
- **SC-009:** `Stele.extract.from_messages(...)` auto-stashes the thread
  when `auto_stash_messages=True` and the resulting ref appears in
  `source_refs`. Verified by
  `test_extractor.py::test_from_messages_auto_stashes`.
- **SC-010:** `Stele.extract.from_text(text, source_refs=[])` raises
  `ValidationError`. Verified by
  `test_extractor.py::test_from_text_requires_refs`.
- **SC-011:** A duplicate candidate (same content hash + same scope as an
  existing memory) appears in `rejected` with `reason="duplicate"` and
  `duplicate_of=<existing_id>`. Verified by
  `test_extractor.py::test_duplicate_appears_in_rejected`.
- **SC-012:** Pure-noise input returns `ExtractionReport(accepted=[])`
  without raising. Verified by
  `test_abstention.py::test_no_facts_returns_empty_accepted`.
- **SC-013:** Extraction never produces a stored memory with empty or
  non-`stele://` source_refs (Phase 1's invariant holds). Verified by an
  integration assertion in the contract test.
- **SC-014:** Memory text inside `ExtractionReport.accepted[*].candidate.text`
  and `Memory.search` hits are PII-scrubbed by default; raw access requires
  `pii.raw_fetch_enabled`. Verified by `test_pii_invariant.py`.
- **SC-015:** Contract test parametrized across `memory + sqlite + postgres`
  produces equal `accepted_count` and structurally equivalent `stored_id`s
  for the same input. Verified by `test_extraction_contract.py`.
- **SC-016:** `Stele.extract.*` raises `CapabilityError` when
  `extraction.enabled=False`. Verified by an orchestrator test.
- **SC-017:** Every accepted memory carries
  `metadata["extraction_config"] == report.config_fingerprint`. Verified by
  an orchestrator test.
- **SC-018:** `lede` raising mid-run causes `SteleError` and discards all
  partial state — no memory rows are stored. Verified by an orchestrator
  test that monkeypatches `lede.extract.key_facts` to raise.

## Drift Checkpoints (hard gates for the plan)

- **⛔ DC-001** — after `extract_candidates` lands, run:
  ```
  grep -rn 'pg_raggraph\|chunkshop\|RecallPolicy\|SourceConnector\|UniversalSearch' src/stele/extraction/
  ```
  Expected: empty. If anything matches, the slice has drifted into Phase 3+.

- **⛔ DC-002** — after the classifier and patterns land, run
  `test_patterns.py` with `overlay_patterns_enabled=False` and confirm
  every preference/decision/commitment/issue/instruction fixture
  falls back to `kind="fact"`. If any retains its agent-loop kind, the
  overlay flag isn't actually gating behavior.

- **⛔ DC-003** — after the orchestrator lands, confirm `Memory.add` is the
  only path from extraction to storage. Run:
  ```
  grep -rn 'MemoryStore\|_store\.' src/stele/extraction/
  ```
  Expected: empty. If matched, extraction is bypassing the `Memory` facade
  and skipping PII scrubbing.

- **⛔ DC-FINAL** — every SC-001..SC-018 has a passing test cited; the
  Out-of-Scope list is verified untouched.

## Out of Scope

- **Policy-driven acceptance** — confidence threshold is a static config
  value. Phase 3 replaces the static filter with `RecallPolicy.accept`.
- **Embedding-based duplicate detection** — duplicate detection uses
  Phase 1's content-hash. Vector similarity is Phase 4.
- **LLM-backed classifier** — no LLM in Phase 2.
- **Graph relationships between candidates** — `lede.extract.correlate_facts`
  exists but Phase 2 does not surface it. Phase 5 handles relational
  structure.
- **Re-extraction / drift detection** — the `config_fingerprint` field
  exists *for* that future feature, but no re-extraction trigger is built.
- **MariaDB / ClickHouse memory backends for extraction** —
  `CapabilityError` stubs (same as Phase 1).
- **CLI / MCP / LangChain integration** — those are M7/M8 in the milestone
  plan, not Phase 2.
- **Auto-extraction on every `stele.store(...)` call** — extraction stays
  explicit. No hidden behavior on store paths.
- **Multi-tenant permission enforcement** — out of scope, same as Phase 1.
- **Public PyPI publish / naming** — orthogonal.

## Testing Requirements Summary

| Suite | Path | Anchors |
|---|---|---|
| Pure-core | `tests/unit/extraction/test_candidates.py` | SC-002, SC-003 |
| Classifier | `tests/unit/extraction/test_classifier.py` | SC-004, SC-005, SC-006 |
| Patterns | `tests/unit/extraction/test_patterns.py` | SC-007 |
| Orchestrator | `tests/unit/extraction/test_extractor.py` | SC-008, SC-009, SC-010, SC-011, SC-016, SC-017, SC-018 |
| Abstention | `tests/unit/extraction/test_abstention.py` | SC-012 |
| PII invariant | `tests/unit/extraction/test_pii_invariant.py` | SC-014 |
| Cross-backend | `tests/contract/test_extraction_contract.py` | SC-013, SC-015 |
| Demo | `scripts/demo-extraction.sh` | Human-readable proof of all five fixture categories |

## Cross-References

- Phase 1 source-of-truth files (consumed, not modified):
  - `src/stele/core/memory.py` — `Memory.add()` is the only path from
    extraction to storage.
  - `src/stele/core/memory_record.py` — `MemoryRecord`, `MemoryScope`,
    `MemoryKind`, `MemoryAddResult` models.
  - `src/stele/pii/regex.py`, `src/stele/pii/scrubber.py` — PII scrub
    layer, double-scrubbed for safety.
  - `src/stele/summary/lede_adapter.py` — pattern reference for how
    `lede` integration looks today.
- Strategy docs:
  - `docs/sovereign-memory-system-plan.md:613-620` — Phase 2 scope
  - `docs/prd-sovereign-stele.md:341-343` — Phase 2 summary
- Phase 1 plan / brief (precedent format and gate discipline):
  - `docs/superpowers/plans/2026-05-12-phase1-memory-supersession.md`
  - `skill-output/mission-brief/Mission-Brief-stele-memory-supersession-slice.md`
