# Memory Distillation: Flow, Usage, and Implementation

How raw agent sessions become long-lived distilled memory, and how to run it on
a laptop-dispatcher + local-Spark topology.

## The two-phase architecture

Distillation is deliberately split from ingestion. They run on different clocks.

```
  PHASE A (continuous, inside the agent)        PHASE B (periodic batch, scheduled)
  ┌───────────────────────────────────┐        ┌────────────────────────────────────┐
  │ session ends / hits a stage        │        │ cron: every few days (< raw TTL)   │
  │   stele.store(transcript,          │        │   for each NEW session since the   │
  │     ttl_seconds=30d)   ← raw bytes │  ───▶  │   last run:                        │
  │   + chunk index (vector/hybrid)    │        │     extract.from_session(...)      │
  │ raw kept ~30 days, then GC'd       │        │       → kinded memories (6 modes)  │
  └───────────────────────────────────┘        │   distilled memory: NO ttl (long)  │
                                                └────────────────────────────────────┘
       raw artifacts: short-lived (30d)               distilled memory: long-lived
```

- **Phase A is cheap and synchronous** (inside Claude): store the exact bytes
  behind a `stele://` ref with a 30-day TTL, and chunk-index them for retrieval.
  No LLM, no distillation on the hot path.
- **Phase B is the expensive part, off the hot path**: a scheduled batch reads
  accumulated raw sessions and distills the six modes into a long-lived memory
  store. This is where the LLMs (local Sparks / OpenAI) are used.
- **Retention is two-tier**: raw artifacts expire at 30 days (`ttl_seconds` +
  `cleanup_expired`); distilled memories have no TTL and persist, evolving by
  supersession. The only hard rule: **the Phase-B cadence must be shorter than
  the raw TTL**, so durable knowledge is extracted before the raw is GC'd.

## Components (what each piece is)

| Role | API / tool | Status |
|---|---|---|
| Ingest raw bytes + ref | `stele.store(payload, ttl_seconds=...)` / `stash_tool_result` | shipped |
| Chunk index for retrieval | `IndexingConfig(mode=sync/async)` + chunk store | shipped |
| Raw retention GC | `stele.cleanup_expired()` | shipped |
| Distill one transcript | `stele.extract.from_session(transcript=, scope=, llm=)` | built |
| Per-mode distilled views | `stele.distill.{facts,precedents,state,skills,best_practices,rules}` | built |
| Batch over many sessions | `benchmarks/external/memory_modes/distill_fleet.py` | built |
| Distilled memory store | `stele.memory.add/list` (+ supersession, as_of) | shipped |

## How to make it work (concrete)

### 1. Continuous ingest (inside the agent, Phase A)
Stash the raw transcript with a 30-day TTL and let it be chunk-indexed:
```python
ref = stele.store(transcript_text, namespace=project, ttl_seconds=30 * 86_400)
# (or, for oversized tool output mid-session:)
#   stash_tool_result(raw_output, stash=stele, namespace=project, tool_name=...)
```
The bytes are exact and retrievable now; they self-expire in 30 days.

### 2. Periodic batch distill (Phase B, scheduled)
Run the fleet across the local Sparks. It streams sessions, fans bounded
concurrency across both endpoints, commits per session, and is resumable:
```bash
STELE_PG_DSN=postgresql://.../stele \
  .venv/bin/python -m benchmarks.external.memory_modes.distill_fleet \
    --limit 500 --windows 1 --namespace project-memory
# resume / next bucket:  --start 500 --no-purge
```
Endpoints + per-endpoint concurrency caps are declared in `ENDPOINTS` (measured
sweet spots: Qwen ~4, Gemma ~8). The laptop only holds the in-flight network
waits; the Sparks do the work.

### 3. Read the distilled views (anytime, by anything)
```python
import asyncio
from stele.core.memory_record import MemoryScope
scope = MemoryScope(namespace="project-memory")
rules = asyncio.run(stele.distill.rules(scope))   # don't/do pairs, in-family
for r in rules.items:
    print(r.dont, "=>", r.do_instead, r.source_refs)
```
Externally via MCP/CLI: `stele distill rules --namespace project-memory`
(`stele_distill` tool over the wire). Inject an embedder for semantic dedup and
an LLM for the refine/synthesis (both optional; deterministic without them).

### 4. Retention GC (scheduled, Phase A cleanup)
```bash
# nightly: drop expired raw artifacts; distilled memory is untouched (no TTL)
python -c "from stele import Stele; Stele.from_config(cfg).cleanup_expired()"
```

## How to implement / wire it

1. **Agent integration (Phase A):** on session end / stage boundaries, call
   `stele.store(..., ttl_seconds=30d)` (already the stash path). No new code if
   the agent already stashes; just set the TTL.
2. **Scheduler (Phase B):** a cron / systemd timer on the laptop runs
   `distill_fleet` every N days where **N < 30**. First run is a one-time
   backfill of existing raw; subsequent runs process only what's new (see gap 1).
3. **Endpoint pool:** edit `ENDPOINTS` in `distill_fleet.py` to your Spark URLs +
   caps. Add OpenAI gpt-5-mini as a pool member only for the refine step or
   high-value sessions (it is ~2× slower, costs tokens, and sends transcripts
   off-box, whereas the Sparks keep them local).
4. **Retention:** stash with `ttl_seconds`, run `cleanup_expired` nightly.
   Distilled memory needs no TTL.

### Incremental selection (built)
Each periodic run distills only sessions modified since the last run:
```bash
# watermark file advances each run; only new sessions are processed next time
.venv/bin/python -m benchmarks.external.memory_modes.distill_fleet \
  --namespace project-memory --windows 1 --watermark /var/lib/stele/distill.wm
# or a rolling window: --since-days 7
```
Measured: of 5,711 sessions, ~388 were modified in the last 7 days, ~28 in the
last day, so a daily run is minutes.

### Temporal supersession (built)
Run `consolidate` after a distill batch to keep the long-lived store current:
it clusters active memories by embedding similarity and **retracts all but the
newest** in each cluster (newest by `session_mtime`, stamped by `from_session`),
so "version 0.5" gives way to "version 0.6" instead of both lingering.
```python
stele._distill_embedder = build_memory_embedder(cfg.indexing)  # inject once
report = stele.distill.consolidate(scope)   # {"clusters": n, "retracted": m}
```
Requires an injected embedder; it is a maintenance pass, not on the hot path.

### Minify (built)
Reduce a transcript to signal before storing/embedding (`minify_transcript` /
the `minify` CLI). Structural reduction (drop successful tool-result bodies,
compact + collapse tool calls, keep failures) does ~96% on real sessions;
`--caveman` adds `lede.clean_text` on prose for ~2% more (lossy; embedding path
only). After-the-fact minify of a stored artifact re-chunks/re-embeds it.

## Throughput (measured)

Per session (reduced transcript, 1 window): local Qwen int4 ~44s, Gemma-4-26B
~49s, gpt-5-mini ~97s. The Sparks parallelize well under vLLM (probe: Qwen
near-linear to ~4 concurrent, Gemma to ~8+).

**Measured fleet run** (both Sparks, 12 slots, 24 sessions): 93 memories in 391s
= **~16s/session effective, ~2.7x over serial**. Not the ~12x the slots imply,
because this run hit the biggest sessions first and **parsing 20MB+ transcripts
is laptop-bound** (the dispatcher's real ceiling, not the Sparks). Naive
full-backfill at that rate ~26h.

Two things make that a non-issue:
- **Incremental runs** touch only new sessions (median ~98KB; ~28/day, ~388/week),
  so steady-state is minutes.
- **Minify-at-ingest** removes the backfill ceiling: store the reduced transcript
  (~96% smaller) in Phase A so Phase B never re-parses the 20MB raw. This is the
  fix for the laptop-parse bottleneck the fleet run exposed.

## Config knobs
- `ttl_seconds` on stash (raw retention; 30d).
- `ENDPOINTS` + caps in `distill_fleet.py` (pool + concurrency).
- `--windows` (1 for small sessions; more for large).
- `DistillConfig.synthesis` ("auto" uses the injected LLM; "deterministic" skips it).
- Injected `llm` (refine quality) and `embedder` (semantic dedup) on `Stele.distill`.
