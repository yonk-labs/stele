# ruff: noqa: E501 -- session-distillation harness.
"""Distill durable memory from REAL agent transcripts, then run the six modes.

This is the honest target the deterministic CLAUDE.md path was a poor proxy for:
real session transcripts are tool-dominated with sparse prose, and the richest
signal is the messy part (failed commands, deadends, rework, corrections). A
pattern scan cannot see that, so extraction here is LLM-driven: render the
transcript (turns + tool calls + FAILURES), window it, and ask an LLM to extract
kinded memories with evidence. Those kinded memories feed the existing
`Stele.distill` views.

Transcript parsing is format-pluggable (PARSERS) so other agent loops can be
added; the Claude Code .jsonl parser is implemented.

Run:
    STELE_PG_DSN=postgresql://.../stele_bench \
      .venv/bin/python -m benchmarks.external.memory_modes.session_distill \
        --limit 20 --per-session-windows 3
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stele.core.memory_record import KIND_VALUES, MemoryScope
from stele.core.stash import Stele
from stele.distill.jobs import run_sync
from stele.distill.models import DistilledView

_PROJECTS_ROOT = Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class Turn:
    role: str  # user | assistant | tool | result
    text: str
    is_error: bool = False


def _block_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text", "")))
        return " ".join(parts)
    return ""


def parse_claude_jsonl(path: Path) -> list[Turn]:
    """Claude Code .jsonl -> turns, preserving tool calls and FAILURES.

    Keeps user/assistant text + thinking, renders each tool_use as a TOOL line,
    and each tool_result as RESULT (marking is_error). The failures are the
    precedent/pitfall signal, so they are retained verbatim-ish (truncated)."""
    turns: list[Turn] = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = obj.get("type")
        if typ not in ("user", "assistant"):
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        # plain user instruction
        if typ == "user" and isinstance(content, str):
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
                    turns.append(Turn(typ, t))
            elif bt == "tool_use":
                name = str(b.get("name", "tool"))
                inp = json.dumps(b.get("input", {}))[:200]
                turns.append(Turn("tool", f"{name}({inp})"))
            elif bt == "tool_result":
                err = bool(b.get("is_error"))
                res = _block_text(b.get("content"))[:300]
                turns.append(Turn("result", res, is_error=err))
    return turns


def parse_openai_messages(path: Path) -> list[Turn]:
    """Generic agent-loop format: a JSON file with a list of {role, content}
    messages (OpenAI-style). Lets non-Claude transcripts feed the same pipeline."""
    data = json.loads(path.read_text(errors="replace"))
    msgs = data.get("messages", data) if isinstance(data, dict) else data
    turns: list[Turn] = []
    for m in msgs if isinstance(msgs, list) else []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "assistant"))
        text = _block_text(m.get("content"))
        if text.strip():
            turns.append(Turn(role, text.strip()))
    return turns


PARSERS: dict[str, Callable[[Path], list[Turn]]] = {
    "claude_jsonl": parse_claude_jsonl,
    "openai_messages": parse_openai_messages,
}


def detect_parser(path: Path) -> Callable[[Path], list[Turn]]:
    if path.suffix == ".jsonl":
        return parse_claude_jsonl
    return parse_openai_messages


def render(turns: Iterable[Turn]) -> str:
    """A compact, readable transcript rendering. Failures are flagged so the
    extractor can mine them as pitfalls/precedents."""
    lines: list[str] = []
    for t in turns:
        if t.role == "tool":
            lines.append(f"[TOOL] {t.text}")
        elif t.role == "result":
            tag = "[RESULT ERROR]" if t.is_error else "[RESULT ok]"
            lines.append(f"{tag} {t.text[:200]}")
        else:
            lines.append(f"[{t.role.upper()}] {t.text}")
    return "\n".join(lines)


def windows(turns: list[Turn], max_chars: int, limit: int) -> list[str]:
    """Group turns into ~max_chars windows, prioritizing windows that contain a
    failure (more memory signal). Returns up to `limit` rendered windows."""
    out: list[str] = []
    buf: list[Turn] = []
    size = 0
    for t in turns:
        buf.append(t)
        size += len(t.text)
        if size >= max_chars:
            out.append(render(buf))
            buf, size = [], 0
    if buf:
        out.append(render(buf))
    # windows with a failure first (richest signal), then by length
    out.sort(key=lambda w: ("[RESULT ERROR]" not in w, -len(w)))
    return out[:limit]


_EXTRACT_PROMPT = """You are distilling DURABLE MEMORY from one window of an AI agent's work session, for reuse by a future agent. Capture the messy signal: failed commands, deadends, rework, corrections, and what fixed them.

Return ONLY a JSON array (no prose, no code fences). Each item:
{{"kind": "<one of: fact, decision, pitfall, workaround, instruction, preference, issue>", "summary": "<one line, specific>", "detail": "<short, include the failed command/approach if relevant>"}}

Kinds:
- fact: a durable fact established (a number, path, name, state, result).
- decision: a choice made and the reason.
- pitfall: something that FAILED or a deadend or a mistake (capture the failing command/approach and why it failed).
- workaround: how a problem was resolved (the fix).
- instruction: a rule/convention the USER stated (always/never do X).
- preference: a stated user preference.
Skip chitchat, acknowledgements, and one-off trivia. Only durable, reusable memory. If nothing durable, return [].

WINDOW:
{window}
"""


def extract_memories(llm: Callable[[str], str], window: str) -> list[dict[str, str]]:
    raw = llm(_EXTRACT_PROMPT.format(window=window[:8000]))
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    out: list[dict[str, str]] = []
    for obj in parsed if isinstance(parsed, list) else []:
        if not isinstance(obj, dict):
            continue
        kind = str(obj.get("kind", "")).strip()
        summary = str(obj.get("summary", "")).strip()
        if kind in KIND_VALUES and summary:
            out.append({"kind": kind, "summary": summary, "detail": str(obj.get("detail", "")).strip()})
    return out


def ingest_session(stele: Stele, llm: Callable[[str], str], path: Path,
                   scope: MemoryScope, max_windows: int) -> int:
    turns = detect_parser(path)(path)
    if not turns:
        return 0
    ref = str(stele.store(render(turns)[:200000], namespace=scope.namespace).reference)
    committed = 0
    for window in windows(turns, max_chars=4000, limit=max_windows):
        for mem in extract_memories(llm, window):
            stele.memory.add(
                text=mem["detail"] or mem["summary"], kind=mem["kind"],  # type: ignore[arg-type]
                source_refs=[ref], scope=scope,
                summary=mem["summary"], detail=mem["detail"],
                metadata={"source": "session", "session": path.name},
            )
            committed += 1
    return committed


def _sessions(limit: int) -> list[Path]:
    files = sorted(_PROJECTS_ROOT.glob("*/*.jsonl"), key=lambda p: p.stat().st_size, reverse=True)
    # spread across projects: take the largest from distinct project dirs first
    seen: set[str] = set()
    picked: list[Path] = []
    for f in files:
        if f.parent.name not in seen:
            seen.add(f.parent.name)
            picked.append(f)
        if len(picked) >= limit:
            break
    return picked


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--limit", type=int, default=20, help="how many sessions to ingest")
    ap.add_argument("--per-session-windows", type=int, default=3)
    ap.add_argument("--namespace", default="distill-real-sessions")
    args = ap.parse_args(argv)
    import os
    dsn = args.dsn or os.environ.get("STELE_PG_DSN")
    if not dsn:
        raise SystemExit("set STELE_PG_DSN or pass --dsn")

    import contextlib

    from benchmarks.answer_workflow import OpenAICompatAnswerer
    from benchmarks.external.memory_modes.run import _ANSWER_URL
    from benchmarks.external.sweep_matrix import _QWEN
    from stele.core.config import BackendConfig, StashConfig

    stele = Stele(config=StashConfig(backend=BackendConfig(type="postgres", dsn=dsn)))
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_QWEN, base_url=_ANSWER_URL, api_key="local")

    def llm(prompt: str) -> str:
        return str(ans._chat(model=_QWEN, json_mode=False,
                             messages=[{"role": "user", "content": prompt}])).strip()

    stele._distill_llm = llm  # type: ignore[attr-defined]

    scope = MemoryScope(namespace=args.namespace)
    with contextlib.suppress(Exception):
        stele.purge_namespace(args.namespace, dry_run=False)

    sessions = _sessions(args.limit)
    total = 0
    for path in sessions:
        n = ingest_session(stele, llm, path, scope, args.per_session_windows)
        total += n
        print(f"  ingested {n:>3} memories from {path.parent.name[:34]}", flush=True)
    print(f"\nTOTAL: {total} durable memories distilled from {len(sessions)} real sessions\n")

    def _distill_call(mode: str) -> Coroutine[Any, Any, DistilledView]:
        method = getattr(stele.distill, mode)
        return method(scope)  # type: ignore[no-any-return]

    def _factory(mode: str) -> Callable[[], Coroutine[Any, Any, DistilledView]]:
        return lambda: _distill_call(mode)  # binds the param, not the loop var

    for mode in ("rules", "skills", "best_practices", "precedents", "facts"):
        view = run_sync(_factory(mode))
        print(f"=== distill_{mode} -> {len(view.items)} ===")
        for it in view.items[:8]:
            do_instead = getattr(it, "do_instead", "")
            extra = f"  ==> {do_instead}" if do_instead else ""
            print(f"   - {it.summary[:88]}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
