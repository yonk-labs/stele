# Spec: compact return for structured payloads

Status: tiers 1-2 shipped (2026-06-25, branch `feat/compact-return`); tier 3 proposed. Owner: stele core.

## Using it (tiers 1-2)

Nothing to configure. It runs automatically inside every `store()` /
`stash_tool_result()` via `_summarize_content`: a JSON object/array payload gets a
compact summary and bypasses the prose summarizer entirely. No flag, no API change,
no behavioural change for non-JSON content. The dispatch (`compact_or_digest`):

- If the losslessly-minified payload fits the summary budget (`summary.max_chars`),
  the summary **is** that minified JSON. Lossless, exact.
- Otherwise the summary is a bounded structural digest: top-level keys + types,
  array lengths, a minified sample, and a `fetch the stele:// ref` marker. Lossy
  hint; the full payload is one `fetch` away. Example: a 74 KB / 2000-row JSON
  object collapses to a 1.2 KB summary that still names every top-level key, its
  type, and the array length.
- Non-JSON (prose, code) is unchanged: it still goes to the `lede` summarizer.

## How data loss is prevented

Three layers, in order:

1. Storage is upstream and immutable. Compaction only ever runs on a model-visible
   *derivative* (the summary). The artifact is stored byte-for-byte first
   (`digest_sha256`, `byte_size` computed from the original); the exact-bytes
   invariant is guarded by `tests/unit/test_architecture.py`.
2. Tier 1 is lossless regardless: minify is a `json.loads` / `json.dumps`
   round-trip, so the data is identical and only whitespace differs.
3. For the lossy tiers (2-3), the compact form is a *hint*, the `stele://` ref is
   the truth, and the agent recovers exact bytes with `fetch`. A summary can lose
   detail; the source never does.

Fail-safe: `compact_or_digest` never raises into the summary path. Malformed or
non-JSON input returns `None` and falls back to the prose summarizer, so a bad
payload cannot break a stash.

## Problem

stele's model-visible surfaces (the stored summary, `fetch` snippets, recalled
memory payloads) are produced by `lede`, a prose-extractive summarizer. JSON and
tabular (DB-result) payloads are not prose. Running a prose summarizer over them
wastes the bounded budget on structural whitespace and produces a poor digest.
Per the cost model in `process-is-the-memory.md` (§3), a record's value is
debited by its `footprint_tokens`; shrinking the footprint of a structured
payload directly raises its reuse value.

This is the *retrieval lane*, not the process lane. It is orthogonal to and
stacks with `headroom` (structural JSON compression 89-95%, prose/code ~0%).

## Principle (non-negotiable)

Exact bytes are sacred. Compaction only ever touches a **model-visible
derivative** (summary, snippet, recalled payload). The stored artifact is never
minified. A compact form is a *hint*; the `stele://` ref is the truth, and the
agent expands via `fetch`. This is the paper's "hint vs truth" rule, reused.

## Tiers (lazy ladder, stop at the first that holds)

1. **JSON minify (lossless).** `json.loads` then `json.dumps(separators=(",",":"),
   ensure_ascii=False)`. Free, lossless, ~2-4x on pretty-printed JSON. Applies
   only to top-level `dict`/`list` (containers, where whitespace lives).
   **Shipped** (`compact_json`, and the fits-branch of `compact_or_digest`).
2. **Structural digest (bounded, lossy).** When minified JSON still exceeds the
   summary budget: emit top-level keys + value types + array lengths + a minified
   sample, with a `(+N more keys)` cap and a fetch marker. **Shipped**
   (`compact_or_digest` -> `_structural_digest`). Tabular/DB-result handling
   (column names + types + K sample rows + row count) is still future work; a
   DB result serialized as a JSON array already gets the array digest.
3. **headroom tier (heavy, lossy-on-structure).** Route JSON/log payloads through
   `headroom` (already a sibling tool, rung-4 dependency, not new) for 89-95%
   compression when the structural digest is still too large.

## Integration seam

`core/stash.py::_content_to_summary_text` (line ~1195) is the single chokepoint:
it decodes content and hands text to `summary_provider.summarize(...)`. A new
`summary/compact.py::compact_json(text) -> str` is called there. Content-type is
sniffed by attempting `json.loads` (no signature change needed); non-JSON and
scalars pass through unchanged.

Tiers 2-3 graduate to a content-type-aware `SummaryProvider` selector
(`base.py::SummaryProvider`), chosen on the artifact's `content_type` /
sniffed shape, sitting beside `LedeSummaryProvider`. Out of scope for slice 3.

## Safety

`compact_json` must never raise into the summary path: any parse/dump failure
returns the input unchanged. Covered by a unit test asserting (a) round-trip
losslessness, (b) size reduction on pretty JSON, (c) pass-through for prose and
malformed JSON.

## Out of scope

- Minifying stored artifacts (violates exact-bytes).
- Tiers 2-3 (separate slices).
- Any new runtime dependency (headroom is already vendored in the workspace).
