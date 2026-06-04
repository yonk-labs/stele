# Stele Packaging — Manual Smoke Checklist

Run this on a maintainer machine before each release that touches `mcp/`, `cli/`, or `packaging/`. Not part of CI.

## Setup

- [ ] Back up `~/.claude`, `~/.cursor`, `~/.agents`, `~/.config/opencode`, `~/.gemini`, `~/.copilot`, `~/.aider` (or run on a fresh user).
- [ ] `uv pip install -e .` from a clean clone.
- [ ] `cd /tmp && mkdir stele-smoke && cd stele-smoke`
- [ ] `stele init --backend sqlite`
- [ ] `stele doctor` exits 0 and prints capability info.

## Per-platform (7 platforms)

For each of: claude-code, codex, opencode, cursor, gemini-cli, copilot, aider:

- [ ] `stele install --platform <name>` succeeds.
- [ ] Skill file exists at the expected path (`stele status` shows `yes` for the platform).
- [ ] If the platform has a hook template, the hook file exists too.
- [ ] Restart the agent (whichever applies). `/stele` (or platform-equivalent) is discoverable.
- [ ] In the agent, exercise one MCP round-trip: ask the agent to call `stele_store("hello")` then `stele_fetch(<ref>)`. Verify both succeed and the bytes round-trip.

## Memory smoke (Claude Code minimum)

- [ ] In a conversation, mention a specific fact ("my favorite editor is helix").
- [ ] Ask the agent to record it via `stele_memory_add`.
- [ ] Start a new session.
- [ ] Ask the agent what your favorite editor is — verify it calls `stele_memory_search` and cites the `stele://` ref.

## Cleanup

- [ ] `stele uninstall --all`.
- [ ] `stele status` shows `no` for every platform.
- [ ] No leftover files under `~/.claude/skills/stele`, `~/.agents/skills/stele`, `~/.cursor/skills/stele`, `~/.config/opencode/skills/stele`, `~/.gemini/skills/stele`, `~/.copilot/skills/stele`, `~/.aider/skills/stele`.
- [ ] No `## stele` section remains in any shared doc (`~/.claude/CLAUDE.md`, project `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`).
