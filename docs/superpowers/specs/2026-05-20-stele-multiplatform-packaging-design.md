# Stele Multi-Platform Packaging — Design Spec

**Status:** Approved 2026-05-20 (brainstorming session, Approach A — channel-per-concern, single-source-of-truth). Implementation complete on `feat/multiplatform-packaging`; §4.1 was retroactively reconciled with the real `bind_handlers` signatures after the facade probe revealed `MemoryScope`/`ContentType`/etc. constraints the original draft missed. **The ground-truth tool reference is [`docs/mcp-tools.md`](../../mcp-tools.md)** — this spec describes intent and shape; that doc describes wire reality.
**Author:** brainstorming session driven by The Yonk.
**Roadmap slot:** Independent of Phase 6/7 critical path. This work is structurally a candidate to become the first concrete adapter for Phase 7 (Adapter SDK + Runtime Capture), but does NOT block on T-RAM-005..008 scaffolding. If Phase 7 lands first, the MCP server gets retrofitted to use the adapter contract; if this lands first, Phase 7 absorbs the lessons. Either order is fine.
**Background:** Competitive research (`skill-output/research-and-design/Research-Report-graphify-vs-stele.md`) identified packaging/distribution as stele's primary gap vs. graphify's 49.7k-star slash-skill play. This spec defines how stele closes that gap without copying graphify's pitfalls.

---

## 1. Purpose

Ship `stele-core` with a multi-platform packaging story so that any LLM agent supporting MCP, slash-skills, or shared-context-doc patterns can pick up stele's full read/write surface (artifact storage, evolving memory, recall, extraction, interception) in one install. Match graphify's distribution shape (14 platforms via one config dict) while keeping stele's evidence-cited semantics and avoiding graphify's known maintenance traps (duplicated skill files, CLI/MCP code drift, swallowed errors).

## 2. Scope

### In Scope
- A `stele-mcp` stdio MCP server exposing the full public facade (`store`, `fetch`, `search`, `query`, `list`, `delete`, `memory.*`, `extract.*`, `recall`, plus interception's `stash_tool_result`).
- A `stele` CLI exposing `init`, `install`, `uninstall`, `status`, `doctor`, `mcp`.
- A single Jinja2 skill template + per-platform render adapters.
- Per-platform hook templates where the platform supports it (Claude Code, Gemini, OpenCode).
- A `.stele/config.yaml` project-level config schema (DSN, signing mode, defaults).
- Idempotent section insertion into `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`.
- Multi-platform routing table covering: Claude Code, Codex, OpenCode, Cursor, Gemini CLI, Copilot, Aider — exactly seven at launch. Additional platforms are one dict entry each.

### Out of Scope
- Network-exposed MCP transports (SSE, streamable-HTTP). Stdio only in v1; deferred.
- Authentication / authorization. v1 assumes local-trusted execution boundary.
- A browser UI / hosted dashboard. (Graphify Labs territory; not stele's.)
- Multimodal corpus ingestion (PDFs, images, video) — graphify's lane, deliberately not entered.
- A `stele-agent-pack` split package (Approach B) — reserved as a future refactor.

## 3. Constraints

### ALWAYS
- The MCP server is the **single source of truth** for tool semantics. The CLI invokes the same facade methods in-process; it does not re-implement search, recall, or memory logic.
- Every skill / hook / shared-doc section is rendered from a **single Jinja2 template** with platform-specific data, not from per-platform hand-maintained files.
- Errors are returned to MCP callers as **structured JSON** (`{"error": {"code": str, "message": str, "context": {...}}}`) — never swallowed, never collapsed to "Error executing X".
- Every install/uninstall mutation of shared docs (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) uses the **marker + next-H2** idempotent-section pattern. User-authored content between sections is preserved.
- The full public facade surface stays SDK-public; the MCP server is a **transport layer**, not an API redefinition.
- All structured-output fields derived from LLM or external content are **sanitized through `pii.scrubber`** before crossing the MCP boundary, identically to other model-visible surfaces.

### ASK FIRST
- Adding a new MCP tool that is not a 1:1 wrapper over an existing facade method.
- Adding a platform that requires a non-stdio transport or a write to a directory outside the platform's documented skill/hook location.
- Bumping the project-level config schema (`.stele/config.yaml`) in a backwards-incompatible way.

### NEVER
- Duplicate skill content across platforms. One template, N renderings.
- Re-implement facade logic in either the MCP server or the CLI. Both wrap the same `Stele` instance.
- Ship a hook that blocks tool execution. Hooks are reminders only; they print to stderr and exit 0.
- Embed credentials, signing keys, or DSNs in any template, manifest, or shared-doc section. Project config carries those; templates carry only path placeholders.
- Swallow exceptions in MCP tool handlers. Catch, log to stderr, return structured-error JSON, re-raise on truly-fatal errors.

## 4. Architecture — Six Channels

Each channel has exactly one source of truth and one update path.

```
┌──────────────────────────────────────────────────────────────────┐
│                       Stele Facade (existing)                     │
│ Stele.{store,fetch,search,query,list,delete,memory,extract,recall}│
└──────────────────────────────────────────────────────────────────┘
            ▲                                       ▲
            │ in-process                            │ in-process
            │                                       │
┌───────────┴───────────┐                ┌──────────┴─────────────┐
│  stele-mcp (stdio)    │                │  stele CLI             │
│  src/stele/mcp/       │                │  src/stele/cli/        │
│  - server.py          │                │  - __init__.py         │
│  - tools.py           │                │  - commands/init.py    │
│  - errors.py          │                │  - commands/install.py │
│  - sanitize.py        │                │  - commands/doctor.py  │
└───────────────────────┘                └────────────────────────┘
                                                    │ writes
                                                    ▼
┌──────────────────────────────────────────────────────────────────┐
│           src/stele/packaging/                                    │
│ - platforms.py        : PLATFORM_CONFIG dict (7 entries at launch)│
│ - render.py           : Jinja2 environment + helpers              │
│ - install.py          : per-platform install/uninstall actions    │
│ - sections.py         : idempotent shared-doc section editor      │
│ - templates/                                                      │
│   - skill.md.j2       : ONE skill template, all platforms         │
│   - hooks/                                                        │
│     - claude-code.sh.j2                                           │
│     - gemini-settings.json.j2                                     │
│     - opencode-plugin.js.j2                                       │
│   - agents-md-section.md.j2                                       │
│   - mcp-server-config.json.j2                                     │
│ - version_stamps.py   : per-platform .stele_version stamp sync    │
└──────────────────────────────────────────────────────────────────┘
```

### 4.1 MCP Server (`src/stele/mcp/`)

- **Library:** `mcp` (Python). Stdio transport only in v1. (Matches graphify; widest ecosystem support.)
- **Tool registration:** declarative — each tool is a `ToolSpec` dataclass with `name`, `description`, `input_schema` (JSON Schema dict), `handler` (callable). Registered in `tools.py:TOOLS: list[ToolSpec]`. The `@server.list_tools()` and `@server.call_tool()` handlers iterate this list. No decorator magic; the list is greppable.
- **Tool surface (v1, full read/write — see [`docs/mcp-tools.md`](../../mcp-tools.md) for the ground-truth reference; signatures below are the post-implementation reality, not the original draft):**
  - `stele_store(payload, content_type=None, namespace=None, metadata=None) -> {ref}` — wraps `Stele.store`. `content_type` is the `ContentType` Literal enum (`text` / `json` / `markdown` / `code` / `code_diff` / `csv` / `sql` / `log` / `html` / `table` / `blob`), NOT a MIME string.
  - `stele_fetch(ref) -> {content, content_type, scrubbed, pii, byte_size}` — wraps `Stele.fetch`. `PIIBlockedError` → `error.code = "PII_BLOCKED"`.
  - `stele_search(ref, query, mode=None, limit=10) -> {hits}` — wraps `Stele.search`. `ref` is required because search is artifact-scoped; cross-artifact queries use `stele_query`.
  - `stele_query(query, namespace="default", mode=None, limit=10) -> {hits}` — wraps `Stele.query` across a namespace's chunk index.
  - `stele_list(namespace=None, limit=100) -> {page}` — wraps `Stele.list`; returns a `Page` shape.
  - `stele_delete(ref) -> {ok}` — wraps `Stele.delete`; `ok` reflects whether the artifact existed.
  - `stele_memory_add(text, source_refs, kind="fact", namespace="default", supersedes=None, confidence=1.0, metadata=None) -> {memory_id, duplicate_of, superseded_ids}` — `namespace` synthesized into a `MemoryScope`; `kind` and `confidence` surface facade fields.
  - `stele_memory_get(memory_id) -> {record}`
  - `stele_memory_search(query, namespace="default", as_of=None, limit=10, include_superseded=False) -> {hits}` — `as_of` is ISO-8601; handler parses to `datetime`.
  - `stele_memory_list(namespace="default", as_of=None, limit=100, status_filter=None) -> {records}`
  - `stele_memory_update(memory_id, metadata=None) -> {record}` (text changes rejected per facade)
  - `stele_memory_delete(memory_id) -> {ok}`
  - `stele_memory_retract(memory_id, reason) -> {record}` (Phase 5; `record.status` becomes `retracted`)
  - `stele_extract_from_text(text, source_refs, namespace="default") -> {report}`
  - `stele_extract_from_messages(messages, namespace="default") -> {report}` — NOT `source_refs`; the facade derives provenance from message order.
  - `stele_extract_from_artifact(ref, namespace="default") -> {report}` — accepts full `stele://` ref; the facade was patched in fe9284f to parse the embedded namespace correctly.
  - `stele_recall(query, namespace="default", strategy=None, as_of=None, version_filter=None, retracted_behavior=None, max_memory_hits=None, max_artifact_hits=None) -> {response}` — strategies: `summary_only`, `memory_search`, `artifact_search`, `adaptive`, `raw_fetch`, `abstain`, `graph_search` (Phase 5).
  - `stele_stash_tool_result(tool_name, raw_output, namespace="default", metadata=None) -> {result}` — wraps `interception.wrapper.stash_tool_result`. The threshold is configured globally (`mcp.stash_threshold_tokens` in `.stele/config.yaml`); per-call override is not surfaced.
- **Output handling:**
  - All free-text fields pass through `mcp.sanitize.sanitize_label()` (ANSI-strip + C0/`\x7f` control-char strip + 256-char clamp) before serialization. PII scrubbing is inherited from the facade and never re-applied. Token-budget truncation with actionable hints is deferred — not implemented in v1.
- **Errors:** All exceptions reach a single `handle_exception(exc) -> McpError` boundary in `mcp/errors.py`. Map known stele exceptions to stable codes: `ConfigError → CONFIG`, `PIIBlockedError → PII_BLOCKED`, `CapabilityError → CAPABILITY`, `ValidationError → VALIDATION`, all others → `INTERNAL` with traceback to stderr. Never swallow.
- **Config plumbing:** server boots from `.stele/config.yaml` resolved by walking up from CWD; falls back to `~/.config/stele/config.yaml`; can be overridden by `--config <path>`. DSN never read from env at this layer — config carries it.
- **Hot-reload:** out of scope for v1 (the facade is in-process; config changes require restart, which an MCP host can do on its own).

### 4.2 CLI (`src/stele/cli/`)

Exposes one binary, `stele`, registered as `[project.scripts] stele = "stele.cli:main"`.

Commands:
- `stele init [--backend sqlite|memory|postgres|...] [--dsn URL]` — writes `.stele/config.yaml` with sensible defaults (sqlite at `.stele/stele.db` if no flag). Idempotent: re-running prompts before overwriting.
- `stele install --platform <name> [--platforms <name,name,...>] [--all]` — renders skill + hook + shared-doc-section for one or more platforms; refreshes all platforms' version stamps (graphify's pattern, retained).
- `stele uninstall --platform <name> [--all]` — removes skill files, hook files, version stamps, and the marker-delimited section from shared docs.
- `stele status` — prints per-platform install state, MCP server reachability, config validity.
- `stele doctor` — runs config validation, backend reachability check, signing-mode sanity check. Returns exit 0/1.
- `stele mcp [--config <path>]` — starts the stdio MCP server in the foreground. (Mirrors what `[project.scripts] stele-mcp` does; the alias is for users who prefer one binary.)

All CLI commands construct a single `Stele(...)` instance from `.stele/config.yaml` and call facade methods. No re-implementation.

### 4.3 Packaging templates (`src/stele/packaging/`)

`platforms.py:PLATFORM_CONFIG` is the routing table:

```python
PLATFORM_CONFIG: dict[str, PlatformSpec] = {
    "claude-code": PlatformSpec(
        skill_path="~/.claude/skills/stele/SKILL.md",
        agents_doc="~/.claude/CLAUDE.md",
        project_agents_doc="CLAUDE.md",
        hook_template="hooks/claude-code.sh.j2",
        hook_path="~/.claude/hooks/stele-large-output.sh",
        mcp_config_path="~/.claude/mcp.json",   # if absent, instruct via stderr
    ),
    "codex": PlatformSpec(...),
    "opencode": PlatformSpec(...),
    "cursor": PlatformSpec(...),
    "gemini-cli": PlatformSpec(...),
    "copilot": PlatformSpec(...),
    "aider": PlatformSpec(...),
}
```

`render.py` is a thin Jinja2 wrapper exposing `render_skill(platform: str) -> str`, `render_hook(platform: str) -> str | None`, `render_agents_md_section(platform: str) -> str`. Templates live under `templates/`. One source of truth per content type.

`sections.py` implements the marker + next-H2 idempotent-section pattern (graphify's `__main__.py:166-208`, kept). Tested separately.

`version_stamps.py` writes `.stele_version` per platform and refreshes all platforms' stamps on any install (graphify's pattern, kept — avoids "your codex skill is stale" noise after you only re-installed Claude Code).

### 4.4 Skill template (`templates/skill.md.j2`)

The skill is a **reference card**, not a procedural runbook. It tells the agent **when** to use which MCP tool — not what bash to run.

```markdown
---
name: stele
description: {{ description }}
trigger: {{ trigger }}
---

# /stele

You have access to the `stele` MCP tool surface for evidence-cited memory and artifact storage.

## When to use

- Tool output >{{ stash_threshold }} tokens: call `stele_stash_tool_result` to swap the output for a `stele://` reference + summary.
- User asks something needing prior context: call `stele_memory_search` before responding.
- A claim depends on a specific artifact: call `stele_fetch` on its `stele://` ref; never paraphrase from memory alone.
- A previously-stated fact has changed: call `stele_memory_add` with `supersedes=[<old_id>]` — never edit in place.
- A claim was wrong and must be retracted: call `stele_memory_retract`. Don't delete; retract leaves the audit trail.

## Tool reference

{{ tool_reference_table }}
<!-- rendered from src/stele/mcp/tools.py:TOOLS — one row per ToolSpec
     with columns: name, one-line purpose, key inputs. Single source of
     truth: editing TOOLS regenerates the reference for every platform. -->


## Notes

- Every memory cites its evidence (`source_refs` = list of `stele://` URIs). The MCP server enforces this.
- PII scrubbing is on by default. Raw artifact bytes require `pii.raw_fetch_enabled=true` in `.stele/config.yaml`.
- Time-travel: pass `as_of=<ISO datetime>` to `stele_memory_search` / `stele_memory_list` / `stele_recall`.
```

Per platform, only `description`, `trigger`, `stash_threshold`, and `tool_reference_table` change. Everything else renders identically.

### 4.5 Hooks and rules-files (`templates/hooks/`)

Opt-in agent-side nudges. Three platforms get native hooks at launch; two get rules-file equivalents; two get no nudge surface (skill content alone carries the instruction).

| Platform | Mechanism | Template |
|---|---|---|
| Claude Code | Bash hook on `Bash`/`Read` large output | `hooks/claude-code.sh.j2` |
| Gemini CLI | BeforeTool entry in `.gemini/settings.json` | `hooks/gemini-settings.json.j2` |
| OpenCode | `tool.execute.before` JS plugin | `hooks/opencode-plugin.js.j2` |
| Cursor | `.cursor/rules/stele.mdc` with `alwaysApply: true` | `hooks/cursor-rules.mdc.j2` |
| Codex | `AGENTS.md` section only (no native hook) | — |
| Copilot | Skill content only | — |
| Aider | Skill content only | — |

Hooks NEVER block. They print to stderr, return exit 0 / `return undefined`. Graphify's pitfall #3 (gating-via-hooks) explicitly avoided.

Rules-files (Cursor) carry the same nudge text as hooks but execute via the platform's prompt-injection mechanism rather than a tool callback.

### 4.6 Project config schema (`.stele/config.yaml`)

```yaml
# .stele/config.yaml — generated by `stele init`
backend:
  type: sqlite            # memory | sqlite | postgres | mariadb | clickhouse
  dsn: .stele/stele.db    # type-specific; not required for memory/sqlite-default
pii:
  raw_fetch_enabled: false
  scrub_summary: true
signing:
  mode: optional          # off | optional | required
  # secret: loaded from env var STELE_SIGNING_SECRET — never written here
indexing:
  mode: sync              # skip | sync | async
retrieval:
  default_mode: hybrid    # text | vector | hybrid
mcp:
  stash_threshold_tokens: 4096
```

Schema validated by a Pydantic model in `src/stele/cli/config.py`. Re-uses the existing `core.config` Pydantic models where possible; the wrapper exists so the CLI's error messages can point at `.stele/config.yaml` lines rather than at internal model names.

## 5. Data Flow

### Install flow
1. `stele install --platform claude-code` runs.
2. `packaging.install.install_for("claude-code")` looks up `PLATFORM_CONFIG["claude-code"]`.
3. `render.render_skill("claude-code")` produces SKILL.md content.
4. File written to `~/.claude/skills/stele/SKILL.md` (creating parents).
5. `render.render_hook("claude-code")` produces hook content; written to hook path.
6. `sections.upsert("CLAUDE.md", marker="## stele", content=render_agents_md_section(...))` injects/replaces the stele section in user-global `CLAUDE.md`.
7. MCP server entry written/merged into `~/.claude/mcp.json` (if path exists; otherwise stderr instructs how to add it).
8. `.stele_version` stamp written to skill dir.
9. `version_stamps.refresh_all()` updates stamps for every other platform that's already installed.
10. Print success + next-step hint ("type `/stele` in Claude Code to verify").

### Runtime flow (agent calling MCP)
1. Agent runs a Bash tool with output >threshold.
2. Hook (if installed) prints to stderr reminding the agent.
3. Agent calls `stele_stash_tool_result(tool_name="Bash", raw_output="...")`.
4. MCP server's tool handler dispatches to `stele.interception.stash_tool_result(...)`.
5. Returns `{"ref": "stele://default/abc123", "summary": "..."}`.
6. Agent uses the summary in its response; can later call `stele_fetch("stele://default/abc123")` to get full bytes.

### Uninstall flow
1. `stele uninstall --platform claude-code` runs.
2. Skill file, hook file, version stamp deleted.
3. `sections.remove("CLAUDE.md", marker="## stele")` strips the section, preserving everything else.
4. MCP server entry removed from `~/.claude/mcp.json` if present.

## 6. Error Handling

- Every MCP tool handler is wrapped by `mcp.errors.guard()` — a single decorator that catches exceptions, maps known types to error codes (table in §4.1), logs unmapped exceptions with traceback to stderr, and returns the structured error JSON.
- CLI commands use the same error mapping for non-zero exits; `stele doctor` exposes the same codes for scripted health-checks.
- `sections.upsert` and `sections.remove` are transactional: if the regex match is ambiguous (multiple markers found, indicating prior corruption), they refuse to act and print the conflict — no silent overwrite.

## 7. Testing

### Unit
- `tests/unit/mcp/test_errors.py` — every known exception type maps to its documented code.
- `tests/unit/mcp/test_tools.py` — for each `ToolSpec`, input schema validates known-good input and rejects known-bad input. Handler invocation goes through a mock `Stele` instance.
- `tests/unit/mcp/test_sanitize.py` — ANSI/control-char strip + 256-char clamp. Prompt-injection payloads in label fields are neutralized.
- `tests/unit/packaging/test_render.py` — every platform in `PLATFORM_CONFIG` renders without error; rendered content contains required markers.
- `tests/unit/packaging/test_sections.py` — upsert/remove idempotency, marker conflict refusal, preservation of unrelated content.
- `tests/unit/packaging/test_version_stamps.py` — refresh-all-on-any-install behavior.
- `tests/unit/cli/test_init.py`, `test_install.py`, `test_uninstall.py`, `test_doctor.py` — using a tmp HOME for filesystem isolation.

### Contract
- `tests/contract/test_mcp_contract.py` — parametrized across `BACKENDS` (memory + sqlite default; pg/mariadb/clickhouse when env vars set). For each backend, the full MCP tool surface is exercised over a real stdio pipe with a real `Stele` instance. Asserts response shape, error mapping, sanitization.

### Integration
- `tests/integration/test_install_e2e.py` — installs to a tmp HOME for each platform in `PLATFORM_CONFIG`, then uninstalls. Asserts no leftover files, no shared-doc corruption.

### Manual smoke (one-time, documented in `docs/packaging-smoke-checklist.md`)
- Real Claude Code session, real `/stele` invocation, real MCP round-trip end-to-end on the maintainer's machine. Not part of CI.

## 8. Success Criteria

- **SC-001:** `pip install stele-core` exposes both `stele` and `stele-mcp` console scripts.
- **SC-002:** `stele init` produces a working `.stele/config.yaml` with `backend.type=sqlite` by default; `stele doctor` exits 0 immediately after.
- **SC-003:** For each of the seven launch platforms, `stele install --platform <name>` writes the skill, hook (if applicable), and shared-doc section without manual intervention. `stele uninstall --platform <name>` reverses it cleanly.
- **SC-004:** The MCP server exposes all 18 tools enumerated in §4.1 (6 artifact + 7 memory + 3 extract + 1 recall + 1 stash). Each tool's input schema validates correctly and the handler dispatches to the matching facade method.
- **SC-005:** Every known stele exception maps to a stable MCP error code; unmapped exceptions return `INTERNAL` with traceback on stderr (verified by `tests/unit/mcp/test_errors.py`).
- **SC-006:** All free-text fields crossing the MCP boundary are PII-scrubbed and label-sanitized (verified by `tests/unit/mcp/test_sanitize.py`).
- **SC-007:** Skill content is rendered from one Jinja template; changing the template's body propagates to every platform's rendered skill (verified by `tests/unit/packaging/test_render.py`).
- **SC-008:** Shared-doc section upsert/remove is idempotent and preserves unrelated content (verified by `tests/unit/packaging/test_sections.py`).
- **SC-009:** End-to-end install/uninstall cycle leaves zero leftover files across all seven platforms (verified by `tests/integration/test_install_e2e.py`).
- **SC-010:** Full MCP contract suite passes on memory + sqlite by default, and on postgres/mariadb/clickhouse when their DSN env vars are set.

## 9. Drift Checkpoints

- **DC-A — After CLI scaffold:** confirm `stele init` writes valid config that `stele doctor` validates. No MCP work yet.
- **DC-B — After MCP server scaffold:** confirm `stele mcp` starts, lists tools, and a single round-trip to `stele_store` + `stele_fetch` works against the memory backend.
- **DC-C — After packaging templates:** confirm Claude Code install (only) renders skill + hook + CLAUDE.md section without touching other platforms' paths.
- **DC-D — After all seven platforms:** confirm `stele install --all` and `stele uninstall --all` are clean across a tmp HOME.
- **DC-FINAL:** all SC-XXX have evidence in tests; `ruff` + `mypy --strict` + `pytest` clean; manual smoke on real Claude Code green.

## 10. Open Questions

None at design time. Two deferred decisions:
1. When SSE/streamable-HTTP transport is added (post-v1), the auth model gets revisited. The stdio assumption is documented in `docs/packaging-auth-model.md` so the deferred decision has a clean handoff.
2. The eighth+ platform list (Antigravity, Kiro, Trae, Droid, Pi, Kimi, etc., the rest of graphify's 14) is deferred to a follow-up — add one PR per platform.

## 11. References

- Research: `skill-output/research-and-design/Research-Report-graphify-vs-stele.md`
- Decision context: `skill-output/research-and-design/Research-Summary-graphify-vs-stele.md`
- Adjacent roadmap: `docs/superpowers/2026-05-17-order-of-operations.md` (this work feeds Phase 7's Adapter SDK)
- Graphify code patterns deep-dive: agent report from 2026-05-20 session (saved inline in conversation history; key citations: `serve.py:247-298` truncation, `__main__.py:82-163` PLATFORM_CONFIG, `__main__.py:166-208` idempotent section editor, `security.py:227-242` sanitization).
