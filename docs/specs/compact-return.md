# Spec: compact return for structured payloads

Status: proposed (2026-06-25). Owner: stele core.

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
   only to top-level `dict`/`list` (containers, where whitespace lives). **This
   is slice 3, shipping first.**
2. **Structural digest (bounded, lossy).** When minified JSON still exceeds the
   summary budget: emit top-level keys + value types + array lengths + the first
   K sample elements minified, with a `"… N more"` marker. For tabular: column
   names + types + K sample rows + row count.
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
