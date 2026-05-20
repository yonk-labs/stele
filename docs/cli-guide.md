# Stele CLI Guide

The `stele` binary is installed by `pip install stele-core` and exposes **two groups** of subcommands. The companion `stele-mcp` binary runs the MCP server (same code path as `stele mcp`).

**Operator subcommands** — setup, install, diagnostics. You'll run these once per project or once per platform.

```
stele init       Write .stele/config.yaml with sensible defaults.
stele install    Install skill + hook + MCP entry for an agent platform.
stele uninstall  Reverse a previous install.
stele status     Show per-platform install state.
stele doctor     Validate config + backend reachability.
stele mcp        Run the stdio MCP server (foreground).
```

**Data-plane subcommands** — the same 18 operations the MCP server exposes, callable from a shell. JSON in (via flags or stdin), JSON out (on stdout). Useful in scripts, pipelines, CI, and for debugging what an MCP client is actually doing.

```
stele store     Store text/bytes; emit a stele:// ref.
stele fetch     Resolve a stele:// ref to content + metadata.
stele search    Search within a single artifact.
stele query     Query the chunk index across a namespace.
stele list      List artifacts.
stele delete    Delete an artifact by ref.
stele memory    Memory operations:
                  add | get | search | list | update | delete | retract
stele extract   Extraction operations:
                  from-text | from-messages | from-artifact
stele recall    Run a recall strategy.
stele stash     Stash an oversize tool output (pipe its raw_output via stdin).
```

Global flags:

- `--pretty` — indent JSON output (can appear before or after the subcommand)
- `--namespace NS` — partition data (default `"default"`); accepted by every data-plane subcommand

See [`docs/mcp-tools.md`](mcp-tools.md) for the canonical schema of every operation; the CLI and MCP shapes are identical because both call into `bind_handlers()` over the same `Stele` instance.

## `stele init`

Writes `.stele/config.yaml` in the current directory.

```
stele init [--backend memory|sqlite|postgres|mariadb|clickhouse] [--dsn URL] [--force]
```

| Flag | Default | Notes |
|---|---|---|
| `--backend` | `sqlite` | The artifact storage backend. |
| `--dsn` | — | Override the default DSN for the chosen backend. |
| `--force` | off | Overwrite an existing config without prompting. |

**Examples:**
```bash
# Project-local sqlite (most common starting point)
stele init

# In-memory (good for ephemeral testing)
stele init --backend memory

# Real Postgres
stele init --backend postgres --dsn postgresql://user:pw@localhost:5432/stele
```

The default sqlite path is `.stele/stele.db` relative to where `stele init` ran. Other config keys (PII gate, signing mode, indexing mode, MCP threshold) get sensible defaults you can hand-edit:

```yaml
backend:
  type: sqlite
  dsn: .stele/stele.db
pii:
  raw_fetch_enabled: false
  scrub_summary: true
signing:
  mode: optional
indexing:
  mode: sync
retrieval:
  default_mode: hybrid
mcp:
  stash_threshold_tokens: 4096
```

`stele init` exits non-zero if `.stele/config.yaml` already exists, unless `--force` is passed.

### Backend-specific notes

#### Postgres

A few things that are clear from the code but not obvious until you run into them:

- **The `[postgres]` extra is required.** `stele init --backend postgres` writes the config file fine, but the backend itself raises `OptionalDependencyError` on first use without `psycopg`. Install with `pip install 'stele-core[postgres]'`. `stele doctor` pre-checks this and prints the pip command for any missing extra.
- **Schema evolution is operator-managed.** stele uses `CREATE TABLE IF NOT EXISTS` plus `ADD COLUMN IF NOT EXISTS` patches on every connection rather than a numbered migration system. New stele versions may add columns idempotently; they will not drop or rename. On a long-lived shared Postgres, treat schema changes between releases as forward-compatible-only and back up before upgrading.
- **`retrieval.default_mode: hybrid` requires the chunk index.** The Postgres artifact retrieval backend itself only supports `keyword` (vector lives in the optional chunkshop chunk index). Setting `retrieval.default_mode: hybrid` without `indexing.provider: chunkshop` + the `[chunkshop]` extra silently degrades to keyword. If you want true hybrid search on Postgres:
  ```yaml
  indexing:
    mode: sync          # or async
    provider: chunkshop
  retrieval:
    default_mode: hybrid
  ```
  And `pip install 'stele-core[chunkshop]'`.
- **Tables land in `public.` by default.** If you're sharing a Postgres database with other apps, isolate stele with a dedicated schema by appending `options=-c search_path=stele` to the DSN:
  ```
  postgresql://user:pw@host:5432/db?options=-c%20search_path%3Dstele
  ```
  You'll need to `CREATE SCHEMA stele` first; stele auto-creates tables, not schemas.

#### MariaDB / ClickHouse

- Require their respective extras: `pip install 'stele-core[mariadb]'` or `'stele-core[clickhouse]'`.
- Both support artifact storage; **memory rows are not yet implemented** on either backend — calls to `stele memory add` etc. raise `CapabilityError`. SQLite or Postgres are the supported memory backends today.

#### Memory (in-process)

- Zero deps, zero persistence. Good for tests and ephemeral CI; useless for any long-lived agent.

## `stele install` / `stele uninstall`

Install the stele skill + (optionally) a hook + an `mcp.json` entry for one or more agent platforms. Renders content from a single Jinja template per content type and writes to per-platform locations.

```
stele install   --platform NAME       | --all   [--dry-run]
stele uninstall --platform NAME       | --all
```

**Supported platforms (and where files land):**

| Platform | Skill | Hook | MCP config | Project doc |
|---|---|---|---|---|
| `claude-code` | `~/.claude/skills/stele/SKILL.md` | `~/.claude/hooks/stele-large-output.sh` | `~/.claude/mcp.json` | `CLAUDE.md` |
| `codex` | `~/.agents/skills/stele/SKILL.md` | — | `~/.agents/mcp.json` | `AGENTS.md` |
| `opencode` | `~/.config/opencode/skills/stele/SKILL.md` | `~/.config/opencode/plugins/stele.js` | `~/.config/opencode/mcp.json` | `AGENTS.md` |
| `cursor` | `~/.cursor/skills/stele/SKILL.md` | `.cursor/rules/stele.mdc` (project) | `~/.cursor/mcp.json` | — |
| `gemini-cli` | `~/.gemini/skills/stele/SKILL.md` | `~/.gemini/settings.json` | `~/.gemini/mcp.json` | `GEMINI.md` |
| `copilot` | `~/.copilot/skills/stele/SKILL.md` | — | `~/.copilot/mcp.json` | `AGENTS.md` |
| `aider` | `~/.aider/skills/stele/SKILL.md` | — | `~/.aider/mcp.json` | `AGENTS.md` |

**Examples:**
```bash
stele install --platform claude-code      # one platform
stele install --all                       # all 7
stele install --platform codex --dry-run  # check what would happen, no writes
stele uninstall --all                     # reverse
```

**Safety: `mcp.json` is merged, not overwritten.** If you already have an `mcp.json` with other tools, `stele install` adds `mcpServers.stele = {...}` and leaves everything else alone. Existing `stele` entries get updated.

**Project-doc edits are idempotent.** The `## stele` section in `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` is bounded by the marker + next H2 pattern. Re-running install replaces in place. Uninstall removes the section but preserves the rest.

**On corrupted state:** if `mcp.json` is invalid JSON or has multiple `## stele` markers, install refuses to act and surfaces an error. Inspect and fix the file, then re-run.

## `stele status`

Per-platform install state with version stamps.

```
$ stele status
Platform           Installed   Stamp
claude-code        yes         0.1.0
codex              no          —
opencode           no          —
cursor             yes         0.1.0
gemini-cli         no          —
copilot            no          —
aider              no          —
```

The "Stamp" column is the version recorded in `.stele_version` next to the skill file. `stele install` refreshes the stamp for every installed platform on any install — so you won't see drift like "claude-code: 0.1.0, codex: 0.0.9" after upgrading.

## `stele doctor`

Validates the current config and pings the backend.

```
$ stele doctor
stele doctor: ok (.stele/config.yaml) — backend=sqlite capabilities=StashCapabilities(...)
```

Exits non-zero with a specific error message on:
- No config found (run `stele init`)
- YAML parse failure
- Backend unreachable (e.g., bad DSN)
- Config rejected by Pydantic validation

Useful in CI/scripts:
```bash
stele doctor || exit 1
```

## `stele mcp` and `stele-mcp`

Both run the same stdio MCP server. Identical:
```bash
stele mcp
stele-mcp
```

You almost never run these directly — agent hosts launch the server as a child process. Use them for debugging:

```bash
# Smoke-test the protocol handshake
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  | timeout 3 stele-mcp
```

The server loads `.stele/config.yaml` via the same walk-up + user-global resolution as the CLI. If no config exists anywhere, it falls back to the in-memory backend (good for tests; useless for real agent work).

## Data-plane subcommands

The seventeen data-plane subcommands mirror the eighteen MCP tools (`stele_stash_tool_result` is exposed as `stele stash`). Every command emits JSON to stdout; structured errors are returned with a non-zero exit code so scripts can branch on success/failure.

For the canonical schema of each operation (inputs, response shape, edge cases, notes on `content_type` enum values, etc.), see [`docs/mcp-tools.md`](mcp-tools.md). The reference below is just the shell ergonomics.

### Artifact surface

```bash
# Store text from a flag or stdin
stele store --text "the team uses Postgres 17" --content-type text
echo "free-text body" | stele store --text - --content-type text

# Fetch by reference
stele fetch stele://default/abc123...

# Search within a single artifact
stele search stele://default/abc123... "query" --mode hybrid --limit 5

# Cross-artifact query against the chunk index
stele query "postgres" --namespace prod --mode hybrid

# List + delete
stele list --namespace prod --limit 50
stele delete stele://default/abc123...
```

`--content-type` is the `ContentType` literal enum (`text`, `json`, `markdown`, `code`, `code_diff`, `csv`, `sql`, `log`, `html`, `table`, `blob`), not a MIME string.

### Memory surface

```bash
stele memory add "Project uses Postgres 17" \
    --source-ref stele://default/abc123... \
    --kind fact \
    --confidence 1.0

stele memory get MEMORY_ID

stele memory search "postgres" --as-of 2026-05-01T00:00:00Z --limit 10
stele memory search "postgres" --include-superseded

stele memory list --status active --limit 50

stele memory update MEMORY_ID --metadata '{"reviewed_by":"me"}'

stele memory delete MEMORY_ID                  # soft delete
stele memory retract MEMORY_ID --reason "fact was wrong"

# Supersede a previous memory in one step
stele memory add "Project upgraded to Postgres 18" \
    --source-ref stele://default/def456... \
    --supersedes MEMORY_ID_OLD
```

### Extraction surface

```bash
stele extract from-text \
    --text "Decision: standardize on Postgres 17 as of 2026-05." \
    --source-ref stele://default/...

cat conversation.json | stele extract from-messages --input -

stele extract from-artifact stele://default/abc123...
```

`from-messages` expects a JSON array of `{"role": "...", "content": "..."}` objects, either passed via `--input FILE` or piped on stdin.

### Recall

```bash
stele recall "what postgres version are we on" \
    --strategy memory_search \
    --as-of 2026-05-15T00:00:00Z

stele recall "summarize the launch decision" \
    --strategy adaptive \
    --max-memory-hits 5 \
    --max-artifact-hits 3
```

Strategies: `summary_only` · `memory_search` · `artifact_search` · `adaptive` · `raw_fetch` · `abstain` · `graph_search` (requires the `postgres-graph` extra on a Postgres backend).

### Interception (stash)

```bash
# Pipe oversize output through the interception path
git log --all --pretty=format:"%h %s" | head -200 | stele stash Bash -

# Or pass a file:
stele stash MyTool --input /tmp/huge-output.txt
```

If the input is over the threshold (`mcp.stash_threshold_tokens` in `.stele/config.yaml`, default 4096), Stele stores the exact bytes, generates a summary via the `lede` extractive summarizer, and returns a `stele://` ref plus the summary. Below the threshold, the output passes through.

### Common patterns

**Round-trip a fact (shell):**

```bash
REF=$(stele store --text "smoke test fact" --content-type text | jq -r .ref)
MID=$(stele memory add "smoke test fact" --source-ref "$REF" | jq -r .memory_id)
stele memory search "smoke" --pretty
```

**Verify the MCP server matches the CLI:**

```bash
stele memory search "smoke"                                # via CLI
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"stele_memory_search","arguments":{"query":"smoke"}}}' | stele-mcp   # via MCP
```

Both produce the same JSON body.

## Troubleshooting

### `/stele` doesn't appear in my agent's slash-skill list

1. **Did you restart the agent?** Skills load at startup. Quit and re-open the agent host.
2. **Did the file land where it should?** `stele status` should report `yes` for your platform. If `no`, re-run `stele install --platform <name>` and check stderr for errors.
3. **Did the skill file render correctly?** `cat ~/.claude/skills/stele/SKILL.md` (or the equivalent path from the [platform table](#stele-install--stele-uninstall)) — should start with `---\nname: stele\n...` frontmatter.
4. **Is the agent reading from the right home?** Some agents are sandboxed; check the agent's docs for its skill-discovery rules.

### MCP server fails to start / agent says "stele-mcp not found"

1. **Is `stele-mcp` on PATH for the agent's launch environment?** GUI launchers (macOS .app, Windows shortcut) often don't see your shell PATH. Use the absolute path in `~/.claude/mcp.json`:
    ```json
    "command": "/full/path/to/.venv/bin/stele-mcp"
    ```
2. **Is your venv active in the agent?** If you installed `stele-core` in a venv, the agent needs the venv's Python on its PATH or an absolute path to `stele-mcp`.
3. **Smoke-test the server independently:**
    ```bash
    echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' | timeout 3 stele-mcp
    ```
    A working server prints a JSON-RPC `result` containing `"serverInfo":{"name":"stele",...}`.

### "artifact not found" when calling `stele_extract_from_artifact` or `stele_fetch`

The most common cause: passing a bare `artifact_id` instead of the full `stele://<namespace>/<artifact_id>` ref. The tools accept both for `extract_from_artifact` but `stele_fetch` requires the full URI. Always pass the full ref returned by `stele_store`.

### "PII_BLOCKED" error on `stele_fetch`

PII scrubbing is on by default for raw artifact bytes. To unblock fetch for trusted local use, edit `.stele/config.yaml`:

```yaml
pii:
  raw_fetch_enabled: true
```

**Don't do this on a shared deployment.** Summaries returned by recall/search remain scrubbed either way; the gate only affects `fetch`'s raw payload.

### `stele install` says "mcp.json is not valid JSON"

Your existing `mcp.json` has a syntax error or isn't a JSON object at the top level. The install refuses to act so you don't lose data. Inspect the file, fix the JSON manually, then re-run install. (Common cause: trailing commas, which JSON doesn't allow.)

### `stele install` refuses to act on a corrupted shared doc

You have multiple `## stele` markers in `~/.claude/CLAUDE.md` (or wherever). Manually fix the file to have at most one such heading, then re-run.

### `stele doctor` says "backend not reachable"

For DSN-backed backends (postgres/mariadb/clickhouse), the DSN in `.stele/config.yaml` doesn't resolve. Check:

- The database server is running.
- The DSN format matches your backend (`postgresql://...`, `mariadb://...`, `http://...`).
- Credentials are correct.
- The database exists (stele does NOT auto-create databases — it does auto-create tables).

### Reset to a known-good state

```bash
stele uninstall --all
rm -rf .stele/             # wipes local data
stele init
stele install --platform claude-code
```

## See also

- [`docs/quickstart.md`](quickstart.md) — 5-minute happy path.
- [`docs/mcp-tools.md`](mcp-tools.md) — reference for all 18 MCP tools.
- [`docs/packaging-auth-model.md`](packaging-auth-model.md) — why no auth in v1.
- [`docs/packaging-smoke-checklist.md`](packaging-smoke-checklist.md) — manual smoke before releases.
- [`docs/agent-integration.md`](agent-integration.md) — long-form agent integration guide (covers MCP, Python SDK, hooks).
