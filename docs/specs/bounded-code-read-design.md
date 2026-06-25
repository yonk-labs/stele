# Spec: dependency-aware bounded code reads

Status: design (2026-06-25). Owner: stele core. Evidence:
[agent-memory-research-summary.md](../measurements/agent-memory-research-summary.md),
`benchmarks/session_reuse_audit.py`.

## Problem

Coding agents over-fetch: they `Read` a whole file when one function was needed.
Measured across six real projects (85 session groups, ~11.7M read tokens),
over-fetch is ~65% of edit-anchored read tokens (~1.42M), the single largest
*real* inference-token lever for coding agents. Re-read dedup only moves data;
command/outcome reuse collapsed to ~0 on real coding transcripts.

The catch, proven by a falsification test: you cannot capture this with a naive
window or vector RAG. Reproducing a function from a naive cursor-window span
succeeded in **1 of 30** cases; from a **dependency-aware** span (the span plus
the definitions it references) in **30 of 30**, both at ~6% of full-file tokens.
A dependency-blind span breaks the task. Retrieval must follow references.

## Principle

A code read returns a **layered bounded view**, not the whole file and not a dumb
window. The model keeps agency: every bounded view advertises how to escalate, so
the one real failure mode (a mis-sized or dependency-blind span) is recoverable by
the agent, never silent. Exact bytes are stored as the artifact; the bounded view
is a model-visible *derivative*; the full file is one `fetch` away. This is the
same hint-vs-truth rule stele already uses for summaries and compact-return.

## The layered bounded view (priority order)

1. **Requested span** (verbatim). What the agent asked for: a line range or a
   named symbol. Always included.
2. **Resolved dependencies** (load-bearing). The definitions the span references
   that are not in the span, each as a signature plus body (recursively bounded if
   large). This is the leg the falsification proved is mandatory.
   - In-file: AST locates identifiers in the span and their defs in the same file.
   - Cross-file: stele's pg-raggraph **graph path** follows import/call edges to
     the defining file and symbol. Graph over vector, because code dependencies
     are edges, not similarity.
3. **Signature outline of the rest** (cheap orientation). Other top-level defs in
   the file as names plus signatures only, no bodies, so the agent sees what else
   exists without paying for it.
4. **Optional semantic RAG** (weakest leg, last). If the agent's task query is
   available, one or two semantically-related spans. Optional because structure
   beats similarity for code; it only catches what the graph misses (e.g. a usage
   example).
5. **Expansion handles** (agency, de-risks the 1/30). Explicit affordances:
   `expand <symbol>`, `expand lines A-B`, `full file: fetch <ref>`. The agent
   escalates when the bounded view is insufficient.

## Where it lives in stele

Two insertion points, not mutually exclusive:

- **A retrieval verb (primary):** `read_bounded(path_or_ref, *, span, task=None)`
  returning the layered view. Agents/harnesses call it instead of a raw full
  `Read` for large code files. This is the only path with the agent's *task*, so
  it is the only one that can do the query-biased semantic leg (4).
- **An interception transform (secondary):** at `interception/wrapper.py`, a
  code-file `Read` result (content-type / extension sniff) is reshaped into the
  bounded view. This path lacks the task query, so it can do legs 1-3 and 5 but
  not 4. It is the zero-config fallback for agents that do not adopt the verb.

Exact-bytes invariant holds in both: the artifact is the full file; expansion is
`fetch` with a span selector.

## Dependency resolution

- In-file: Python via the stdlib `ast`. Multi-language via tree-sitter later.
- Cross-file: the pg-raggraph graph path (already in stele as the optional graph
  retrieval). This is the load-bearing, falsification-proven component. A vector
  fallback is explicitly *not* a substitute; it may sit beside the graph as leg 4.

## Data safety and agency

- The artifact stores exact bytes; the bounded view never replaces them.
- The bounded view always carries expansion handles, so a too-small or
  dependency-blind slice is recoverable, not a silent wrong answer.
- A `fetch(ref)` with no span returns the full file unchanged.

## Phasing (lazy ladder)

- **Slice 0 (boundary + agency, Python, no deps yet):** requested span +
  signature outline of the rest + expansion handles. Proves the UX and plumbing,
  ships the agency mechanism, captures the localizable easy cases.
- **Slice 1 (the mandatory leg):** in-file dependency resolution via `ast`.
- **Slice 2 (the real win):** cross-file dependency resolution via the graph path.
- **Slice 3:** optional semantic leg; multi-language via tree-sitter.

## Open questions

- **Adoption.** The verb is opt-in; the interception transform is automatic but
  task-blind. Which is the default for the first slice?
- **The Unknown bucket (sized, 2026-06-25).** 82% of measured reads are
  un-adjudicable directly from transcripts. We intent-classified a 160-read sample
  of the single-read source bucket with a local code model (Qwen3-Coder): ~98% of
  tokens were TARGETED (one function/section) or SCAN (orientation), ~2% WHOLE. A
  6-case calibration probe scored 5/6 (the classifier does recognize obvious
  whole-file tasks, so the high fraction is not pure bias), and the result is
  mechanistically sensible: read-once, never-edited files are reference lookups,
  while whole-file refactor targets get edited and fall in the edit-anchored
  bucket instead. Read it as "the large majority is addressable" (~80-95%+), not
  the literal 98%. Caveats: an LLM proxy for intent, not the counterfactual; sample
  not census; token weights use post-truncation read sizes. This triangulates with
  the already-run counterfactual (bounded approximates full at 10-30% tokens) and
  the falsification (dependency-aware required). **Net: the lever is real and the
  bucket is largely addressable; slice 0 is justified.**
- **Counterfactual ceiling.** Bounded approximate full at 10-30% tokens on a
  40-case sample; the production saving depends on how much real work is
  localizable, which #3 informs.

## Non-goals

- Replacing the harness `Read` tool (stele offers a view, it does not own Read).
- Minifying or mutating stored artifacts.
- A vector index as the dependency resolver (the falsification rules it out for
  the load-bearing leg).
