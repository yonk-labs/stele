---
title: Phase 6+7 Recon & Decision Sheet (GROUND TRUTH)
created: 2026-05-17
status: authoritative — resolves the runtime-agent-memory spec's Open Questions
        against the spec + the real shipped Stele code (branch
        phase6-7-runtime-working-memory @ 01cb971). Inject into every P6/P7 task.
design-source: docs/specs/runtime-agent-memory-architecture-spec.md (T-RAM-001..011)
roadmap: docs/superpowers/2026-05-17-order-of-operations.md (P6=T-RAM-001..004, P7=T-RAM-005..008+first adapter)
---

# Phase 6+7 — Recon & Decisions

## §0 — Scope

- **Phase 6 = T-RAM-001..004**: WorkGraph models+validators, `WorkGraphStore`
  Protocol + in-memory backend, SQLite store, Mermaid/Markdown/JSON renderers.
  Deterministic, source-backed, **no pg-raggraph**, no LLM.
- **Phase 7 = T-RAM-005..008 + one adapter that proves the loop**:
  artifact→WorkGraph capture helper, context packer, adapter health contract,
  adapter scheduling, and an in-process demo adapter.
- Out of scope: T-RAM-009 (evidence-backed views — P8), T-RAM-010 (LLM
  proposal pipeline — post-deterministic), T-RAM-011 (runs continuously; a
  P7 runtime benchmark is delivered but the public-claim gate stays open).

## §1 — Open Questions RESOLVED (spec + code grounded)

**Q1: WorkGraph records = memory, artifact, or a third first-class type?**
→ **Third first-class record type.** The spec proposes its own package
(`src/stele/workgraph/`), its own models, its own `WorkGraphStore` Protocol,
its own backends, and the invariant *derived claim → source-backed
node/event → memory atom → `stele://` artifact → exact content*. A WorkGraph
node is therefore NOT a memory and NOT an artifact; it **references** them
(`source_refs`/`artifact_refs`/`memory_refs`) and is never authoritative over
memory truth. This mirrors how Phase 5's `Revisor` is a projection, not truth.

**Q2: `as_of` from day one?** → **Protocol defines it; memory backend raises
`CapabilityError`; SQLite implements it.** Matches Spec-2 acceptance ("`as_of`
support is either implemented or explicitly raises `CapabilityError`") and the
Phase-1 precedent (capability honesty over silent no-op).

**Q3: WorkGraph query = pg-raggraph / relational / both?** →
**Deterministic relational/in-memory query only.** `query_graph` filters by
namespace/session/status + substring/keyword over `label`/`summary`. NO
pg-raggraph (roadmap: "no pg-raggraph needed"; keeps P6 low-external-dep).
Living-knowledge graph (Phase 5) and WorkGraph are distinct subsystems.

**Q4: First adapter to prove the loop (P7)?** → **Stele's own in-process
demo runner** (`SteleAgentSession`). LangChain/MCP/OpenAI-Agents need network
+ SDKs and are Phase 8 ("framework adapters") per the Prior-Art matrix; the
demo runner proves `observe → store → workgraph → extract → recall/pack →
resume` deterministically, in CI, with no live LLM (spec constraint: "Health
state is testable without a live LLM provider").

**Q5: Generated profile views as recall inputs?** → Out of P6/P7 (T-RAM-009,
Phase 8). Not built.

## §2 — Real Stele integration surfaces (code-verified @ 01cb971)

| Need | Reality |
|---|---|
| Validate `stele://` refs | `stele.core.reference.parse_reference(value) -> Reference`; raises `ReferenceError`. Use it in validators. |
| PII scrub summaries | `stele.pii.scrubber.build_pii_scrubber(PIIConfig)` → `.scrub(text) -> ScrubResult`; `ScrubResult.text` (scrubbed), `.summary: PIIScrubSummary`, `.detections`. |
| Config | `StashConfig` (pydantic). Add a `WorkGraphConfig` + `Stele.workgraph` lazy property (mirror `Stele.memory`/`Stele.revisor`). |
| Store pattern | Mirror `src/stele/storage/memory_store/{base.py Protocol, memory.py, sqlite.py}` + `tests/contract/`. |
| Models pattern | pydantic v2 `BaseModel`, `ConfigDict`, `field_validator`; mirror `MemoryRecord`. Exceptions: `ValidationError`, `CapabilityError`, `ArtifactNotFound` in `stele.core.exceptions`. |
| Recall result for packer | `RecallResult` (`stele.recall.models`): `.context`, `.citations[Citation(kind,id,reference,score,snippet)]`, `.source_refs`, `.strategy_used`. |
| Artifact store for capture | `Stele.store(content, *, namespace, session_id, metadata) -> StoredResult` (`.reference`, `.artifact_id`, `.summary`, `.estimated_token_savings`). |
| Locked discipline | Additive only. Do NOT reshape `search`/`query`/`recall`/`memory`/`revisor` or Phase-1..5 signatures. WorkGraph is a NEW subsystem; new `Stele.workgraph` property; `recall`/`memory` untouched. |

## §3 — Cross-cutting invariants (inject into every implementer)

1. **Source-backed or it does not persist.** Every graph (once persisted),
   node, and causal/derivation edge must carry ≥1 valid ref (parses via
   `parse_reference`) OR an explicit `derived_from`. Validator enforced.
2. **No raw content in the graph.** `label`/`summary`/`metadata` values over
   a small threshold (default 512 chars) fail validation. Big payloads must be
   `Stele.store()`d as artifacts first; the node carries the ref.
3. **PII on summaries before persistence.** Run the scrubber on
   human-readable fields at the store boundary (fail-loud if unscrubbed PII
   reaches it, like the Phase-4 chunk-store check).
4. **Status transitions are validated** (Spec-1 rules). Terminal states only
   move via explicit supersession.
5. **Renderers/views are never authoritative.** Mermaid/Markdown/JSON are
   projections; the store is truth.
6. **Deterministic. No LLM. No pg-raggraph. No network.** P6/P7 are pure.
7. **Concurrency**: any scheduling clock is **injectable** (fake clock in
   tests); idle/session flush scoped to one session; no real sleeps in tests.
8. **Capability honesty**: missing optional pieces report explicit state, never
   silent degraded (Spec-5).
9. TDD per task; one conventional commit per task `feat(scope): … (T-RAM-0xx)`;
   trio green before each commit; no `--no-verify`.

## §4 — SC / exit gates

- **SC-P6**: T-RAM-001..004 acceptance criteria each cited to a passing test;
  contract tests green on memory+sqlite; renderers round-trip; arch test
  (workgraph has no pg_raggraph/LLM import; renderers not authoritative).
- **SC-P7**: T-RAM-005..008 acceptance each cited to a passing test; the demo
  adapter proves the full loop end-to-end in one test; adapter health +
  scheduling tested with fake stores/clock.
- **P7 exit demo (the bar)**: a runnable
  `scripts/demo-runtime-loop.sh` + `tests/integration/test_runtime_loop.py`
  proving `observe tool result → store artifact → update WorkGraph → extract
  memory → recall/pack context → resume`, every packed claim carrying refs,
  PII fixture not leaking into packed context.
- **DC-P6/7-FINAL**: full trio green; `grep -rn 'pg_raggraph\|openai\|anthropic'
  src/stele/workgraph/` empty; SC→test map written. Then push branch (NO merge).
