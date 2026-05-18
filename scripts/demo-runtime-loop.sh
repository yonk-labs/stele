#!/usr/bin/env bash
# Runtime loop demo (Phase 7): observe -> store -> WorkGraph -> extract ->
# recall/pack -> resume, fully in-process (no LLM, no network).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

.venv/bin/python - <<'PY'
from stele.core.stash import Stele
from stele.runtime.demo import SteleAgentSession
from stele.workgraph.store import InProcessWorkGraphStore

stele = Stele.from_config({"backend": {"type": "memory"}})
sess = SteleAgentSession(
    stele=stele, wg_store=InProcessWorkGraphStore(),
    namespace="demo", session_id="s1",
)
sess.start("debug the failing deploy")

tool_output = (
    "Deploy log. Owner contact: ops@example.com (PII — must be scrubbed). "
    "Root cause: the deploy region is eu-west-1 but the secret was created "
    "in us-east-1. " + ("verbose stack frame line. " * 200)
)
node = sess.observe_tool("Bash", tool_output)
print(f"observed -> node {node.id[:8]} cites {node.source_refs[0]}")

pack = sess.recall_and_pack(query="what is the deploy region")
print("\n--- PACKED CONTEXT (stable) ---")
print(pack.stable_context)
print("\n--- PACKED CONTEXT (dynamic, every line ref-backed) ---")
print(pack.dynamic_context)
print(f"\nrecovery handles: {pack.recovery_handles}")
print(f"token_estimate={pack.token_estimate} omitted={pack.omitted}")
assert "eu-west-1" in pack.dynamic_context, "answer fact lost"
assert "ops@example.com" not in pack.dynamic_context, "PII LEAKED"

print("\n--- RESUME VIEW (Markdown) ---")
print(sess.resume())

print(f"\nhealth: {sess.health().status}")
print(f"session end closed {sess.end()} graph(s); idempotent end -> {sess.end()}")
print("\nLoop proven: PII scrubbed, every claim cites stele://, resume works.")
PY
