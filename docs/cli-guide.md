# Stele CLI Guide

The `stele` binary is installed by `pip install stele-core` and exposes six subcommands. The companion `stele-mcp` binary runs the MCP server (same code path as `stele mcp`).

```
stele init       Write .stele/config.yaml with sensible defaults.
stele install    Install skill + hook + MCP entry for an agent platform.
stele uninstall  Reverse a previous install.
stele status     Show per-platform install state.
stele doctor     Validate config + backend reachability.
stele mcp        Run the stdio MCP server (foreground).
```

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

## See also

- [`docs/mcp-tools.md`](mcp-tools.md) — reference for all 18 MCP tools.
- [`docs/packaging-auth-model.md`](packaging-auth-model.md) — why no auth in v1.
- [`docs/packaging-smoke-checklist.md`](packaging-smoke-checklist.md) — manual smoke before releases.
- [`docs/agent-integration.md`](agent-integration.md) — long-form agent integration guide (covers MCP, Python SDK, hooks).
