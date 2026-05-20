# Stele Quickstart — 5 minutes to a working agent

This guide takes you from zero to a Claude Code agent that uses stele for evidence-cited memory and artifact storage. Same pattern works for Codex, Cursor, OpenCode, Gemini CLI, Copilot, and Aider — substitute the platform name.

## 0. Prerequisites

- Python ≥3.12
- One of: Claude Code, Codex, Cursor, OpenCode, Gemini CLI, Copilot, Aider
- (Optional) A backend: SQLite is the default and requires nothing extra; Postgres / MariaDB / ClickHouse need their respective extras.

## 1. Install

```bash
pip install stele-core
```

That gives you two binaries: `stele` (the CLI) and `stele-mcp` (the stdio MCP server). For non-default backends:

```bash
pip install 'stele-core[postgres]'      # for Postgres
pip install 'stele-core[mariadb]'       # for MariaDB
pip install 'stele-core[clickhouse]'    # for ClickHouse
pip install 'stele-core[postgres-graph]' # for Phase 5 living-knowledge (requires Postgres)
pip install 'stele-core[all-backends]'  # everything except postgres-graph
```

Verify:

```bash
stele --help
stele-mcp --help  # exits after printing usage
```

## 2. Initialize a project

In your project directory:

```bash
stele init
```

This writes `.stele/config.yaml` with `backend.type: sqlite` and a database at `.stele/stele.db`. To pick a different backend:

```bash
stele init --backend memory                                           # ephemeral; good for tests
stele init --backend sqlite                                           # local file (default)
stele init --backend postgres --dsn postgresql://user:pw@host:5432/db # production
```

Verify the config is good:

```bash
stele doctor
# stele doctor: ok (.stele/config.yaml) — backend=sqlite capabilities=StashCapabilities(...)
```

## 3. Install the agent integration

```bash
stele install --platform claude-code
```

What this writes (no existing file is clobbered — `mcp.json` and `CLAUDE.md` are merged in place):

- `~/.claude/skills/stele/SKILL.md` — slash-skill so `/stele` appears in the agent
- `~/.claude/hooks/stele-large-output.sh` — nudge when Bash/Read output exceeds 4096 tokens
- `~/.claude/mcp.json` — registers the `stele-mcp` MCP server
- `~/.claude/CLAUDE.md` (created or merged) — adds a `## stele` section telling the agent how to use the tools
- `CLAUDE.md` in your current project (created or merged) — same `## stele` section, project-scope

For multiple platforms in one shot:

```bash
stele install --all
```

To see what's installed where:

```bash
stele status
```

## 4. Restart your agent

Claude Code, Codex, Cursor, etc. load skills + MCP server lists at startup. Quit and re-open. After restart:

- The agent's `/skills` list (or equivalent) should include `stele`.
- The MCP server connects on first tool call.

## 5. Verify the round-trip (in the agent)

In your agent, paste this prompt:

```
Use the stele MCP to:
1. stele_store a short text payload saying "My favorite editor is helix"
2. stele_memory_add with the returned ref as source_refs
3. stele_memory_search for "editor"
4. Tell me what you found and cite the stele:// ref.
```

A working stele install will: store the text, add a memory citing the ref, search and find it, and quote the original ref back. If any step fails, see [Troubleshooting in `cli-guide.md`](cli-guide.md#troubleshooting).

## 6. Try the runnable tour

Outside the agent, you can exercise all 18 tools without restarting anything:

```bash
python examples/mcp_tour.py
```

This calls every tool against an in-memory Stele and prints request + response. Good for understanding what each tool does without committing to an agent loop.

## What next

- **Tool reference:** [docs/mcp-tools.md](mcp-tools.md) — every tool, every schema, every example.
- **CLI reference:** [docs/cli-guide.md](cli-guide.md) — every `stele` subcommand + troubleshooting.
- **Backend choices:** [docs/quickstart.md#backend-selection](#backend-selection) (below).
- **Security model:** [docs/packaging-auth-model.md](packaging-auth-model.md) — why stdio-only + no auth in v1.
- **Living knowledge (Phase 5):** [docs/living-knowledge-setup.md](living-knowledge-setup.md) — superseding facts, retracting, time-travel queries on a Postgres + pg-raggraph stack.

---

## Backend selection

| Backend | When to use | DSN needed? | Extras needed? |
|---|---|---|---|
| `memory` | Tests, ephemeral sessions, demos | No | No |
| `sqlite` | **Default. Personal use, single machine.** | No (defaults to `.stele/stele.db`) | No |
| `postgres` | Multi-process, multi-machine, production | Yes | `stele-core[postgres]` |
| `mariadb` | Existing MariaDB infrastructure | Yes | `stele-core[mariadb]` |
| `clickhouse` | Analytics-shaped workloads | Yes | `stele-core[clickhouse]` |

Vector / hybrid retrieval works across all five via Chunkshop (`indexing.mode: sync` in your config). See [vector-indexing-setup.md](vector-indexing-setup.md).

## Upgrading

```bash
pip install --upgrade stele-core
stele install --all  # re-runs install with the new version
```

The install refreshes `.stele_version` stamps across every platform you've installed so you don't see "your codex install is stale" warnings after only re-installing Claude Code.

Stele itself does NOT auto-upgrade on pip install — re-running `stele install` is what propagates the new skill content. The MCP server picks up the new code on the next launch (when the agent restarts).

## Uninstall

```bash
stele uninstall --platform claude-code  # one platform
stele uninstall --all                   # everything
```

What this removes:

- The skill file, hook file, version stamp at each platform's path.
- The `## stele` section from `~/.claude/CLAUDE.md` and the project's `CLAUDE.md` (other sections preserved).
- The `stele` entry from `~/.claude/mcp.json` (other servers preserved).

What this does NOT remove:

- The `.stele/` directory in your project (your data — delete manually if you want it gone).
- `pip install`'d `stele-core` (use `pip uninstall stele-core`).
