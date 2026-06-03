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
from typing import Any

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


@dataclass(frozen=True)
class ReduceConfig:
    """How hard to reduce ONE transcript event at the stream/parse boundary.

    Defaults are the measured keep120 sweet spot: keep the headline of each
    successful tool result (first `result_chars` chars, where the durable facts
    live: versions, test outcomes, discovered constraints), keep more of
    failures (the rule signal), and drop nothing that carries memory. The
    reduction is per-event with no lookback, so the SAME filter runs live on the
    ingest stream and batch over a stored .jsonl.

    `drop_success_results=True` is the older, aggressive "minify" behavior: it
    loses ~30% of memories (incl. rules) to save a few MB of storage, so it is
    only for archive-only sessions you will never distill. keep120 is the
    default because storage is cheap (~70MB for the whole corpus) and recall is
    not.

    Any char limit set to None means "no truncation" (keep the full body). So the
    tiers are: keep120 (default), keep300 (result_chars=300), or full
    (result_chars=None) -- all still drop signatures/snapshots/metadata. To also
    retain the exact original bytes, see ingest_session(keep_raw=True).
    """

    result_chars: int | None = 120
    error_chars: int | None = 220
    tool_chars: int | None = 200
    drop_success_results: bool = False


def _block_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(b.get("text", "")) for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def reduce_event(event: dict[str, Any], cfg: ReduceConfig | None = None) -> list[Turn]:
    """One parsed transcript JSON event -> 0+ reduced Turns. This is the single
    reduction filter for BOTH the live ingest stream and the batch file parser.

    It drops the structural cruft the model never needs: non-conversation lines
    (file-history-snapshot, attachment, metadata, system) -> []; the thinking
    SIGNATURE (a base64 attestation, ~20% of raw bytes) -> dropped, keeping only
    the thinking TEXT; tool bodies truncated per `cfg`. It preserves role and
    is_error so distill-time windowing can still surface failures first. Pure and
    streamable (no lookback), so on-disk and streamed sessions reduce identically.
    """
    cfg = cfg or ReduceConfig()
    if event.get("type") not in ("user", "assistant"):
        return []  # snapshots / attachments / metadata / system: not conversation
    msg = event.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if event.get("type") == "user" and isinstance(content, str):
        t = content.strip()
        return [Turn("user", t)] if t and not t.startswith("<") else []  # skip <reminders>
    if not isinstance(content, list):
        return []
    out: list[Turn] = []
    for b in content:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt in ("text", "thinking"):
            t = str(b.get("text") or b.get("thinking") or "").strip()  # never the signature
            if t:
                out.append(Turn(str(event.get("type")), t))
        elif bt == "tool_use":
            args = json.dumps(b.get("input", {}))[: cfg.tool_chars]
            out.append(Turn("tool", f"{b.get('name', 'tool')}({args})"))
        elif bt == "tool_result":
            if b.get("is_error"):
                out.append(Turn("result", _block_text(b.get("content"))[: cfg.error_chars],
                                is_error=True))
            elif not cfg.drop_success_results:
                out.append(Turn("result", _block_text(b.get("content"))[: cfg.result_chars]))
    return out


def parse_claude_jsonl(path: Path, cfg: ReduceConfig | None = None) -> list[Turn]:
    """Claude Code .jsonl -> reduced turns (the BATCH / backfill path): read the
    file, run `reduce_event` per line. Same filter the live stream applies, so a
    session reduces identically whether it streamed in or is read off disk.
    Preserves tool calls and FAILURES (the precedent/pitfall signal)."""
    cfg = cfg or ReduceConfig()
    turns: list[Turn] = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        turns.extend(reduce_event(obj, cfg))
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


def parse_transcript(src: object, cfg: ReduceConfig | None = None) -> list[Turn]:
    """Parse a transcript from a path (.jsonl -> Claude, else generic JSON), a
    list[Turn], or a list[{role, content}] message dicts. `cfg` applies to the
    .jsonl path (the reduction); list/openai inputs are taken as-is."""
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
    if p.suffix == ".jsonl":
        return parse_claude_jsonl(p, cfg)
    return parse_openai_messages(p)


def _line(t: Turn) -> str:
    """Render one (already-reduced) turn to a window/evidence line."""
    if t.role == "tool":
        return f"[TOOL] {t.text}"
    if t.role == "result":
        return f"{'[RESULT ERROR]' if t.is_error else '[RESULT ok]'} {t.text}"
    return f"[{t.role.upper()}] {t.text}"


def render(turns: list[Turn]) -> str:
    return "\n".join(_line(t) for t in turns)


def windows(turns: list[Turn], max_chars: int = 4000, limit: int = 3) -> list[str]:
    """Group already-reduced turns into ~max_chars windows, failure-bearing
    windows first (richest), capped at `limit`. Turns arrive pre-reduced from
    `reduce_event`, so windowing only packs and orders -- the drop/truncate
    decisions live in ReduceConfig at the stream boundary, not here."""
    grouped: list[tuple[str, bool]] = []
    buf: list[str] = []
    size = 0
    has_err = False
    for t in turns:
        line = _line(t)
        buf.append(line)
        size += len(line)
        has_err = has_err or t.is_error
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


def minify_transcript(src: object, *, caveman: bool = False, max_chars: int = 200_000,
                      cfg: ReduceConfig | None = None) -> str:
    """Reduce a transcript to its signal, returning minified TEXT (the stored
    evidence form). Uses the same `reduce_event` filter as ingestion (via
    parse_transcript), so the stored bytes are exactly what distillation reads.
    The reduction level is `cfg` (default keep120); pass
    `ReduceConfig(drop_success_results=True)` for the older archive-only minify.

    caveman=True additionally runs lede.clean_text on NATURAL-LANGUAGE turns
    only (filler/markdown/boilerplate). It is LOSSY (lowercases, strips
    markdown), never touches [TOOL]/[RESULT] lines (code/commands/output), and
    falls back to a no-op if lede is unavailable."""
    prose_clean = None
    if caveman:
        try:
            from lede import clean_text as prose_clean  # type: ignore[no-redef]
        except ModuleNotFoundError:
            prose_clean = None
    out: list[str] = []
    for t in parse_transcript(src, cfg):
        line = _line(t)
        if prose_clean is not None and t.role in ("user", "assistant"):
            tag, body = line.split("] ", 1)  # "[USER] x" -> ("[USER", "x")
            line = f"{tag}] {prose_clean(body)}"
        out.append(line)
    return "\n".join(out)[:max_chars]


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
