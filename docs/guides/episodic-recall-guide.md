# Episodic Recall: a step-by-step guide

How to read your past sessions back as **episodes**, a **timeline**, cross-session
**spans**, and via **episodic recall**. For the conceptual model (how episodic
sits beside semantic and procedural memory), see
[memory-types.md](../reference/memory-types.md#relation-to-the-classical-taxonomy-semantic--episodic--procedural).
For how sessions get ingested in the first place, see
[distillation-flow.md](memory-distillation-guide.md).

An **episode** = one past session: its stored artifact plus the memories that
session produced (back-linked by `source_refs`). Everything below is computed on
read from those, so nothing new is written to the store.

## Run it yourself

A self-contained tour (in-memory backend, no DSN) is at
[`examples/episodic_tour.py`](../../examples/episodic_tour.py):

```bash
.venv/bin/python examples/episodic_tour.py
```

It ingests three past sessions (two about a dashboard, one about auth, dated days
to weeks back) and then runs the four reads below. The output shown here is from
an actual run; dates are relative to "now" so the "last week" query lands.

## 1. Episodes: one "what happened" per session

```python
import asyncio
from stele.core.memory_record import MemoryScope
scope = MemoryScope(namespace="tour")
for it in asyncio.run(stele.distill.episodes(scope)).items:
    print(f"[{it.when:%Y-%m-%d}] {it.session_id}: {it.summary}")
```
```
[2026-06-03] sess-auth:   decided move token refresh into a single interceptor. hit refresh storm when 401s arrived in parallel; added a mutex (2 memories)
[2026-06-01] sess-dash-1: decided use a CSS grid for the dashboard widget layout. hit widget overflow broke the grid until min-width was set (2 memories)
[2026-05-15] sess-dash-2: decided standardize dashboard widget spacing on an 8px scale (1 memory)
```
One summary per session, newest-first, each composed from that session's
decisions and pitfalls. `episodes(scope, since=, until=)` windows by time.

## 2. Timeline: the narrative sequence, optionally filtered

```python
for it in asyncio.run(stele.distill.timeline(scope, query="dashboard")).items:
    print(f"[{it.when:%Y-%m-%d}] {it.session_id}: {it.summary}")
```
```
[2026-05-15] sess-dash-2: decided standardize dashboard widget spacing on an 8px scale (1 memory)
[2026-06-01] sess-dash-1: decided use a CSS grid for the dashboard widget layout. hit widget overflow broke the grid until min-width was set (2 memories)
```
Same episodes as `episodes()`, but ordered **oldest-first** (read it as a story)
and filtered to the `query`: the auth session is correctly dropped, only the two
dashboard sessions remain. `timeline(scope, since=, until=, query=)`.

## 3. Spans: cross-session arcs

```python
for s in asyncio.run(stele.distill.spans(scope)).items:
    print(f"span {s.started:%Y-%m-%d}..{s.ended:%Y-%m-%d} {s.session_ids}: {s.summary}")
```
```
span 2026-06-03..2026-06-03 ['sess-auth']: decided move token refresh into a single interceptor ...
span 2026-05-15..2026-06-01 ['sess-dash-1', 'sess-dash-2']: [2 sessions] ... CSS grid for the dashboard widget layout ... -> ... standardize dashboard widget spacing ...
```
The two dashboard sessions cluster into **one span** spanning May 15 to June 1
(the whole dashboard arc, across sessions); auth stays its own span. Spans
cluster by the embedding similarity of episode summaries, so they need an
injected embedder (`stele._distill_embedder`); the tour uses the real
`build_memory_embedder` (the `chunkshop` extra). With no embedder, every episode
is its own one-member span. `spans(scope, threshold=0.65)`.

## 4. Episodic recall: "what was I building last week"

```python
result = stele.recall.episodic(query="what was I building last week", scope=scope)
for h in result.episodes:
    print(f"[{h.when:%Y-%m-%d}] score={h.score:.2f} {h.session_id}: {h.summary} ({len(h.memories)} memories)")
```
```
[2026-06-01] score=0.03 sess-dash-1: ... CSS grid for the dashboard widget layout ... (2 memories)
[2026-06-03] score=0.00 sess-auth:   ... token refresh into a single interceptor ... (2 memories)
[2026-05-15] score=0.00 sess-dash-2: ... standardize dashboard widget spacing ... (1 memory)
```
The in-window dashboard session ranks first (it is within "last week" and
matches "building"), and each hit carries the memories that session produced.
Note the temporal filter is a **soft boost by default**: it ranks the in-window
episode first but does not exclude the others. Pass `hard_temporal=True` to
restrict to the window (with a fallback to the unfiltered rank if the window
matches nothing, so it never returns empty).

## CLI and MCP

```bash
stele distill episodes --namespace tour
stele distill timeline --namespace tour
stele distill spans    --namespace tour
```
Over MCP: `stele_distill` with `mode=episodes|timeline|spans`. The CLI/MCP take
`mode` + `namespace`; the advanced filters (`since`/`until`/`query`/`threshold`)
are on the Python facade.

## Tuning notes

- **Spans `threshold` (default 0.65).** Calibrated for `bge-base`, which runs hot
  (unrelated short texts sit near 0.5, same-topic near 0.76). Raise it for
  tighter arcs, lower it to merge more loosely. It is **not** the same as
  `consolidate`'s 0.82 near-duplicate threshold.
- **Timeline `query` floor (0.55).** Same calibration: keeps on-topic episodes,
  drops off-topic ones. With no embedder injected it falls back to token overlap.
- **Recall is soft-boost by default**, never LLM-backed: `parse_temporal` reads
  the time phrase, recency/window boosts the rank, and `hard_temporal=True` is
  the opt-in hard filter (with an empty-window fallback).
