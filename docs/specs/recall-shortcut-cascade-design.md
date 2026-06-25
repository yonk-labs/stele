# recall.shortcut — 3-tier fall-through + semantic matcher (design)

Status: design, pending implementation. Date: 2026-06-22.
Reviewed by: abe panel (gemma, qwen, codex); findings folded in (see §7).

## 1. Motivation

Real coding-agent sessions re-do work they already did: re-deriving the same
multi-step outcome, re-running the same procedure, re-reading the same file.
Measured on real transcripts: 30-80% of file reads are repeats (cross-turn
42-58%, cross-session ~22%). `Stele.memory` already stores the durable pieces
(outcomes, procedures, observations) and can match them semantically. What is
missing is the **routing**: given an agent intent plus the current env, decide
whether a remembered item can short-circuit the work, and which one.

This is a *router*, not new storage. It composes existing facades.

## 2. Public surface

```python
Stele.recall.shortcut(
    intent: str,            # the agent's goal in natural language ("run the tests")
    env: dict[str, str],    # current observable env (for the outcome canary gate)
    *,
    scope: MemoryScope,     # MUST carry project identity; the hard isolation boundary
    source: str | None = None,  # current source text, for the context freshness hash
) -> ShortcutResult
```

```python
@dataclass(frozen=True)
class ShortcutResult:
    tier: str               # "outcome" | "context" | "procedure" | "work"
    hit: bool               # False iff tier == "work"
    payload: str | None     # the remembered text to reuse, or None on a miss
    record: MemoryRecord | None
    reason: str             # human-readable verdict
    diagnostics: dict[str, object]  # backend, kinds searched, candidate ids+scores,
                                    # the floor used, freshness outcome, why tiers were skipped
```

`tier == "work"` means nothing was reusable: the caller does the work fresh and
(optionally, its choice) records the result for next time. stele never executes
anything; it returns advice + evidence.

## 3. The cascade (order fixed by review: most-reliable-first)

```
intent + env + scope
  │   [matcher: semantic intent routing, §4]
  ├─ Phase 1  OUTCOME   route by intent → candidates → canary(env) + TTL gate   → hit?  [reuse.py built]
  ├─ Phase 2  CONTEXT   route by intent → candidates → freshness gate (hash|TTL) → hit?  [new gate]
  ├─ Phase 3  PROCEDURE route by intent → candidates → ADVISORY (env metadata)   → hit?  [new writer]
  └─ Phase 4  WORK      no reuse; caller does it fresh
```

Ordering principle (the review's key correction): tiers are ordered by **how
reliable a hit is**, not how abstract it is. Outcome is canary+TTL-gated (most
reliable). Context is freshness-gated. Procedure is *un-hard-gated* and therefore
**last and advisory** — a remembered procedure is returned as "suggested steps to
validate," never as authority, so it can never silently short-circuit a gated
context hit.

First *tier* with a valid hit wins. First raw *candidate* never wins: each tier
overfetches top-N, applies its gate, and returns the best candidate that passes
(§4). On a tier miss, fall through.

## 4. The matcher (semantic routing)

A single internal helper routes an intent to remembered items of a given kind:

```python
_route(intent, scope, kind, *, top_n=5) -> list[ScoredHit]   # scored, kind-filtered, scope-hard-filtered
```

- Backed by `Stele.memory.search_with_score`, which returns max-normalized
  `[0,1]` scores on every backend (`storage/memory_store/base.py:119`). Hybrid
  vector+lexical (RRF) when `memory_vector=True` on Postgres
  (`config.py:69`); lexical FTS otherwise. **Degrades, never hard-fails.**
  "Semantic routing is on" ⇔ `memory_vector=True`.
- **Requires a new `kind_filter` on `search_with_score`** (and the store
  contract). codex review: `search_with_score` currently has no kind filter, so
  routing to `kind="procedure"` is impossible without it. Filter at the store
  layer (precision + performance), not by over-fetch-and-discard.
- **`scope` is a HARD filter**, never a semantic hint. Project identity in scope
  is the cross-project contamination boundary.
- **Per-kind acceptance floor**, not one global number. Start from the existing
  `confidence_floor` (0.4, `config.py:169`) as the context/observation floor;
  use a higher floor for procedure (advisory but should still be a strong match)
  and rely on the canary (not score) for outcome. Per-backend calibration and a
  runner-up margin check are deferred hardening (§8).
- **Top-N then gate:** each tier asks `_route` for the top N, applies its gate to
  each in score order, and returns the first that passes; else the tier misses.
  This prevents a high-score-but-stale candidate from masking a fresh one.

## 5. Per-tier behavior

**Phase 1 — Outcome.** Route `kind="outcome"` by intent (this fixes the leakage
codex found: `_latest_outcome` at `memory.py:217` returns the newest outcome in
scope ignoring intent, so a broad scope could reuse an unrelated task's result).
For each candidate in score order, apply the existing canary+TTL gate via the
reuse machinery (`reuse.py` `is_valid` + `is_expired`, already built and tested).
First valid → hit. The matcher narrows *which* outcome; the canary decides *if*
it is still valid.

**Phase 2 — Context.** Route `kind="observation"` by intent. New pure gate in
`core/reuse.py`:

```python
def is_stale(stored_hash, current_source, created_at, ttl_seconds, now) -> bool:
    # stale iff (current_source given AND sha256(current_source) != stored_hash)
    #        OR is_expired(created_at, ttl_seconds, now)
```

Source-hash is the observable gate; TTL is the backstop for drift you cannot
observe (mirrors the outcome canary+TTL pairing). When `source is None`, freshness
rests on TTL alone and the result says so: `reason="fresh_unverified_source"`, so
callers do not overtrust context never checked against current bytes. New writer
`memory.record_context(text, *, source_ref, source, intent, scope, ttl_seconds, ...)`
stores `sha256(source)` + `ttl_seconds` + the intent in metadata.

**Phase 3 — Procedure.** Route `kind="procedure"` by intent. **Advisory, no hard
gate** (the agent re-runs the steps). But not gate-free either: `record_procedure`
stores applicability metadata (the `env` at recording, observed tool/command
names) so the result can flag mismatch in `diagnostics`/`reason`
(e.g. `"procedure_env_drift"`). The payload is returned as suggested steps; the
agent decides. New writer `memory.record_procedure(text, *, intent, source_refs,
scope, env=None, ...)` over `add(kind="procedure")`.

## 6. New/changed code (all additive)

| Area | Change |
|---|---|
| `storage/memory_store/base.py` + sqlite/postgres/memory | add `kind_filter` to `search_with_score`; contract test param |
| `core/reuse.py` | add `is_stale(...)` (pure, beside `is_expired`); `META_SOURCE_HASH` |
| `core/memory.py` | `record_procedure(...)`, `record_context(...)` writers |
| `recall/shortcut.py` (new) | `_route`, the cascade, `ShortcutResult` |
| `recall/facade.py` | expose `Recall.shortcut(...)` |
| `core/config.py` | per-kind floors (small map), default context TTL |

## 7. Review findings folded in (abe: gemma, qwen, codex)

| # | Finding | Resolution |
|---|---|---|
| 1 | Phase 1 ignored `intent` → cross-task outcome leakage (`memory.py:217`) | route outcome by intent before the canary gate (§5) |
| 2 | `_route` impossible: `search_with_score` has no `kind_filter` | add `kind_filter` to the store contract (§4, §6) |
| 3 | one global `confidence_floor` not calibrated across backends | per-kind floors now; per-backend calibration deferred (§8) |
| 4 | first raw candidate could mask a fresh one | top-N then gate (§4) |
| 5 | procedure is the dangerous ungated tier | ordered last + advisory + env metadata (§3, §5) |
| 6 | context with no source overtrusted | `reason="fresh_unverified_source"` (§5) |
| 7 | no observability → untrustable | `ShortcutResult.diagnostics` (§2) |

## 8. Scope OUT (YAGNI)

Procedure *execution* (stele returns steps, the agent runs them); automatic
recording in Phase 4 (the caller decides what to record); flipping the
`memory_vector` default (semantic routing stays opt-in, documented as "enable
`memory_vector` on Postgres"); per-backend score calibration and runner-up-margin
thresholds (revisit if mis-routing shows up in measurement); multi-outcome
typed-column routing (followups Plan 1 — metadata routing is enough here).

## 9. Testing (TDD)

- Pure: `is_stale` unit tests (hash match / mismatch / no-source / TTL boundary),
  mirroring the `is_expired` tests.
- Store: `search_with_score(kind_filter=...)` contract test across backends.
- Orchestration: `shortcut` tier-order tests on a real sqlite `Stele` (lexical
  matcher) — outcome short-circuits; context fresh-hit vs stale-fall-through;
  procedure advisory hit; all-miss → `tier="work"`; intent mis-route stays under
  the floor → fall through.
- Writers: `record_procedure` / `record_context` contract tests across backends.

## 10. Build slices (each leaves the tree green)

1. `is_stale` + `META_SOURCE_HASH` in `core/reuse.py` (pure, TDD).
2. `kind_filter` on `search_with_score` across backends + contract test.
3. `record_context` + `record_procedure` writers.
4. `recall/shortcut.py`: `_route` + `ShortcutResult` + the 3-tier cascade.
5. `Recall.shortcut` facade exposure + per-kind floor config.
