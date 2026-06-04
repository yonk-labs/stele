# Plugging Stele into an Agent

Stele is an **off-prompt memory layer**, not an agent framework. There is no
required network call and no hosted dependency — you embed the `stele`
Python package in whatever loop you already have. First-class framework
adapters (LangChain middleware, an MCP server, an OpenAI Agents SDK shim)
are **Phase 7** and not shipped yet; until then you wire the public API
into your loop directly. The loop is small and the same everywhere.

## The universal loop

```
                ┌─────────────────────────────────────────┐
                │  before the model call:                  │
                │    ctx = stele.recall(query, scope)      │  ← inject ctx.context
                └─────────────────────────────────────────┘
                                  │
                          model produces output / calls a tool
                                  │
                ┌─────────────────────────────────────────┐
                │  after a large tool result / turn:       │
                │    s = stele.store(result, namespace=…)  │  ← cheap stele:// ref
                │    stele.extract.from_text(text, scope)  │  ← durable memories
                │  when a fact changes:                    │
                │    memory.add(..., supersedes=[old])     │
                │    memory.retract(id, reason=…)          │  ← living knowledge
                └─────────────────────────────────────────┘
```

Three rules that make it sovereign: every memory cites the `stele://`
evidence that produced it; PII is scrubbed before anything is model-visible;
the artifact is stored once and replaced in-prompt by a short summary + ref
(that is the token win).

Shared setup for every example below:

```python
from stele import Stele
from stele.core.memory_record import MemoryScope

stele = Stele.from_config({"backend": {"type": "sqlite", "path": ".stele/agent.db"}})
scope = MemoryScope(user_id="alice", agent_id="my-agent", session_id="sess-1")
```

## Pattern 1 — wrap any chat/agent loop

```python
def turn(user_msg: str) -> str:
    # 1. Recall the right context (adaptive escalation, no oracle)
    ctx = stele.recall(query=user_msg, scope=scope)

    system = (
        "You have a sovereign memory. Relevant prior context "
        f"(each line cites its source):\n{ctx.context}"
    )
    reply, tool_outputs = call_your_model(system=system, user=user_msg)

    # 2. Stash big tool outputs off-prompt; keep only the ref + summary
    for out in tool_outputs:
        if len(out) > 4000:                       # your own threshold
            s = stele.store(out, namespace="tools", session_id=scope.session_id)
            # hand the model s.reference + s.summary next turn instead of `out`

    # 3. Distil durable memories from the exchange (deterministic, no LLM)
    stele.extract.from_text(f"{user_msg}\n{reply}", scope=scope)
    return reply
```

`ctx.context` is a newline-joined, PII-scrubbed, source-cited block — drop it
straight into a system or developer message.

## Pattern 2 — Claude (Anthropic API)

```python
import anthropic

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY in env

def ask_claude(user_msg: str) -> str:
    ctx = stele.recall(query=user_msg, scope=scope)
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=("Use this sovereign memory; every line cites its "
                f"stele:// source:\n{ctx.context}"),
        messages=[{"role": "user", "content": user_msg}],
    )
    reply = msg.content[0].text
    stele.extract.from_messages(
        [{"role": "user", "content": user_msg},
         {"role": "assistant", "content": reply}],
        scope=scope,
    )
    return reply
```

Large tool/result blocks: `s = stele.store(big_text, namespace="tools")`,
then pass `f"[{s.reference}] {s.summary}"` to the model and let it call a
`fetch` tool that returns `stele.fetch(ref).content` only when it actually
needs the full text. That is the off-prompt win.

## Pattern 3 — Claude Code (hooks)

Stele fits Claude Code's hook model with no code changes to Claude Code.
Add hooks in `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      { "matcher": "Bash|Read|WebFetch",
        "hooks": [{ "type": "command",
                    "command": ".venv/bin/python scripts/hooks/stele_capture.py" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command",
                    "command": ".venv/bin/python scripts/hooks/stele_recall.py" }] }
    ]
  }
}
```

`stele_capture.py` (PostToolUse — store oversized tool output as evidence):

```python
import json, sys
from stele import Stele
from stele.core.memory_record import MemoryScope

ev = json.load(sys.stdin)                       # Claude Code passes event JSON
out = str(ev.get("tool_response", ""))
if len(out) > 4000:
    stele = Stele.from_config({"backend": {"type": "sqlite", "path": ".stele/cc.db"}})
    s = stele.store(out, namespace="claude-code", session_id=ev.get("session_id"))
    stele.extract.from_text(out, scope=MemoryScope(namespace="claude-code"))
    print(f"stored {s.reference} ({s.estimated_token_savings} tok saved)")
```

`stele_recall.py` (UserPromptSubmit — inject recalled context; stdout is
added to the model's context by Claude Code):

```python
import json, sys
from stele import Stele
from stele.core.memory_record import MemoryScope

ev = json.load(sys.stdin)
stele = Stele.from_config({"backend": {"type": "sqlite", "path": ".stele/cc.db"}})
ctx = stele.recall(query=ev.get("prompt", ""),
                   scope=MemoryScope(namespace="claude-code"))
if ctx.context:
    print("Sovereign memory (source-cited):\n" + ctx.context)
```

Same idea works as a Claude Code **skill** (a `/recall` skill that calls
`stele.recall` and prints the block) if you prefer explicit invocation over
automatic hooks.

### Pattern 3b: SessionEnd ingest (the conversation feed)

To capture whole sessions for later distillation (not just oversized tool
output), add a **SessionEnd** hook that calls the `stele-ingest` console script.
It reduces the session transcript to its keep120 signal (drops thinking
signatures, file snapshots, metadata; truncates tool bodies; keeps failures) and
stores ONE reduced artifact. The raw transcript never lands.

```json
{
  "hooks": {
    "SessionEnd": [
      { "hooks": [{ "type": "command",
                    "command": "stele-ingest \"$(jq -r .transcript_path)\" --session-id \"$(jq -r .session_id)\" --namespace sessions" }] }
    ]
  }
}
```

A ready-made hook script that parses the stdin JSON itself ships at
`packaging/templates/hooks/claude-code-ingest.sh.j2` (point the hook at the
rendered `.sh` instead of the inline `jq` form if you prefer). Retention tiers
are flags (`--result-chars 300`, `--full`, `--keep-raw`) or config defaults
(`ExtractionConfig.reduce_*`). `stele install --platform claude-code` now drops
the rendered script at `~/.claude/hooks/stele-session-ingest.sh` (chmod +x) and
prints the `settings.json` snippet to register it. Claude Code only runs hooks
listed in `settings.json`, so you still add the `SessionEnd` entry yourself
(install does not edit `settings.json`). The periodic distill (Phase B) then
reads these reduced artifacts. See
[`docs/guides/memory-distillation-guide.md`](memory-distillation-guide.md).

## Pattern 4 — Codex / OpenAI-style agents

Identical loop, OpenAI SDK:

```python
from openai import OpenAI
client = OpenAI()

def ask(user_msg: str) -> str:
    ctx = stele.recall(query=user_msg, scope=scope)
    resp = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system",
             "content": f"Sovereign memory (source-cited):\n{ctx.context}"},
            {"role": "user", "content": user_msg},
        ],
    )
    reply = resp.choices[0].message.content
    stele.extract.from_text(f"{user_msg}\n{reply}", scope=scope)
    return reply
```

For the OpenAI Agents SDK / function-calling: register two tools backed by
Stele — `recall(query)` → `stele.recall(...).context` and `remember(text)` →
`stele.extract.from_text(...)` — and let the agent call them. A built-in
adapter that does this wiring for you is Phase 7.

## Pattern 5 — MCP server (sketch)

A first-class MCP server is a Phase 7 deliverable. You can expose Stele over
MCP today with a thin server: tools `stele_recall(query, scope)`,
`stele_store(content)`, `stele_remember(text)`, `stele_retract(id, reason)`,
each a one-line call into the public API above. Any MCP-speaking agent
(Claude Desktop, Claude Code, Cursor, …) then gets sovereign memory without
importing the package.

## Living knowledge for agents (Phase 5)

When the world changes, don't append — *evolve*. On a Postgres backend with
`stele-core[postgres-graph]` and `graph.enabled: true`:

```python
old = stele.memory.search(MemoryQuery(query="deploy target", scope=scope))[0]
stele.memory.add(text="Deploy target is now eu-west-1.", kind="decision",
                 source_refs=[s.reference], scope=scope, supersedes=[old.id])
# later, a decision is reversed:
stele.memory.retract(some_id, reason="rolled back in incident 4821")

# the agent asks; graph_search honors supersession/retraction + time-travel
ans  = stele.recall(query="where do we deploy?", scope=scope,
                    strategy="graph_search")
were = stele.recall(query="where did we deploy?", scope=scope,
                    strategy="graph_search", as_of=incident_start)
```

Every hit still carries its exact `stele://` source, so the agent can always
show its work. Full guide: [living-knowledge-setup.md](living-knowledge-setup.md).

## What's first-class vs DIY today

| Capability | Status |
| --- | --- |
| `store` / `extract` / `recall` / `memory` / living-knowledge public API | ✅ shipped (Phases 1–5) |
| Vector + hybrid retrieval (5 backends) | ✅ shipped (Phase 4) |
| Self-host harness (`make -C deploy e2e`) | ✅ shipped (INFRA-A) |
| Runtime capture loop / context packer / WorkGraph | ⏳ Phase 6–7 |
| LangChain middleware / MCP server / OpenAI Agents adapter | ⏳ Phase 7 |

Until Phase 7 lands those adapters, the patterns above are the supported
integration path — they use only the committed, tested public surface.
