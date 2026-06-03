"""Session-transcript ingestion: parse real agent transcripts and LLM-extract
durable kinded memories (incl. failures/deadends/rework).

This is the front half of distilling memory from raw agent work. The
deterministic lede+pattern extractor (candidates.py) fits structured prose but
not conversational, tool-heavy transcripts, where the richest signal is the
messy part (failed commands, rework, corrections). So extraction here is
LLM-driven: the LLM is INJECTED (no LLM client imported at module top), keeping
this pure-ish and the core LLM-free by default. Transcript parsing is
format-pluggable (PARSERS) for non-Claude agent loops.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from stele.core.memory_record import KIND_VALUES

LLM = Callable[[str], str]


@dataclass(frozen=True)
class Turn:
    role: str  # user | assistant | tool | result
    text: str
    is_error: bool = False


@dataclass(frozen=True)
class SessionMemory:
    kind: str  # a MemoryKind value
    summary: str
    detail: str


def _block_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(b.get("text", "")) for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def parse_claude_jsonl(path: Path) -> list[Turn]:
    """Claude Code .jsonl -> turns, preserving tool calls and FAILURES (the
    precedent/pitfall signal). Renders tool_use as a TOOL turn and tool_result
    as a RESULT turn, flagging is_error."""
    turns: list[Turn] = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") not in ("user", "assistant"):
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if obj.get("type") == "user" and isinstance(content, str):
            t = content.strip()
            if t and not t.startswith("<"):
                turns.append(Turn("user", t))
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt in ("text", "thinking"):
                t = str(b.get("text") or b.get("thinking") or "").strip()
                if t:
                    turns.append(Turn(str(obj.get("type")), t))
            elif bt == "tool_use":
                args = json.dumps(b.get("input", {}))[:200]
                turns.append(Turn("tool", f"{b.get('name', 'tool')}({args})"))
            elif bt == "tool_result":
                turns.append(Turn("result", _block_text(b.get("content"))[:300],
                                  is_error=bool(b.get("is_error"))))
    return turns


def parse_openai_messages(path: Path) -> list[Turn]:
    """Generic agent loop: a JSON file with a list (or {messages:[...]}) of
    {role, content} dicts. Lets non-Claude transcripts feed the same pipeline."""
    data = json.loads(path.read_text(errors="replace"))
    msgs = data.get("messages", []) if isinstance(data, dict) else data
    out: list[Turn] = []
    for m in msgs if isinstance(msgs, list) else []:
        if isinstance(m, dict):
            text = _block_text(m.get("content"))
            if text.strip():
                out.append(Turn(str(m.get("role", "assistant")), text.strip()))
    return out


PARSERS: dict[str, Callable[[Path], list[Turn]]] = {
    "claude_jsonl": parse_claude_jsonl,
    "openai_messages": parse_openai_messages,
}


def parse_transcript(src: object) -> list[Turn]:
    """Parse a transcript from a path (.jsonl -> Claude, else generic JSON), a
    list[Turn], or a list[{role, content}] message dicts."""
    if isinstance(src, list):
        if src and isinstance(src[0], Turn):
            return list(src)
        out: list[Turn] = []
        for m in src:
            if isinstance(m, dict):
                text = _block_text(m.get("content"))
                if text.strip():
                    out.append(Turn(str(m.get("role", "user")), text.strip()))
        return out
    p = Path(str(src))
    return (parse_claude_jsonl if p.suffix == ".jsonl" else parse_openai_messages)(p)


def render(turns: list[Turn]) -> str:
    lines: list[str] = []
    for t in turns:
        if t.role == "tool":
            lines.append(f"[TOOL] {t.text}")
        elif t.role == "result":
            lines.append(f"{'[RESULT ERROR]' if t.is_error else '[RESULT ok]'} {t.text[:200]}")
        else:
            lines.append(f"[{t.role.upper()}] {t.text}")
    return "\n".join(lines)


def _compact_lines(turns: list[Turn]) -> list[tuple[str, bool]]:
    """Reduce the transcript to the signal worth sending to the LLM, returning
    (line, is_failure) pairs. What matters for durable memory: user turns,
    assistant reasoning, and FAILURES + the surrounding work. What is noise:
    successful tool-result bodies (ephemeral, and the source of junk facts) and
    runs of repeated read-only calls. So: keep user/assistant/thinking in full,
    keep failed results verbatim, shrink tool calls to name+short-arg, drop
    successful result bodies, and collapse consecutive same-name tool calls.
    This cuts tokens several-fold and improves precision."""
    out: list[tuple[str, bool]] = []
    prev_tool: str | None = None
    for t in turns:
        if t.role == "tool":
            name = t.text.split("(", 1)[0]
            if name == prev_tool:
                continue  # collapse a run of the same tool (ls/grep/read spam)
            prev_tool = name
            out.append((f"[TOOL] {t.text[:90]}", False))
            continue
        prev_tool = None
        if t.role == "result":
            if t.is_error:
                out.append((f"[RESULT ERROR] {t.text[:220]}", True))  # the signal
            continue  # drop successful result bodies (noise + ephemeral facts)
        out.append((f"[{t.role.upper()}] {t.text}", False))
    return out


def windows(turns: list[Turn], max_chars: int = 4000, limit: int = 3) -> list[str]:
    """Reduce (see _compact_lines), then group into ~max_chars windows packed
    with signal; failure-bearing windows first (richest), capped at `limit`."""
    lines = _compact_lines(turns)
    grouped: list[tuple[str, bool]] = []
    buf: list[str] = []
    size = 0
    has_err = False
    for line, is_err in lines:
        buf.append(line)
        size += len(line)
        has_err = has_err or is_err
        if size >= max_chars:
            grouped.append(("\n".join(buf), has_err))
            buf, size, has_err = [], 0, False
    if buf:
        grouped.append(("\n".join(buf), has_err))
    grouped.sort(key=lambda w: (not w[1], -len(w[0])))  # failure windows first
    return [text for text, _ in grouped[:limit]]


_EXTRACT_PROMPT = """You are distilling DURABLE MEMORY from one window of an AI agent's
work session, for reuse by a future agent. Capture the messy signal: failed
commands, deadends, rework, corrections, and what fixed them.

Return ONLY a JSON array (no prose, no code fences). Each item is an object with
keys "kind", "summary" (one specific line), and "detail" (short; include the
failing command or approach if relevant).

kind is one of: fact (a durable fact/result/state), decision (a choice + why),
pitfall (something that FAILED or a deadend/mistake, with what went wrong),
workaround (the fix), instruction (a rule the USER stated, always/never),
preference (a stated preference). Skip chitchat. Only durable, reusable memory.
If nothing durable, return [].

WINDOW:
{window}
"""


def extract_session_memories(llm: LLM, window: str) -> list[SessionMemory]:
    """Ask the injected LLM to extract durable kinded memories from one window.
    Defensive JSON parsing; unknown kinds dropped. Returns [] on parse failure."""
    match = re.search(r"\[.*\]", llm(_EXTRACT_PROMPT.format(window=window[:8000])), re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    out: list[SessionMemory] = []
    for obj in parsed if isinstance(parsed, list) else []:
        if not isinstance(obj, dict):
            continue
        kind = str(obj.get("kind", "")).strip()
        summary = str(obj.get("summary", "")).strip()
        if kind in KIND_VALUES and summary:
            detail = str(obj.get("detail", "")).strip()
            out.append(SessionMemory(kind=kind, summary=summary, detail=detail))
    return out
