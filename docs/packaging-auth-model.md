# Stele MCP — Auth Model (v1)

**Status:** stdio-only, no auth. Local-trusted execution boundary.

## Why

- The MCP server runs as a child process of the agent host (Claude Code, Codex, Cursor, etc.).
- The process boundary already gives the user explicit consent at launch time.
- Network-exposed transports (SSE, streamable-HTTP) defer the auth question — design slot reserved.

## What this means

- Anyone who can launch `stele-mcp` on this machine has full read/write access to whatever backend `.stele/config.yaml` points at.
- Don't commit a `.stele/config.yaml` containing a production DSN to a public repo.
- Signing keys (when `signing.mode != "off"`) come from the env var `STELE_SIGNING_SECRET`, NOT from the config file.
- The 18 MCP tools include destructive operations (`stele_delete`, `stele_memory_delete`, `stele_memory_retract`). Any agent that can call `stele-mcp` can call those.

## When this changes

The day a remote transport ships, this doc gets reopened. Plan:

1. Add bearer-token requirement to the network transport handshake.
2. Add a per-tool permission list (`mcp.allow_tools: [...]`) to `.stele/config.yaml`.
3. Add request signing for callers behind a shared secret.

Until then: stdio only.
