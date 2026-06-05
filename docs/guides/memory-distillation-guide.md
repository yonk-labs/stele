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
| Reduce one event (stream/parse filter) | `extraction.session.reduce_event(event, cfg)` | shipped 0.6.0 |
| Reduction knobs | `ExtractionConfig.reduce_*` (`result_chars=120`, ...) | shipped 0.6.0 |
| Ingest a session (reduce + store) | `extraction.ingest.ingest_session` / `stele-ingest` CLI | shipped 0.6.0 |
| Live conversation feed hook | `templates/hooks/claude-code-ingest.sh.j2` (SessionEnd) | `stele install --platform claude-code` drops the script + prints the `settings.json` snippet to register it |
| Chunk index for retrieval | `IndexingConfig(mode=sync/async)` + chunk store | shipped |
| Raw retention GC | `stele.cleanup_expired()` | shipped |
| Distill one transcript | `stele.extract.from_session(transcript=, scope=, llm=)` | shipped 0.6.0 |
| Per-mode distilled views | `stele.distill.{facts,precedents,state,skills,best_practices,rules}` | shipped 0.5.x |
| Batch over many sessions | `benchmarks/external/memory_modes/distill_fleet.py` | benchmark harness (not in the package) |
| Distilled memory store | `stele.memory.add/list` (+ supersession, as_of) | shipped |

## Reading an agent stream, step by step

The conversation feed turns a live Claude session into one reduced, stored
artifact. The filter (`reduce_event`) is per-event, so it works the same whether
you process events as they arrive or read the finished transcript once at the
end. The simplest wiring is the SessionEnd hook; the per-event form is there when
you want true streaming.

1. **Point a hook at the transcript.** Claude Code writes the session to a
   `.jsonl` and hands a SessionEnd hook its `transcript_path` + `session_id` on
   stdin. The hook calls `stele-ingest` with that path (full hook setup, with the
   `settings.json` snippet, is in
   [agent-integration.md](agent-integration.md#pattern-3b-sessionend-ingest-the-conversation-feed)):
   ```bash
   stele-ingest "$transcript_path" --session-id "$session_id" --namespace sessions
   ```
2. **Each event is reduced as it is read.** `reduce_event(event, cfg)` runs per
   line: non-conversation events (file-history-snapshot, attachment, metadata,
   system) and thinking signatures are dropped; tool bodies are truncated to the
   keep120 tier; `role` + `is_error` are preserved. Nothing raw reaches storage.
3. **The reduced session is stored as ONE artifact** with a TTL (default 30d),
   PII-scrubbed by the store boundary when `pii.enabled`. You get back a
   `stele://` ref.
4. **Phase B distills that reduced artifact later** (never the raw transcript),
   which is exactly why the feed makes distillation cheap.

### True per-event streaming (optional)
To process events as they arrive instead of once at session end, the same filter
accumulates a live stream:
```python
from stele.extraction.ingest import reduce_stream, ingest_session
turns = reduce_stream(live_event_iterator)            # reduce as events arrive
ingest_session(stele, transcript=turns, namespace="sessions")  # store once, at the end
```
Store **one artifact per session** (at SessionEnd), not per turn: artifacts are
immutable, so per-turn storage fragments a session across many artifacts.

### Keeping it tidy and streaming
- **Reduced, not raw, by construction.** The feed stores the keep120 form
  (~5.6% of raw), so the store stays small without a cleanup step. Use
  `--keep-raw` only where verbatim retention matters.
- **One artifact per session.** Fire on SessionEnd (once); if you also fire on
  Stop, dedupe by `session_id` at distill time.
- **TTL on the raw, none on the distilled.** Reduced sessions expire (30d via
  `ttl_seconds` + nightly `cleanup_expired`); the distilled memories persist and
  evolve by supersession.
- **Incremental distill.** Phase B touches only sessions newer than the
  watermark, so history is never reprocessed.
- **Consolidate the memories.** `stele.distill.consolidate(scope)` retracts stale
  duplicates so the long-lived store reflects current truth, not a pile of
  contradictions.

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
# -> {"ref": "stele://sessions/...", "raw_ref": null, "turns": 5169, "chars": 1337962}
```
Retention tiers (measured on a real 24MB session, % of raw stored):
```bash
stele-ingest s.jsonl                      # keep120 (default)  5.6%
stele-ingest s.jsonl --result-chars 300   # keep300            6.4%
stele-ingest s.jsonl --full               # full bodies        16.1%  (no signatures/meta)
stele-ingest s.jsonl --keep-raw           # keep120 reduced + the EXACT raw bytes (raw_ref)
```
`--keep-raw` stores a second `source=session-raw` artifact for full-fidelity
retention, so you can distill from the reduced form and still keep the verbatim
original (re-distill later at a higher tier, audit, exact fetch-back). All tiers
share the config defaults (`ExtractionConfig.reduce_*`; a char limit of `null` =
the full tier). Hook template: `packaging/templates/hooks/claude-code-ingest.sh.j2`
(SessionEnd).
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

### Incremental selection (benchmark harness)
Each periodic run distills only sessions modified since the last run:
```bash
# watermark file advances each run; only new sessions are processed next time
.venv/bin/python -m benchmarks.external.memory_modes.distill_fleet \
  --namespace project-memory --windows 1 --watermark /var/lib/stele/distill.wm
# or a rolling window: --since-days 7
```
Measured: of 5,711 sessions, ~388 were modified in the last 7 days, ~28 in the
last day, so a daily run is minutes.

### Temporal supersession (shipped)
Run `consolidate` after a distill batch to keep the long-lived store current:
it clusters active memories by embedding similarity and **retracts all but the
newest** in each cluster (newest by `session_mtime`, stamped by `from_session`),
so "version 0.5" gives way to "version 0.6" instead of both lingering.
```python
stele._distill_embedder = build_memory_embedder(cfg.indexing)  # inject once
report = stele.distill.consolidate(scope)   # {"clusters": n, "retracted": m}
```
Requires an injected embedder; it is a maintenance pass, not on the hot path.

### Stream reduction filter: `reduce_event` / keep120 (shipped 0.6.0)
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

#### Extraction-prompt coverage of `instruction` / `preference` (fixed in 0.6.2)
Reduction is not the only thing that can starve a view. The `skills` and
`best_practices` views are **kind-gated to a single kind each** (`skills` <-
`instruction`, `best_practices` <- `preference`), so each is only as rich as the
extractor's emission of that one kind. Through 0.6.1 the extraction prompt
(`_EXTRACT_PROMPT`) gave `instruction`/`preference` only a terse one-line gloss
while the preamble pushed toward failure/fact signal, so a real LLM emitted them
rarely and both views came out near-empty even on transcripts full of stated
rules and preferences (issue #59).

0.6.2 fixes the prompt (a per-kind bulleted list with a concrete example for every
kind, plus an explicit "extract instructions and preferences" directive). Measured
on 6 real transcripts (paired A/B, identical inputs, temp 0): behavioral
extraction roughly doubled (46 -> 79), `preference` 9 -> 31; an A/A control put
run-to-run jitter at 0 for `preference` and 5 for behavioral, and a per-window
correlation (r ~ 0) showed the gain is not the `decision` drop relabeled.

**Downstream action when upgrading from <= 0.6.1:** distilled memory is long-lived
and Phase B is incremental (it only touches sessions newer than the watermark), so
upgrading does **not** retroactively re-extract already-distilled history. If your
`skills` / `best_practices` views are thin from an earlier run, re-distill the
affected sessions after upgrading: reset the watermark (or pass an explicit
`--since-days` / `--start` window) so `from_session` re-runs over them. New
sessions pick up the fix automatically. Absolute counts are model-specific; the
defensible result is the paired delta on identical inputs.

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

### Reduction recall: keep vs drop (production budget, measured)
At the production window budget (3 failure-first windows/session, what
`from_session` actually uses), 8 sessions, temperature 0:

| reduction | memories | vs full | note |
|---|---|---|---|
| full (keep all bodies) | 85 | 100% | baseline |
| keep300 | ~81 | 95% | within noise of full |
| **keep120 (default)** | **90** | **106%** | matches full; smallest |
| drop / old minify | 62 | 73% | loses ~30%, hits rules hardest |

Two findings behind this: (1) extraction yields ~2 memories per window
regardless of reduction tier, so total memories track window count, not how hard
you truncate; (2) the only cliff is keep-vs-drop. Keeping the first ~120 chars of
each successful result preserves the headline fact; dropping the result loses it.
Raising the cap above ~120 buys nothing (the tail is ephemeral). A separate
finding: the "collapse repeated tool calls" step is a **no-op** on real
transcripts (0-1.3% of tool turns), because calls are interleaved with their
results; all reduction value is in result handling.

### Corpus + distill throughput (measured)
On a real corpus of **5,673 sessions / 1.22GB raw**:
- **Stored reduced:** full-parsed ~70MB (5.7% of raw; the parse alone removes
  94%); keep120 is smaller; drop/minify ~23MB. The full-vs-drop delta is ~47MB
  corpus-wide, so storage is not a reason to drop.
- **Window distribution:** ~1.42 windows/session (67% are 1 window, 23% two,
  9% three). So the whole corpus is ~8,065 LLM calls at `--windows 3` (~5,673 at
  `--windows 1`), not "5,673 x something big".
- **Distill time:** ~5.3s/window-call on a local Spark. Full backfill ~1-1.5h
  on both Sparks pooled, ~8-12h serial. The old "~26h" figure was embedding,
  not distillation; skip transcript indexing and it is LLM-bound (~1-1.5h).

## Capacity planning

Size three things: storage, distill compute, and cadence. Numbers are measured on
the 5,673-session / 1.22GB corpus and a laptop-dispatcher + two-Spark topology.

### Storage
| what | per 24MB-raw session | per 1,000 sessions (rough) | retention |
|---|---|---|---|
| raw `.jsonl` (only if `--keep-raw`) | 24MB | ~215MB | your choice |
| keep120 reduced artifact | 1.3MB (5.6%) | ~12MB | 30d TTL |
| distilled memories | ~5-10 records | ~5-10k records | no TTL (persists) |

- The store stays small by construction (keep120 = ~5-6% of raw; whole corpus
  reduced is ~70MB). `--keep-raw` multiplies it back toward 100% of raw.
- **Plan for distilled-memory growth, not raw.** Raw expires; memories
  accumulate (~5-10 per substantive session). Run `consolidate` so they do not
  pile up as contradictions.

### Distill compute
- Work scales with **windows, not bytes**: ~1.42 windows/session, so a corpus of
  N sessions is ~`N x 1.4` short LLM calls at `--windows 3`.
- ~5.3s/call on a local Spark. Pool both Sparks (Qwen ~4 + Gemma ~8 concurrent)
  for ~12-way; the full corpus backfill is ~1-1.5h, steady-state daily runs are
  minutes.
- **Embedding, not distillation, is the laptop cost.** Sync chunk-indexing a
  reduced session is ~22s/session on laptop CPU. For a distill-only pipeline,
  store raw with `indexing.mode=skip` and embed only the (small) distilled
  memories; the 22s/session disappears. Offload transcript embedding to a GPU if
  you do want raw-session vector search.

### Cadence and sizing rule of thumb
- ~28 new sessions/day, ~388/week on this corpus. Daily incremental distill =
  minutes; weekly = well under an hour. **Hard rule: Phase-B cadence < raw TTL.**
- For N new sessions/day: distill time ~= `N x 1.4 x 5.3s / concurrency`
  (N=100/day at ~12-way is a few minutes); reduced-storage resident set ~=
  `30 x N x 1.3MB` (30-day TTL) plus the permanent distilled memories.
- The one-time history backfill is the only large job; everything after is
  incremental.

## Config knobs
- `ttl_seconds` on stash (raw retention; 30d).
- `ENDPOINTS` + caps in `distill_fleet.py` (pool + concurrency).
- `--windows` (1 for small sessions; more for large).
- `DistillConfig.synthesis` ("auto" uses the injected LLM; "deterministic" skips it).
- Injected `llm` (refine quality) and `embedder` (semantic dedup) on `Stele.distill`.
