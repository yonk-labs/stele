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
| Reduce one event (stream/parse filter) | `extraction.session.reduce_event(event, cfg)` | built |
| Reduction knobs | `ExtractionConfig.reduce_*` (`result_chars=120`, ...) | built |
| Ingest a session (reduce + store) | `extraction.ingest.ingest_session` / `stele-ingest` CLI | built |
| Live conversation feed hook | `templates/hooks/claude-code-ingest.sh.j2` (SessionEnd) | built |
| Chunk index for retrieval | `IndexingConfig(mode=sync/async)` + chunk store | shipped |
| Raw retention GC | `stele.cleanup_expired()` | shipped |
| Distill one transcript | `stele.extract.from_session(transcript=, scope=, llm=)` | built |
| Per-mode distilled views | `stele.distill.{facts,precedents,state,skills,best_practices,rules}` | built |
| Batch over many sessions | `benchmarks/external/memory_modes/distill_fleet.py` | built |
| Distilled memory store | `stele.memory.add/list` (+ supersession, as_of) | shipped |

## How to make it work (concrete)

### 1. Continuous ingest (the conversation feed, Phase A)
The session is reduced at the INGESTION boundary, so only the keep120 form is
stored (never the raw bytes). A Claude Code SessionEnd hook calls `stele-ingest`
with the transcript path; every event flows through `reduce_event` and the
reduced session is stored as ONE artifact with a 30-day TTL (PII-scrubbed by the
store boundary when `pii.enabled`):
```bash
# what the hook runs (transcript_path + session_id come from the hook's stdin JSON):
stele-ingest "$transcript_path" --session-id "$session_id" --namespace sessions
# -> {"ref": "stele://sessions/...", "turns": 5169, "chars": 1337962}
```
Hook template: `packaging/templates/hooks/claude-code-ingest.sh.j2` (SessionEnd).
Programmatic equivalent (per-event live stream, or a path):
```python
from stele.extraction.ingest import ingest_session, reduce_stream
ingest_session(stele, transcript=transcript_path, namespace="sessions")  # whole session
turns = reduce_stream(events)   # or accumulate per event off a live feed
```
On a real 24MB session this stores ~1.3MB (5.6% of raw): signatures, snapshots,
metadata, and oversized tool bodies are gone, successful results kept to their
headline (keep120), failures kept longer. For oversized tool output mid-session
the exact-bytes path is still `stash_tool_result(...)` (a different contract).

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

### Stream reduction filter: `reduce_event` / keep120 (built)
The raw-to-stored reduction is a single per-event filter, `reduce_event(event,
cfg)`, so it runs identically on the **live ingest stream** (event at a time, as
Claude emits it) and on a stored **.jsonl backfill** (`parse_claude_jsonl` is just
`reduce_event` per line). Per event it drops what carries no durable memory and
the model never needs: non-conversation lines (file-history-snapshot, attachment,
metadata, system), the thinking **signature** (a base64 attestation, ~20% of raw
bytes; only the thinking *text* is kept), and oversized tool bodies. It preserves
role + `is_error` so distill-time windowing can still surface failures first.

The reduction level is config-driven (`ExtractionConfig.reduce_*`), defaulting to
the measured **keep120** sweet spot:

| knob | default | meaning |
|---|---|---|
| `reduce_result_chars` | 120 | successful tool-result kept, truncated to this (the headline fact: versions, test outcomes, constraints) |
| `reduce_error_chars` | 220 | failed result kept longer (it is the rule signal) |
| `reduce_tool_chars` | 200 | tool-call input truncation |
| `reduce_drop_success_results` | False | True = the older "minify" (drop successful results entirely) |

**Why keep120, not drop (measured, production budget, 8 sessions):** dropping
successful results (`reduce_drop_success_results=True`, the old minify) loses
~30% of memories, and it hits the rule-class kinds hardest (pitfall 19->12,
workaround 17->11, instruction 15->10) because the fix/outcome context lives in
the result. keep120 matches keeping the full result (90 vs 85 memories, within
noise) while staying tiny. Raising the cap above ~120 buys no recall (the
durable fact is in the first ~120 chars; the tail is ephemeral file/output bulk).
So keep is binary against drop, and 120 is the floor that keeps recall.

Storage is not a reason to drop: the full parsed corpus is ~70MB (5.7% of the
1.22GB raw; the parse already removes 94%), and keep120 is smaller still. Drop
would save ~47MB corpus-wide for a 30% memory loss. `minify_transcript` / the
`minify` CLI still expose the aggressive drop (`ReduceConfig(drop_success_results
=True)`) for archive-only sessions you will never distill; `--caveman` adds
`lede.clean_text` on prose (lossy, embedding-path only).

#### Impact by memory type (keep120 vs drop)
The reduction does not hit the six distilled views evenly. What it costs depends
on where each type's evidence lives (measured, production budget):

| view (kinds) | where the evidence lives | keep120 vs full | drop (minify) vs full |
|---|---|---|---|
| **facts** (fact) | successful tool results (versions, test outcomes, constraints) | -14% | **-32%** |
| **rules** (pitfall/workaround/instruction) | errors + the fix context in the following result | ~0% | **-35%** |
| **skills** (instruction) | results + prose | ~0% | -33% |
| **state/resume** (recent facts + file states) | successful Read/Bash/Write result bodies | small | **largest** (file states are dropped) |
| **precedents** (decision) | assistant prose / user turns | ~0% (noisy) | small |
| **best_practices** (preference) | stated prose / user turns | ~0% (noisy) | small |

So the types whose signal lives in successful tool output (facts, rules, skills,
and especially resume/state) are exactly the ones dropping results guts; keep120
protects all of them. precedents and best_practices are prose-borne, so they are
nearly immune to the reduction either way.

## Throughput (measured)

The fleet run (both Sparks, 12 slots, 24 sessions) did 93 memories in 391s
(~16s/session effective, ~2.7x over serial). To see what gates that, the
per-operation costs were measured directly (LLM-free where possible, so they
reproduce):

| Operation | Cost | Where it runs |
|---|---|---|
| Parse a 24MB / 5,169-turn transcript | **~0.17s** | laptop (negligible) |
| Parse the 8 biggest sessions (~95MB) serial | **0.53s** | laptop |
| Minify (structural reduction) | ~0.1s, **97-99%** smaller | laptop |
| `store()` with `indexing.mode=sync` (embeds 204KB) | **~22s** | **laptop CPU** |
| `store()` with `indexing.mode=skip` (no embed) | **0.08s** | laptop |
| One distill window -> Spark LLM | **~5-7s** | Spark |

The dominant per-session cost is **synchronous chunk-embedding on the laptop
CPU** (`bge-base-int8`), not parsing and not the Spark LLM. Parsing is ~0.1s;
it is not the bottleneck (an earlier note that said so was wrong). Threads do
not parallelize the parse (GIL: measured 1.04x); processes do (2.29x), but the
parse is sub-second so it does not matter.

Levers, in order of impact:
- **Skip raw-session indexing when you only need evidence.** Distillation does
  not require vector search over raw transcripts. Store raw with
  `indexing.mode=skip` (0.08s) and embed only the small distilled memories;
  the 22s/session embedding disappears and the pipeline becomes Spark-bound.
- **Minify before you embed**, when you *do* want raw-session retrieval: the
  204KB minified form is ~120x fewer chunks than the 24MB raw, so embedding
  goes from minutes to ~22s. Offload that embedding to a GPU (async indexing)
  rather than laptop CPU for a backfill.
- **Incremental runs** touch only new sessions (~28/day, ~388/week of 5,711),
  so steady-state is minutes regardless.

### Flow: session -> minify -> store -> distill (verified end-to-end)
`minify_transcript(session)` -> `stele.store(minified)` -> `extract.from_session(
transcript=session, source_ref=<stored ref>)` composes on existing primitives;
the distilled memories cite the stored minified artifact as evidence. Note that
`from_session` already compacts internally (windows drop successful tool
results), so distilling from the minified form does not change LLM input or
output quality. The minify-first win is **storage and embedding cost** (98-99%
smaller evidence artifacts), not distillation quality or parse speed.

## Config knobs
- `ttl_seconds` on stash (raw retention; 30d).
- `ENDPOINTS` + caps in `distill_fleet.py` (pool + concurrency).
- `--windows` (1 for small sessions; more for large).
- `DistillConfig.synthesis` ("auto" uses the injected LLM; "deterministic" skips it).
- Injected `llm` (refine quality) and `embedder` (semantic dedup) on `Stele.distill`.
