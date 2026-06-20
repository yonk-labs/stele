# Evolving-Fact Consolidation — Design

Status: DRAFT (brainstorming output, pending review)
Date: 2026-06-20
Scope: `stele` session extraction + memory supersession
Related: issues #10 (provisional/consolidated tiers), #11 (memory_tier), #62 (pitfall extraction). Optional richer tier: pg-raggraph `living_knowledge`.

## Problem

`extract.from_session` ingests an agent transcript and LLM-extracts durable kinded
memories. A fact about ONE entity often evolves over the course of a session (and
across days), but each state is committed as an independent, equally-`active`
memory. Recall then returns stale/contradictory states.

Canonical example (capturing a Claude session):

| time | extracted memory |
|---|---|
| early | "Test 1 — not run yet; covers RAG" |
| middle | run Test 1, hit a problem, **expand Test 1 to also cover graph** |
| end | "Test 1 — passed (covers RAG + graph)" |

Later, recall for "Test 1" returns the stale "not run" and "RAG only" states. The
only reconciliation today is exact/near-duplicate rejection (`result.duplicate_of`
in `from_session`); an evolving fact is not a duplicate, so every state stays active.

## Goals / Non-goals

**Goals**
- Recall returns the *current* state of an evolving fact, deterministically, on the
  **LLM-free default path** (an LLM is used only during extraction, which already
  injects one).
- History preserved: `as_of` still returns the state that was current at a past time.
- Works both within one session and across sessions ("yesterday vs today").

**Non-goals**
- Automatic composition of multiple attributes into one prose "current-state object"
  (that is the optional pg-raggraph `living_knowledge` tier, not the default).
- Reconciling `decision` / `pitfall` / `instruction` / `preference` — those are
  additive context, not evolving state. Facts only.
- Editing memory text in place (forbidden; evolution is via supersession only).

## Core idea: subject + aspect slots, superseded as a chain

Reconcile per **(scope, kind=fact, canonical_subject, aspect)** slot, not per whole
entity. A status change supersedes only the old *status*; a coverage change touches
only *coverage*. This is the key that makes the partial-update problem tractable
without fact-composition or the graph:

| slot | chain |
|---|---|
| `fact / test 1 / status` | `not run` → `passed` |
| `fact / test 1 / coverage` | `covers RAG` → `covers RAG + graph` |

Within a slot, states are committed in chronological order as a **supersession
chain**: each state is added via `memory.add(supersedes=[prior_in_slot_id])`.
`as_of` returns the then-current link; default recall (already `active`-filtered)
returns only the latest. **No recall/consumer change is required** — `distill_rules`
and recall already exclude superseded memories.

### Identity: LLM emits a label, code makes the key

The LLM is unreliable at emitting stable slugs (`test1` / `Test 1` / `test-1`).
So the LLM emits a human-visible `subject_label` ("Test 1") and an `aspect`, and
**deterministic code** derives the key:

- `canonical_subject(label)`: NFKC-normalize, casefold, strip punctuation, collapse
  whitespace, split alpha/digit boundaries (`test1` → `test 1`). Pure, unit-tested.
- `canonical_aspect(aspect)`: map to a small seeded vocabulary
  (`status`, `coverage`, `location`, `version`, `owner`, `config`), synonyms folded
  (`result`/`outcome` → `status`), default `other`. Pure, unit-tested.

A slot is formed **only** when `kind == "fact"`, `canonical_subject` is non-empty
(an explicit named subject in the cited evidence), and `aspect` is known. Otherwise
the memory is committed standalone, exactly as today. **Bias to false-negatives:**
when subject or aspect is missing or uncertain, do not consolidate. A stale memory
in recall is annoying; a wrongly-superseded one silently erases truth.

## Components / files touched

- `extraction/session.py`
  - `SessionMemory` gains optional `subject_label: str = ""`, `aspect: str = ""`.
  - `_EXTRACT_PROMPT`: instruct the model to emit `subject_label` + `aspect` for
    `fact` items with an explicit named subject; leave empty otherwise; list the
    seeded aspect vocabulary.
  - `extract_session_memories`: capture the two new keys (still drops unknown keys).
  - Thread a monotonic **source-order index** (turn or window position in ORIGINAL
    transcript order) onto each emitted memory — `windows()` currently sorts
    failure-first, so extraction order is not chronological and cannot be the
    ordering key.
- `extraction/identity.py` (new, pure): `canonical_subject`, `canonical_aspect`.
- `extraction/extractor.py` `from_session`:
  - **Same-session:** buffer slotted facts, group by slot, order by source index,
    commit each slot as a supersession chain. Non-slotted memories commit as today.
  - **Cross-session:** for each slotted fact, look up existing `active` memories in
    the same slot (`scope` + `metadata.canonical_subject` + `metadata.aspect`); if
    the new evidence is strictly newer, add the new fact with `supersedes=[those
    ids]`. Recency source: within a session, the source-order index; across sessions,
    the memory record's own store timestamp (always present), with `session_mtime` as
    a tiebreaker (it is only set for file-path transcripts). Strictly-newer guard
    prevents a later
    *recap of old state* from superseding newer truth ("latest mention ≠ latest
    truth").
  - Store `canonical_subject` + `aspect` in each slotted memory's `metadata` so the
    cross-session lookup can filter.
- `core/memory.py`: if needed, a thin `active-by-slot` query helper, else reuse
  `search`/`list` with a metadata filter.

No change to `core/memory.py` supersession semantics: `add(supersedes=[...])`
already creates a new record superseding the listed ids and bypasses dup-detection
when superseding (memory.py:114).

## Data flow (worked example)

Session ingests the Test-1 transcript. Extraction emits (with source-order index):

```
#1 fact  subject="Test 1" aspect=status   "not run"
#2 fact  subject="Test 1" aspect=coverage "covers RAG"
#5 fact  subject="Test 1" aspect=coverage "covers RAG + graph"
#7 fact  subject="Test 1" aspect=status   "passed"
```

Slots: `(.., test 1, status)` = [#1, #7]; `(.., test 1, coverage)` = [#2, #5].
Commit chains:
- status: add("not run"); add("passed", supersedes=[not-run.id])
- coverage: add("covers RAG"); add("covers RAG + graph", supersedes=[rag.id])

Recall("Test 1") → "passed", "covers RAG + graph" (two active facts, distinct
aspects, both true). `as_of(early)` → "not run", "covers RAG".

## Edge cases / failure modes

- **Partial/compound update** — solved by aspect-scoping (status update does not
  drop coverage).
- **Oscillation** (passed→failed→passed) — chain handles it; current = latest,
  `as_of` shows the flip-flop. Acceptable.
- **Collateral supersession** — aspect prevents superseding a whole entity when only
  one attribute changed.
- **Two genuinely-true facts** — different slot (aspect or scope) → both stay active.
- **Latest-mention ≠ latest-truth** — strictly-newer ordering guard.
- **Subject false-merge** — bias to false-negatives + conservative canonicalization
  (`Test 1` vs `Test 2` → `test 1` vs `test 2`, distinct).
- **PII** — `canonical_subject` is derived from the already-scrubbed `summary`, so no
  raw PII enters metadata.
- **Aspect drift / "zombie facts"** (PRIMARY RISK — flagged unanimously by gemma +
  qwen): if the LLM names the same attribute differently across time (`status` one
  day, `reliability` the next), the states land in different slots and never collapse,
  leaving multiple active facts for one real state. The false-negative bias makes this
  the *safe* failure (no wrong erasure) but it accrues memory bloat over long runs.
  Mitigation: an extensible aspect **synonym map** applied in `canonical_aspect`
  (reliability/health → status, scope → coverage, ...); unknown aspects kept DISTINCT
  (never silently folded into a wrong bucket); and a consolidation-time **detector
  that LOGS** when one `canonical_subject` carries multiple active aspect-slots that
  may overlap (for review — never auto-merge in v1).
- **Cross-aspect coherence** (qwen): an `owner`/`version` change can logically
  invalidate a `coverage` fact, but aspects are treated as orthogonal. OUT OF SCOPE
  for v1 (named limitation, not silently "solved"); a future rule or the graph tier
  can flag cross-slot contradictions.

## Testing plan (TDD)

- **Unit:** `canonical_subject` / `canonical_aspect` (incl. `test1`/`Test 1`/`test-1`
  collapse, distinct subjects stay distinct, aspect synonym folding, unknown→other).
- **Unit/contract:** slotting + chain construction; non-slotted memories unaffected;
  kind-scoping (decision/pitfall never consolidated).
- **Integration:** the Test-1 transcript fixture → assert 2 slots, recall returns
  latest, `as_of(early)` returns historical states.
- **Cross-session:** session A then session B in the same slot → B supersedes A;
  older recap does NOT supersede newer.
- **Real-transcript validation** (per project practice): run over LARGE real agent
  transcripts, capture false merges / false negatives explicitly, do not rely on a
  curated easy case.
- **Extraction-prompt A/B:** paired A/B on real transcripts + A/A noise-floor control
  (the #59 recipe), judged per-kind, to confirm the prompt change adds subject/aspect
  signal without regressing existing kinds.

## Cross-model validation

Direction cross-checked across three models. A gemma+qwen debate converged on
consolidation + supersede but split on identity and partial-update; a Codex second
opinion resolved both (code-canonicalized labels; aspect-scoping). Re-validating the
refined design, BOTH gemma and qwen returned AGREE — qwen explicitly reversing its
"graph is the only correct answer" stance for the default path. All three flag the
SAME primary risk: aspect-vocabulary drift (see Edge cases).

## Open questions

1. Final seeded `aspect` vocabulary + synonym map (see the aspect-drift risk in Edge
   cases). Start small, expand on evidence.
2. Reliable source ordering given failure-first windows: window-position index vs a
   model-emitted turn index. Prefer code-derived window position (the prior
   turn-indexing experiment underperformed, but for windowing quality, a different
   use than ordering — do not assume it carries over).
3. Cross-session lookup cost: may want a metadata index on `canonical_subject`.
4. Confidence interplay: should a lower-confidence later state supersede a
   higher-confidence earlier one? Proposed v1: yes if strictly newer (recency wins);
   revisit if it causes thrash.

## Relation to the graph

The optional pg-raggraph `living_knowledge` model (logical_id + current_only) is the
richer tier: automatic composition into a single current-state object. This design is
the **default-path, LLM-free** equivalent. Both can coexist; the graph is never
required for default correctness.
