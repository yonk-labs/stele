# Stele MCP Tools — Reference

This document is the **ground-truth reference** for the 26 tools the `stele-mcp` server exposes to MCP-capable agents. Schemas, types, and examples are derived from `src/stele/mcp/tools.py` — not from the design spec, which the implementation diverged from in deliberate ways (see [§ Drift from spec](#drift-from-spec)).

**Every tool has a CLI equivalent.** The `stele` binary's data-plane subcommands call the same `bind_handlers()` engine over the same `Stele` instance and emit the same JSON shapes. Pick whichever surface fits the moment — MCP for agent-driven calls, CLI for shell scripts, pipelines, and debugging. See the [Tool table](#tool-table) for the mapping and [`docs/reference/cli-reference.md`](cli-reference.md) for the full CLI command reference with flags.

- **Transport:** stdio only (v1).
- **Server:** `stele-mcp` (or `stele mcp` — same code path).
- **Auth:** none (local-trusted boundary; see [`docs/operations/mcp-auth-model.md`](../operations/mcp-auth-model.md)).
- **Egress sanitization:** every string in every response is run through `sanitize_label()` (ANSI strip, control-char strip, 256-char clamp) before crossing the MCP transport.
- **Error model:** any exception inside a handler is caught by the `guard` decorator and surfaces as `{"error": {"code": str, "message": str, "context": {}}}`. Mapped codes: `CONFIG`, `PII_BLOCKED`, `CAPABILITY`, `VALIDATION`. Anything else returns `INTERNAL` with a full traceback on stderr (see [`docs/operations/mcp-auth-model.md`](../operations/mcp-auth-model.md) for why this is safe in stdio).

## Tool reference

### Tool table

| MCP tool | CLI equivalent | Purpose | Required inputs |
|---|---|---|---|
| [`stele_store`](#stele_store) | `stele store --text TEXT` (or `-` for stdin) | Store bytes/text behind a `stele://` reference. | `payload` |
| [`stele_fetch`](#stele_fetch) | `stele fetch REF` | Resolve a `stele://` ref to its bytes + summary. | `ref` |
| [`stele_search`](#stele_search) | `stele search REF QUERY` | Search within an artifact via the configured retrieval backend. | `ref`, `query` |
| [`stele_query`](#stele_query) | `stele query QUERY` | Query the chunk index (vector/hybrid when configured). | `query` |
| [`stele_list`](#stele_list) | `stele list` | List stored artifacts in a namespace. | — |
| [`stele_delete`](#stele_delete) | `stele delete REF` | Delete an artifact by reference. | `ref` |
| [`stele_memory_add`](#stele_memory_add) | `stele memory add TEXT --source-ref REF` | Add a memory record citing `source_refs`. | `text`, `source_refs` |
| [`stele_memory_get`](#stele_memory_get) | `stele memory get MEMORY_ID` | Fetch a memory record by id. | `memory_id` |
| [`stele_memory_search`](#stele_memory_search) | `stele memory search QUERY` | Search memory with optional `as_of` time travel. | `query` |
| [`stele_memory_list`](#stele_memory_list) | `stele memory list` | List memory records (with `as_of`, `status_filter`). | — |
| [`stele_memory_update`](#stele_memory_update) | `stele memory update MEMORY_ID --metadata JSON` | Update memory metadata. Text changes rejected. | `memory_id` |
| [`stele_memory_delete`](#stele_memory_delete) | `stele memory delete MEMORY_ID` | Soft-delete a memory record. | `memory_id` |
| [`stele_memory_retract`](#stele_memory_retract) | `stele memory retract MEMORY_ID --reason REASON` | Retract with reason (preserves audit). | `memory_id`, `reason` |
| [`stele_extract_from_text`](#stele_extract_from_text) | `stele extract from-text --text TEXT --source-ref REF` | Run extraction on free text. | `text`, `source_refs` |
| [`stele_extract_from_messages`](#stele_extract_from_messages) | `stele extract from-messages --input FILE` | Extract from chat messages. | `messages` |
| [`stele_extract_from_artifact`](#stele_extract_from_artifact) | `stele extract from-artifact REF` | Extract from a stored artifact. | `ref` |
| [`stele_recall`](#stele_recall) | `stele recall QUERY` | Run a recall strategy over memory + artifacts. | `query` |
| [`stele_stash_tool_result`](#stele_stash_tool_result) | `<cmd> \| stele stash TOOL_NAME -` | Route oversize tool output through interception. | `tool_name`, `raw_output` |

All CLI commands accept a `--namespace NS` flag (default `"default"`), a `--pretty` flag for indented JSON output (can appear before or after the subcommand), and JSON-formatted responses on stdout. Non-zero exit code means the response payload contains an `error` object — same shape as the MCP error model.

### Common concepts

- **`namespace`** (string, default `"default"`) — appears on most memory/extract/recall/store tools. Maps internally to a `MemoryScope`. Lets a single Stele instance keep parallel memory streams (e.g., per user, per project). Most callers should pass it consistently.
- **`ref`** — a `stele://<namespace>/<artifact_id>` URI string returned from `stele_store` or any extraction call. Opaque; treat as a blob.
- **`as_of`** — ISO-8601 datetime string. Trailing `Z` is accepted (treated as `+00:00`). Both `2026-05-20T14:30:00Z` and `2026-05-20T14:30:00+00:00` work.
- **`content_type`** — enum (Literal type, NOT a MIME string). Allowed values: `text`, `json`, `table`, `csv`, `sql`, `code`, `code_diff`, `log`, `html`, `markdown`, `blob`. Passing `"text/plain"` raises `CAPABILITY`.
- **`mode`** (retrieval mode) — enum. Allowed values: `keyword`, `vector`, `hybrid`, `graph`. Default is the config's `retrieval.default_mode`.

---

### `stele_store`

Store bytes/text behind a `stele://` reference.

| Input | Type | Required | Default | Notes |
|---|---|---|---|---|
| `payload` | string | ✅ | — | The content to store. |
| `content_type` | string (enum) | | — | One of the [`ContentType` literals](#common-concepts). |
| `namespace` | string | | `"default"` | Lets you partition artifacts per user/agent. |
| `metadata` | object | | — | Free-form caller metadata. |

**Response:** `{"ref": "stele://<namespace>/<artifact_id>"}`

**Example:**
```json
// Request
{"name": "stele_store", "arguments": {"payload": "User prefers tabs over spaces.", "content_type": "text"}}

// Response
{"ref": "stele://default/01J7C4M9X0YHPQEXAMPLEID"}
```

---

### `stele_fetch`

Resolve a `stele://` reference to its bytes/text + scrub metadata.

| Input | Type | Required | Notes |
|---|---|---|---|
| `ref` | string | ✅ | A `stele://` URI from `stele_store`. |

**Response:**
```json
{
  "content": "User prefers tabs over spaces.",
  "content_type": "text",
  "scrubbed": false,
  "pii": null,
  "byte_size": 31
}
```

If `pii.raw_fetch_enabled` is `false` (default) and the artifact contains PII, fetch returns `{"error": {"code": "PII_BLOCKED", ...}}`. To get raw bytes anyway, set `pii.raw_fetch_enabled: true` in `.stele/config.yaml`.

---

### `stele_search`

Search **within** a stored artifact. Different from `stele_query` — this targets one artifact's content.

| Input | Type | Required | Default | Notes |
|---|---|---|---|---|
| `ref` | string | ✅ | — | The artifact to search inside. |
| `query` | string | ✅ | — | Free-text query. |
| `mode` | string (enum) | | config default | `keyword` / `vector` / `hybrid` / `graph`. |
| `limit` | int | | `10` | Max hits returned. |

**Response:** `{"hits": [<SearchHit>, ...]}` where each hit is the rendered form of the backend's `SearchHit` dataclass.

---

### `stele_query`

Targeted query against the chunk index across a namespace. Cross-artifact.

| Input | Type | Required | Default |
|---|---|---|---|
| `query` | string | ✅ | — |
| `namespace` | string | | `"default"` |
| `mode` | string (enum) | | config default |
| `limit` | int | | `10` |
| `session_id` | string | | — |
| `filters` | object | | — |
| `now` | string (ISO-8601) | | wall-clock |

`filters` narrows by time/metadata before ranking: `session_id`,
`created_after`/`created_before` (ISO-8601 strings), and `metadata.<key>` with
optional `__in` / `__gte` / `__lte` suffixes. `now` sets the reference clock for
`retrieval.temporal_routing`. See [filtered-retrieval.md](../guides/filtered-retrieval-guide.md).

**Response:** `{"hits": [<SearchHit>, ...]}`

---

### `stele_list`

List artifacts in a namespace.

| Input | Type | Required | Default |
|---|---|---|---|
| `namespace` | string | | (all namespaces if absent) |
| `limit` | int | | `100` |

**Response:** `{"page": <Page>}` — paginated artifact summaries.

---

### `stele_delete`

Delete an artifact by reference. Hard delete; the artifact's bytes are gone.

| Input | Type | Required |
|---|---|---|
| `ref` | string | ✅ |

**Response:** `{"ok": true}` on success, `{"ok": false}` if the ref didn't exist.

---

### `stele_memory_add`

Add a memory record. Every memory **must** cite at least one `source_refs` entry (a `stele://` URI). This is enforced by the facade; passing an empty list yields `{"error": {"code": "VALIDATION", ...}}`.

| Input | Type | Required | Default | Notes |
|---|---|---|---|---|
| `text` | string | ✅ | — | The fact to remember. |
| `source_refs` | array of strings | ✅ | — | One or more `stele://` URIs. Must be non-empty. |
| `kind` | string | | `"fact"` | Memory kind (`fact`, `preference`, `decision`, `instruction`, etc.). |
| `namespace` | string | | `"default"` | Maps to a `MemoryScope`. |
| `supersedes` | array of strings | | — | Memory IDs this record replaces. Use for fact updates. |
| `confidence` | number | | `1.0` | 0.0–1.0. |
| `metadata` | object | | — | Free-form. |

**Response:**
```json
{
  "memory_id": "01J7C9Q2H...",
  "duplicate_of": null,
  "superseded_ids": []
}
```

If the same `(text, scope)` is added twice, `duplicate_of` returns the existing record's id and `memory_id` may be the duplicate. If `supersedes=[...]` was passed, `superseded_ids` echoes back what was superseded.

**Example — superseding:**
```json
// Original
{"name": "stele_memory_add", "arguments": {
  "text": "Project uses Postgres 15",
  "source_refs": ["stele://default/abc"],
  "kind": "fact"
}}
// later: project upgraded
{"name": "stele_memory_add", "arguments": {
  "text": "Project uses Postgres 17",
  "source_refs": ["stele://default/def"],
  "kind": "fact",
  "supersedes": ["01J7C9Q2H..."]
}}
```

---

### `stele_memory_get`

Fetch a single memory by id.

| Input | Type | Required |
|---|---|---|
| `memory_id` | string | ✅ |

**Response:** `{"record": <MemoryRecord>}` or `{"error": {...}}`.

---

### `stele_memory_search`

Search memory text with optional time-travel.

| Input | Type | Required | Default |
|---|---|---|---|
| `query` | string | ✅ | — |
| `namespace` | string | | `"default"` |
| `as_of` | string (ISO 8601) | | now |
| `limit` | int | | `10` |
| `include_superseded` | bool | | `false` |

**Example — time travel:**
```json
{"name": "stele_memory_search", "arguments": {
  "query": "Postgres version",
  "as_of": "2026-05-01T00:00:00Z"
}}
```
Returns what memory said about Postgres versions on 2026-05-01 — even if a newer superseding record exists today.

**Response:** `{"hits": [<MemoryRecord>, ...]}`

---

### `stele_memory_list`

Enumerate memory records.

| Input | Type | Required | Default |
|---|---|---|---|
| `namespace` | string | | `"default"` |
| `as_of` | string (ISO 8601) | | now |
| `limit` | int | | `100` |
| `status_filter` | array of strings | | (all) |

`status_filter` accepts memory lifecycle states (e.g., `["active", "superseded", "retracted"]`).

---

### `stele_memory_update`

Update **metadata** of a memory record. **Text changes are rejected**; use `stele_memory_add(supersedes=[...])` instead.

| Input | Type | Required |
|---|---|---|
| `memory_id` | string | ✅ |
| `metadata` | object | |

**Response:** `{"record": <MemoryRecord>}`

---

### `stele_memory_delete`

Soft-delete a memory record. Prefer `stele_memory_retract` if you need an audit trail of *why*.

| Input | Type | Required |
|---|---|---|
| `memory_id` | string | ✅ |

**Response:** `{"ok": true}`

---

### `stele_memory_retract`

Retract a memory with a reason. The record stays queryable with `include_superseded=true` and `as_of=<past>`, but is excluded from default searches.

| Input | Type | Required |
|---|---|---|
| `memory_id` | string | ✅ |
| `reason` | string | ✅ |

**Response:** `{"record": <MemoryRecord>}` with status field updated.

---

### `stele_extract_from_text`

Run deterministic extraction on free text. The handler commits the extracted candidates via `memory.add` automatically; the response describes what was extracted.

| Input | Type | Required | Default |
|---|---|---|---|
| `text` | string | ✅ | — |
| `source_refs` | array of strings | ✅ | — |
| `namespace` | string | | `"default"` |

**Response:** `{"report": <ExtractionReport>}`

---

### `stele_extract_from_messages`

Extract from a list of chat messages.

| Input | Type | Required | Default |
|---|---|---|---|
| `messages` | array of objects | ✅ | — |
| `namespace` | string | | `"default"` |

Each message object should follow the OpenAI message shape (`{"role": "user", "content": "..."}`).

**Note:** Unlike `extract_from_text`, this tool does NOT take `source_refs` — extraction derives them from message provenance.

---

### `stele_extract_from_artifact`

Extract from a stored artifact.

| Input | Type | Required | Default |
|---|---|---|---|
| `ref` | string | ✅ | — |
| `namespace` | string | | `"default"` |

The handler strips the `stele://<ns>/` prefix and passes the bare `artifact_id` to the facade.

---

### `stele_recall`

The high-level "answer this question from memory + artifacts" tool. Runs a recall *strategy* — the policy that decides what to search and how to combine.

| Input | Type | Required | Default |
|---|---|---|---|
| `query` | string | ✅ | — |
| `namespace` | string | | `"default"` |
| `strategy` | string | | config default |
| `as_of` | string (ISO 8601) | | now |
| `version_filter` | string | | — |
| `retracted_behavior` | string | | `"exclude"` |
| `max_memory_hits` | int | | strategy default |
| `max_artifact_hits` | int | | strategy default |

**Strategies** (from `Stele.recall`):
- `summary_only` — just summaries, no fetch.
- `memory_search` — only memory.
- `artifact_search` — only artifacts.
- `adaptive` — deterministic escalation (memory → artifacts → both).
- `raw_fetch` — fetch by ref directly.
- `abstain` — return no answer (testing).
- `graph_search` — Phase 5 pg-raggraph (requires `postgres-graph` extra).

**Response:** `{"response": <RecallResponse>}` with `hits`, `strategy_used`, `evidence_refs`.

---

### `stele_stash_tool_result`

Route a tool's raw output through stele's interception. If the output exceeds the interception threshold, store it and return a `stele://` ref + summary. Otherwise passthrough.

| Input | Type | Required | Default |
|---|---|---|---|
| `tool_name` | string | ✅ | — |
| `raw_output` | string | ✅ | — |
| `namespace` | string | | `"default"` |
| `metadata` | object | | — |

**Response:** `{"result": <StashedResult>}` — contains either the original output (passthrough) or a `{"ref": ..., "summary": ...}` shape.

**Typical agent loop:**
```
1. agent runs Bash("git log --all --since='2023')
2. agent sees output is >4096 tokens
3. agent calls stele_stash_tool_result(tool_name="Bash", raw_output=<huge>)
4. stele returns {"ref": "stele://default/xyz", "summary": "1,247 commits..."}
5. agent uses the summary in working context; can stele_fetch(xyz) on demand
```

---

## Lifecycle + bulk-write tools (added 2026-05-20)

The following five tools were added on top of the original 18-tool surface as part of the 2026-05-20 hardening wave. Same `bind_handlers()` engine; same JSON shapes via CLI.

> Three further tools shipped after this wave, bringing the surface to **26**:
> `stele_distill` (composed cross-kind memory views), `stele_read_bounded`
> (bounded code reads), and `stele_memory_find_precedent` (supersession-candidate
> lookup). Their schemas are in [§ Newer tools](#newer-tools) below.

### `stele_purge_namespace`

GDPR-style purge of a namespace across artifact storage + memory rows + chunk index + revisor projection.

```json
{
  "namespace": "tenant-a",
  "confirm": true,
  "dry_run": false
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `namespace` | string | yes | Namespace to purge. Other namespaces are never touched. |
| `confirm` | bool | required for live purge | Tool refuses unless `true`; pair with the agent's tool-call confirmation UX. |
| `dry_run` | bool | no | When `true`, returns the same `PurgeReport` shape with counts that *would* be deleted. No mutation. |

Returns `{result: {namespace, dry_run, artifacts, memories, chunks, graph_evidence}}`.

### `stele_export_namespace`

Write a portable v2 JSONL bundle (artifacts + memory rows with their supersession chain) to `path`. Path must be within the host's allowed filesystem scope.

```json
{"namespace": "tenant-a", "path": "/data/exports/tenant-a.jsonl"}
```

Returns `{result: {exported_count, path}}`. Chunks and revisor projections are NOT bundled — they rebuild on import.

### `stele_import_namespace`

Restore a v2 JSONL bundle previously written by `stele_export_namespace`.

```json
{"path": "/data/exports/tenant-a.jsonl"}
```

Returns `{result: {imported_count}}`. Artifacts re-route through the indexer (chunks rebuild). Memory rows insert byte-identical with `status`/`supersedes`/`effective_until` preserved.

### `stele_store_many`

Bulk-write N artifacts in one transaction. ~10× postgres speedup at N=1000 vs per-row.

```json
{
  "items": [
    {"content": "alpha", "namespace": "bulk"},
    {"content": "beta", "namespace": "bulk", "session_id": "s1"},
    {"content": "gamma", "namespace": "bulk", "metadata": {"tag": "x"}}
  ]
}
```

Each item mirrors the per-row `stele_store` kwargs (`content`, `namespace`, `session_id`, `content_type`, `metadata`, `lifecycle`, `ttl_seconds`). Returns `{results: [StoredResult, ...]}` in input order.

### `stele_memory_add_many`

Bulk-write N memory rows in one transaction.

```json
{
  "items": [
    {
      "text": "user prefers Helix",
      "kind": "preference",
      "source_refs": ["stele://default/abc"],
      "scope": {"namespace": "default", "user_id": "u1"}
    }
  ]
}
```

Each item mirrors the per-row `stele_memory_add` kwargs with `scope` as a nested object. Per-row supersession works inside a batch via the `supersedes` field. Returns `{results: [MemoryAddResult, ...]}`.

---

## Newer tools

The three tools added after the lifecycle wave.

### `stele_read_bounded`

Dependency-aware bounded read of a code file: the requested symbol or line range plus the definitions it references, a signature outline of the rest, and expansion handles — instead of the whole file.

```json
{"source": "stele://repo/abc123", "want": "parse_config", "language": "python", "max_chars": 2000}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `source` | string | yes | A `stele://` ref (artifact is fetched), a file path (language inferred from extension), or raw source. |
| `want` | string | yes | A symbol name (e.g. `parse_config`) or a `start-end` line range (e.g. `40-72`). |
| `language` | string | no | Override when `source` is raw or the extension is ambiguous. |
| `max_chars` | integer | no | Output budget; omitted = adaptive by file size. The full file stays available via `stele_fetch`. |

Returns the layered bounded view as text. Escalation handles in the view resolve to real bytes via `stele_fetch`.

### `stele_distill`

Distill a memory mode into a structured `DistilledView`.

```json
{"mode": "facts", "namespace": "tenant-a"}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `mode` | string | yes | One of `facts`, `precedents`, `state`, `skills`, `best_practices`, `rules`, `episodes`, `timeline`, `spans`. Unknown mode returns a `VALIDATION` error. |
| `namespace` | string | no | Scopes the distillation. |

Returns `{view: <DistilledView>}`. Note: `skills` / `best_practices` / `rules` degrade to empty without an LLM configured; `spans` needs an embedder.

### `stele_memory_find_precedent`

Active memories in a scope whose metadata contains all the given pairs — the supersession-candidate lookup. A new memory whose identifying attributes are `match` should supersede what this returns.

```json
{"match": {"subject": "deploy_day", "predicate": "is"}, "namespace": "tenant-a", "kind": "fact", "limit": 1000}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `match` | object | yes | Metadata key/value pairs; a record matches when its `metadata` contains all of them. |
| `namespace` | string | no | Scopes the lookup. |
| `kind` | string | no | Restrict to one memory kind (e.g. `fact`). |
| `limit` | integer | no | Max active records scanned (default 1000). |

Returns `{records: [MemoryRecord, ...]}` — only active records (superseded ones are never precedents).

---

## Drift from spec

The spec at `docs/archive/superpowers/specs/2026-05-20-stele-multiplatform-packaging-design.md` §4.1 lists 18 tool *names* that match the implementation, but the schemas described there are simpler than the real handlers. The differences are deliberate, not accidental:

| Spec said | Real handler does | Why |
|---|---|---|
| `stele_memory_add(text, source_refs, supersedes, metadata)` | Adds `kind`, `namespace`, `confidence` | The `Stele.memory.add` facade requires `kind` and `scope` (a `MemoryScope`); we surface `namespace` as a friendly string and synthesize the scope. `confidence` is optional but useful. |
| `stele_recall(query, strategy, as_of, version_filter, retracted_behavior)` | Adds `namespace`, `max_memory_hits`, `max_artifact_hits` | Same scope concern; the hit caps were already on the underlying `RecallRequest`. |
| `stele_memory_search/list` no `namespace` | Adds `namespace` | Memory queries are scope-bound; the spec was wrong. |
| `stele_extract_from_messages` takes `source_refs` | Does NOT take `source_refs` | The underlying facade derives source refs from message provenance; passing them would be silently discarded. Removed. |
| `stele_store(content_type)` accepts free strings | Accepts only the `ContentType` Literal | The facade rejects MIME-style strings; spec wording suggested otherwise. Documented above. |
| `stele_search(query, ...)` | Requires `ref` first | `Stele.search` is artifact-scoped; cross-artifact lookup is `stele_query`. |

The spec doc has been updated to point readers here as the source of truth.
