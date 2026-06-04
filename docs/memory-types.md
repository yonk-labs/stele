# Stele Memory Types and Architecture

What stele's memory is made of, the layers it lives in, and how each type is
produced and served. This is the single entry point; it links out to the flow,
tutorial, and architecture docs rather than repeating them.

## TL;DR

Stele has three layers that each have their own list, and "the six types of
memory" can mean any of them depending on context:

- **`MemoryKind`** (11 values): the storage primitive. Every memory record is
  exactly one kind. This is the ground truth in the code.
- **Distill views** (6): groupings *over* kinds that the `Stele.distill` facade
  synthesizes for reuse (`facts`, `precedents`, `state`, `skills`,
  `best_practices`, `rules`).
- **Benchmark modes** (6): the recall *scenarios* that test those views
  (`fact_recall`, `precedent_recall`, `resume_task_state`, `skill_adherence`,
  `best_practice`, `guardrail_adherence`).

There is also a separate "6" that is unrelated: the recall *strategies* (how
context is assembled at read time). See [tutorial-memory.md](tutorial-memory.md).

These layers refine, rather than replace, the classical
**semantic / episodic / procedural** memory taxonomy; the mapping is at the end
of this doc.

## Layer 1: `MemoryKind` (the storage primitive)

A memory record (`stele.core.memory_record.MemoryRecord`) carries exactly one
`kind`. There are **11**, defined as one `Literal` in
`src/stele/core/memory_record.py` (the DB CHECK constraint is derived from it, so
the schema can never drift):

| kind | what it captures |
|---|---|
| `fact` | a durable fact, result, or state |
| `preference` | a stated preference ("prefer X over Y") |
| `decision` | a choice plus its rationale |
| `instruction` | a rule the user stated (always / never) |
| `commitment` | something promised / to be done |
| `issue` | an open problem |
| `summary` | a condensed overview |
| `pitfall` | **cq L1**: a sharp edge encountered (a failure / deadend) |
| `workaround` | **cq L2**: how the pitfall was worked around (the fix) |
| `tool_recommendation` | **cq L3**: a tool that addresses the pitfall |
| `tool_gap` | **cq L4**: a synthesized "missing tool" signal |

The last four are the **cq lifecycle** (L1 to L4): a pitfall gets a workaround,
which may point to a tool, which clusters into a tool-gap. stele stores the
kinds; the L4 tool-gap synthesis is a consumer concern (issue #38).

Every record also carries the fields that make memory **evidence-cited and
evolving**, not an append-only log:

- `source_refs` (required, must be `stele://` URIs): the evidence. `memory.add`
  rejects a memory with no refs.
- `summary` / `detail`: tripartite insight (the headline and the body; both are
  indexed).
- `status`: one of `active`, `superseded`, `retracted`, `disputed`, `deleted`.
- `supersedes`: memory evolves by **supersession**, never in-place edit.
  `memory.update()` rejects text changes and redirects to `add(supersedes=[id])`.
- `confirmations`: times re-observed; raises confidence via `evolved_confidence`.
- `effective_until`: optional validity horizon.

Artifacts are immutable; memory evolves. That boundary is guarded by
`tests/unit/test_architecture.py`.

## Layer 2: distill views (6 groupings over kinds)

`Stele.distill` (subsystem in `src/stele/distill/`) synthesizes six
externally-consumable **views** from the stored kinds. Each is an `async` method
returning a `DistilledView`; every item keeps its `source_refs`.

| view | drawn from kinds | what it is | where its evidence lives |
|---|---|---|---|
| `facts` | `fact` | durable facts/results/state | successful tool results |
| `precedents` | `decision` | choices + why (including rework) | assistant prose / user turns |
| `state` | recent `fact` / `decision` / `commitment` | resume-the-task snapshot | successful Read/Bash/Write result bodies |
| `skills` | `instruction` (+ patterns) | reusable how-to | results + prose |
| `best_practices` | `preference` | suggest-not-force guidance | stated prose / user turns |
| `rules` | `pitfall` + `workaround` + `instruction` | "don't X, do Y" pairs, in-family remediation | errors + the fix in the following result |

The "where the evidence lives" column is why the ingestion reduction tier matters
(see [distillation-flow.md](distillation-flow.md#impact-by-memory-type-keep120-vs-drop)):
facts/rules/skills/state draw on successful tool output, so dropping it costs
them; precedents/best_practices are prose-borne and nearly immune.

`tool_recommendation` / `tool_gap` do not map to one of the six views; they feed
the separate tool-gap synthesis.

Distillation is **oracle-free and deterministic by default**: an injected LLM
only refines (e.g., pairing a `don't` with its `do_instead`), and an injected
embedder only de-duplicates. Both are optional. See
[distillation-flow.md](distillation-flow.md).

## Layer 3: benchmark modes (6 scenarios that test the views)

The six modes in `benchmarks/external/memory_modes/` are recall *scenarios*: each
proves a view earns its keep where a plain retriever would not. They map 1:1 to
the views:

| mode | tests the view | the claim it proves |
|---|---|---|
| `fact_recall` | facts | recall a fact from history beyond the context window |
| `precedent_recall` | precedents | surface a past decision + its rationale |
| `resume_task_state` | state | reconstruct where work left off |
| `skill_adherence` | skills | apply a learned how-to |
| `best_practice` | best_practices | suggest the better-known approach |
| `guardrail_adherence` | rules | enforce a "never do X" rule |

Results and the honest preconditions for each are in
[benchmarks/memory-modes-results-2026-06-02.md](benchmarks/memory-modes-results-2026-06-02.md).
Memory is benchmarked where it *diverges* from RAG (history beyond context,
evolving facts, enforcement), not as a retriever.

## How memory is produced and served (architecture)

```
  PRODUCE                                    SERVE
  ┌───────────────────────────────┐         ┌──────────────────────────────┐
  │ artifact (exact bytes + ref)   │         │ Stele.search  -> SearchHit[]  │
  │   stele.store(...)             │         │ Stele.recall  -> assembled    │
  │     |                          │         │   context (6 strategies)      │
  │     v  evidence ref            │         │ Stele.distill.<view>(scope)   │
  │ Stele.extract / from_session   │  ────▶  │   -> DistilledView (6 views)  │
  │   -> kinded MemoryRecord       │         │ Stele.memory.search/list      │
  │   via Stele.memory.add         │         │   (active-head, as_of)        │
  └───────────────────────────────┘         └──────────────────────────────┘
       kinds are written once               views/recall are computed on read
```

- **Produce.** Raw work becomes an immutable artifact (`store`, with the bytes
  behind a `stele://` ref). `Stele.extract` (structured text / messages) and
  `Stele.extract.from_session` (agent transcripts, via the
  [reduce_event](distillation-flow.md#stream-reduction-filter-reduce_event--keep120-shipped-060)
  filter) turn that into kinded `MemoryRecord`s through `Stele.memory.add`. Every
  memory cites the artifact as evidence.
- **Serve.** `Stele.memory.search/list` returns the active head (with `as_of`
  time-travel and supersession-aware filtering). `Stele.recall` assembles an
  LLM-ready context block via a recall strategy. `Stele.distill.<view>`
  synthesizes the six views on demand.
- **Facades only.** Extraction, recall, and distill consume the public facades
  (`Stele.memory` / `Stele.search` / `Stele.fetch`), never storage internals.
  PII scrubbing is inherited from those surfaces, never re-applied.

The full module breakdown, data flows, and data model are in
[architecture-sovereign-stele.md](architecture-sovereign-stele.md); the
hands-on store/extract/supersede/recall walkthrough is in
[tutorial-memory.md](tutorial-memory.md); the ingestion-to-distillation pipeline
(the reduction filter, the conversation feed, capacity planning) is in
[distillation-flow.md](distillation-flow.md).

## The three "sixes", reconciled

| MemoryKind (stored) | -> distill view | -> benchmark mode |
|---|---|---|
| `fact` | `facts` | `fact_recall` |
| `decision` | `precedents` | `precedent_recall` |
| recent `fact`/`decision`/`commitment` | `state` | `resume_task_state` |
| `instruction` | `skills` | `skill_adherence` |
| `preference` | `best_practices` | `best_practice` |
| `pitfall` + `workaround` + `instruction` | `rules` | `guardrail_adherence` |
| `issue`, `summary`, `tool_recommendation`, `tool_gap` | (no standard view; cq L3/L4 feed the tool-gap synthesis) | -- |

Kinds are the durable storage primitive; views and modes are computed on top.
When someone says "the six types of memory," ask which layer they mean: the
stored kinds (11), the distilled views (6), or the benchmark modes (6).

## Relation to the classical taxonomy (semantic / episodic / procedural)

Cognitive science groups memory into three kinds (Tulving's semantic vs
episodic; Squire's declarative vs procedural), and LLM-agent work applies the
same split (e.g. CoALA, *Cognitive Architectures for Language Agents*, which adds
**working memory** as a fourth). That trio is the *category* level; stele's
kinds and views are the leaf types beneath it. They do not compete with the big
three, they refine it.

| classical type | what it is | stele views | stele kinds |
|---|---|---|---|
| **Semantic** | facts, concepts, what is *true* (decontextualized) | `facts` (+ some `best_practices`) | `fact`, `summary`, `issue` |
| **Episodic** | events, what *happened when* (context-bound) | the raw **artifacts/sessions** + `state` + `precedents` | `decision`, `commitment` (+ the stored sessions) |
| **Procedural** | skills, how to *act* | `skills`, `rules`, `best_practices` | `instruction`, `preference`, `pitfall`, `workaround`, `tool_recommendation`, `tool_gap` |
| **Working** | the current task's context | assembled by `Stele.recall` (not stored) | -- |

The mapping is not arbitrary; it falls out of the architecture:

- **Artifacts are the episodic substrate.** A stored session (the exact bytes
  behind a `stele://` ref) *is* the record of what happened. Episodic memory in
  stele is the evidence layer.
- **Distilled memory is the semantic + procedural knowledge extracted from
  episodes.** `facts` are semantic; `skills` / `rules` / `best_practices` are
  procedural. The evidence-artifacts vs distilled-memory boundary IS the
  episodic vs semantic/procedural distinction.
- **The procedural layer is unusually graded.** The cq lifecycle
  (`pitfall -> workaround -> tool_recommendation -> tool_gap`) is procedural
  learning about sharp edges, and `rules` are procedural-as-enforcement, where
  most systems carry only a thin tool list.

Two honest caveats:

- **Some types straddle.** `precedents` / `decision` is episodic in *origin* (a
  decision is an event) but becomes semantic once distilled ("we use X because
  Y"). `best_practices` is procedural guidance stated as a `preference`.
- **Distilled-episodic is intentionally thin.** `state` (resume) and
  `precedents` are the only distilled-episodic views; true event/timeline recall
  ("what happened in the auth refactor last Tuesday?") is served today by raw
  artifact/session search, not a first-class episodic view. Closing that gap is
  a tracked direction (episodic recall).
