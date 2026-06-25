"""Session reuse audit: point at a directory of Claude `.jsonl` sessions, estimate reducible work.

Four levers, each measured WITH a change-gate so legitimate post-edit re-work is NOT counted as
savings (the read-edit-reread loop is the dominant in-session pattern and is not waste):

  1. Redundant tool calls   - an expensive command re-run with NO file mutation since its last
                              run (Edit/Write or a mutating Bash resets the gate).
  2. Context reuse          - a file re-read with IDENTICAL bytes (content hash, not path).
                              within-agent = free (in context); cross-agent = a subagent re-read
                              of what the orchestrator/sibling already had (FRESH context, not
                              free - the memory opportunity); cross-session = conditional.
  3. Question answerability - for each user turn, the answer-work (tool calls until the next user
                              turn). If ALL of it was redundant re-acquisition (the agent only
                              re-fetched what it already had), the question was answerable from
                              context. Token estimate = the redundant answer-work's result tokens.
  4. Over-fetch             - a Read whose bytes were largely NOT near a downstream edit: read a
                              2,000-line file, edit 10 lines. Unlike 1-3 (which are data movement:
                              same bytes, different source), this is INFERENCE tokens on the first
                              read, reducible by targeted retrieval. The realer lever.

Heuristics are proxies, not proof a model could answer with zero context; they measure the
WASTED re-fetch, which is the reducible part. Token axis: tiktoken cl100k if installed, else
~chars/4. Sessions are processed oldest-first so "prior session" is well defined.

SCOPE: these levers and verdicts are CODING-shaped (file reads/edits, command re-runs). They are
NOT universal. A conversational / recall workload (e.g. LoCoMo captured step-by-step) would light up
a different set: cross-session recall and question-answerability would dominate (the whole task is
recalling prior-session facts), over-fetch maps to retrieve-much-use-one-fact, and the canary /
edit levers go to ~0 (no code). The tool keys on coding tool names (Read/Edit/Bash); a non-coding
capture needs its own adapter and would not trigger these as-is.

Subagents: Claude stores them as `<session-id>/subagents/agent-*.jsonl` beside the main
`<session-id>.jsonl`. They are bundled into the parent's session GROUP and replayed each with its
own fresh context; a subagent's identical re-read of a file the orchestrator (or a sibling) already
fetched lands in the cross-agent bucket, since the subagent paid full tokens for bytes the group
already knew. Codex/main-only files (no `subagents` path segment) are single-agent groups.

Usage:  python -m benchmarks.session_reuse_audit <dir> [--days N] [--md OUT.md]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional, accurate tokenizer
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def _tok(s: str) -> int:
        return len(_ENC.encode(s))

    TOKENIZER = "tiktoken/cl100k_base"
except Exception:  # dependency-light fallback

    def _tok(s: str) -> int:
        return max(1, len(s) // 4)

    TOKENIZER = "approx(chars/4)"

READ_TOOLS = {"Read", "Grep", "Glob"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Expensive processes whose result is reproducible from source state -- the canary's domain. A
# re-run with no SOURCE change since the last run (by this agent, or by another agent in the group)
# is redundant: a shared outcome cache could serve the prior result instead of re-executing.
_EXPENSIVE = {
    "pytest", "ruff", "mypy", "benchmark", "tox", "cargo", "make", "npm", "pnpm", "yarn",
    "go", "jest", "vitest", "python", "python3", "uv",
}
# Over-fetch: a Read followed by Edit(s) to that file. "used" = edited old_string tokens x BUFFER
# (buffer credits the surrounding context needed to make the edit; a larger buffer SHRINKS the
# over-fetch claim). over-fetch = read_tokens - used, the part a targeted retrieval could have
# omitted. A larger buffer is the conservative choice; 3x is the reported default.
_OVERFETCH_BUFFER = 3
_SRC_EXT = {
    "py", "js", "ts", "tsx", "jsx", "go", "rs", "java", "rb", "c", "cpp", "cc", "h", "hpp",
    "sh", "sql", "vue", "svelte", "css", "html",
}


def _file_class(path: str) -> str:
    """Coarse class of a read file, to split the Unknown bucket (source = the over-fetch candidate;
    log/output = polling, not reducible)."""
    p = path.lower()
    ext = p.rsplit(".", 1)[-1] if "." in p else ""
    if ext in {"output", "log"} or ".output" in p:
        return "log/output"
    if ext in _SRC_EXT:
        return "source"
    if ext in {"md", "rst", "txt"}:
        return "doc"
    if ext in {"json", "yaml", "yml", "toml", "cfg", "ini", "env", "lock"}:
        return "config"
    if ext in {"csv", "jsonl", "tsv", "parquet"}:
        return "data"
    if ext in {"png", "jpg", "jpeg", "svg", "gif", "webp", "pdf"}:
        return "image"
    return "other"
_MUTATE = re.compile(
    r"(>>?|\bsed -i|\btee |\brm |\bmv |\bcp |\bmkdir|\btouch |"
    r"\bgit (add|commit|checkout|reset|merge|rebase|stash|restore)|"
    r"\b(pip|uv|npm|pnpm|yarn|cargo|maturin) )"
)


def _bash_mutates(cmd: str) -> bool:
    return bool(_MUTATE.search(cmd))


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _is_prompt(content: object) -> bool:
    """A real user prompt (turn boundary), not a tool_result message."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        has_result = any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
        return not has_result and len(content) > 0
    return False


@dataclass
class Prompt:
    text: str


@dataclass
class Call:
    name: str
    key: str | None  # file_path (reads) or command (bash); None otherwise
    sha: str | None  # content hash of a read's bytes
    mutates: bool
    tokens: int  # result tokens (reads: bytes returned)
    span: int = 0  # for Edit/MultiEdit: tokens of the edited old_string(s) -- the "used" region


def _parse_claude(path: Path) -> list[Prompt | Call]:
    """One Claude session -> ordered Prompt / Call stream. Pairs tool_use to tool_result by id."""
    out: list[Prompt | Call] = []
    pending: dict[str, tuple[str, str | None, bool, int]] = {}  # id -> (name, key, mutates, span)
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if ev.get("type") == "user" and _is_prompt(content):
            out.append(Prompt(_text(content)))
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "tool_use":
                name = str(b.get("name") or "")
                raw_in = b.get("input")
                inp = raw_in if isinstance(raw_in, dict) else {}
                key: str | None = None
                mutates = name in EDIT_TOOLS
                span = 0
                if name in READ_TOOLS:
                    key = inp.get("file_path") or inp.get("path") or inp.get("pattern")
                elif name == "Bash":
                    key = inp.get("command")
                    mutates = bool(key) and _bash_mutates(str(key))
                elif name in EDIT_TOOLS:
                    key = inp.get("file_path")
                    if name == "MultiEdit":  # sum each sub-edit's old_string
                        span = _tok(" ".join(
                            e.get("old_string", "") for e in inp.get("edits", [])
                            if isinstance(e, dict)
                        ))
                    else:  # Edit has old_string; Write replaces wholesale (no edited span)
                        span = _tok(str(inp.get("old_string") or ""))
                if b.get("id"):
                    pending[b["id"]] = (name, str(key) if key else None, mutates, span)
            elif t == "tool_result":
                uid = b.get("tool_use_id")
                if uid in pending:
                    name, key, mutates, span = pending.pop(uid)
                    txt = _text(b.get("content"))
                    sha = (
                        hashlib.sha256(txt.encode()).hexdigest()
                        if name in READ_TOOLS and txt
                        else None
                    )
                    out.append(Call(name, key, sha, mutates, _tok(txt), span))
    return out


_READ_HEADS = {"cat", "head", "tail", "sed", "less", "bat", "nl"}
_TOKCOUNT_RE = re.compile(r"Original token count:\s*(\d+)")


def _codex_cmd(args_raw: object) -> str | None:
    if not isinstance(args_raw, str):
        return None
    try:
        a = json.loads(args_raw)
    except json.JSONDecodeError:
        return args_raw or None
    if isinstance(a, dict):
        c = a.get("cmd") or a.get("command")
        if isinstance(c, list):
            return str(c[-1]) if c else None
        return str(c) if c else None
    return None


def _codex_out_tokens(output: object) -> int:
    s = output if isinstance(output, str) else json.dumps(output)
    m = _TOKCOUNT_RE.search(s)  # Codex exec wrapper reports the true pre-truncation size
    return int(m.group(1)) if m else _tok(s)


def _strip_cd(cmd: str) -> str:
    c = cmd.strip()
    while True:
        nxt = _CD_PREFIX.sub("", c)
        if nxt == c:
            return c
        c = nxt


def _codex_head(cmd: str) -> str:
    return _strip_cd(cmd).split("&&", 1)[0].strip().split(" ", 1)[0].rsplit("/", 1)[-1]


def _parse_codex(path: Path) -> list[Prompt | Call]:
    """One Codex (Responses-API) session -> Prompt / Call stream. Codex reads via shell, so
    cat/sed/head/tail are normalized to Read and apply_patch to a mutation. Reads carry no sha
    (the exec wrapper varies per call), so audit() gates Codex reads on no-mutation-since."""
    out: list[Prompt | Call] = []
    pending: dict[str, str] = {}  # call_id -> cmd
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        p = ev.get("payload")
        if not isinstance(p, dict):
            continue
        et, pt = ev.get("type"), p.get("type")
        if et == "event_msg" and pt == "user_message":
            msg = p.get("message")
            if isinstance(msg, str) and msg.strip():
                out.append(Prompt(msg))
        elif et == "response_item" and pt == "function_call":
            cmd = _codex_cmd(p.get("arguments"))
            cid = p.get("call_id")
            if cid and cmd:
                pending[str(cid)] = cmd
        elif et == "response_item" and pt == "function_call_output":
            cid = str(p.get("call_id"))
            cmd = pending.pop(cid, None)
            if cmd:
                tokens = _codex_out_tokens(p.get("output"))
                if _codex_head(cmd) in _READ_HEADS:
                    # key on the full read command so `cat X` and `sed -n X` differ; the no-
                    # mutation gate then flags only true identical re-reads.
                    out.append(Call("Read", _sig(cmd), None, False, tokens))
                else:
                    out.append(Call("Bash", cmd, None, _bash_mutates(cmd), tokens))
        elif et == "response_item" and pt == "custom_tool_call":
            if "patch" in str(p.get("name") or "").lower():
                out.append(Call("Edit", None, None, True, 0))  # apply_patch = mutation
    return out


def parse(path: Path, fmt: str = "auto") -> list[Prompt | Call]:
    """Dispatch to the right transcript parser. ``auto`` sniffs the first event: Codex events
    carry a top-level ``payload``; Claude events carry ``message``."""
    if fmt == "claude":
        return _parse_claude(path)
    if fmt == "codex":
        return _parse_codex(path)
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and "payload" in ev:
            return _parse_codex(path)
        if isinstance(ev, dict) and "message" in ev:
            return _parse_claude(path)
    return _parse_claude(path)


@dataclass
class Audit:
    sessions: int = 0  # session GROUPS (a main agent + its subagents = one group)
    subagents: int = 0  # subagent transcripts ingested across all groups
    read_tokens: int = 0
    reuse_in: int = 0  # within-agent identical re-read tokens (free, already in context)
    reuse_xagent: int = 0  # cross-agent: a subagent re-read what its group already had (memory opp)
    reuse_x: int = 0  # cross-session identical re-read tokens (conditional)
    proc_runs: dict[str, int] = field(default_factory=dict)
    proc_redundant: dict[str, int] = field(default_factory=dict)
    # per-role splits (main agent vs subagent) for the agent/subagent grid
    main_read: int = 0
    sub_read: int = 0
    main_reuse: int = 0  # reusable re-read tokens where the re-reader was the main agent
    sub_reuse: int = 0  # ... a subagent (its reuse_xagent slice is the memory opportunity)
    main_runs: int = 0
    sub_runs: int = 0
    main_redundant: int = 0
    sub_redundant: int = 0
    # outcome-reuse / canary lever: expensive re-runs with no SOURCE change since (process-level)
    main_exp_runs: int = 0
    sub_exp_runs: int = 0
    main_exp_reuse: int = 0  # within-agent canary: this agent re-ran it with no own source change
    sub_exp_reuse: int = 0
    exp_xagent: int = 0  # cross-agent canary: a later agent re-ran what another already ran (no
    # group source change since) -- the outcome-memory analog of cross-agent reads
    # over-fetch lever: of a Read followed by an Edit to that file, how much was NOT near the edit
    of_anchored: int = 0  # Read tokens that had >=1 downstream Edit to the same file
    of_necessary: int = 0  # of those, min(read, edited_span x BUFFER) -- credited as used
    of_over: int = 0  # of_anchored - of_necessary -- reducible by targeted retrieval
    of_unknown: int = 0  # Read tokens with NO downstream edit (read to understand; NOT waste)
    of_unknown_by_class: dict[str, int] = field(default_factory=dict)  # Unknown tokens per class
    questions: int = 0
    q_no_work: int = 0  # conversational; answered from context
    q_cache: int = 0  # all answer-work was redundant -> answerable from context
    q_partial: int = 0
    q_new: int = 0  # genuinely needed new info
    q_redundant_tokens: int = 0  # reducible tokens in answer-work
    q_cross: int = 0  # work-questions that re-acquired a PRIOR session's content
    q_cross_tokens: int = 0  # of those, the cross-session re-acquired tokens


_TRIVIAL_HEADS = {
    "cd", "export", "pwd", "ls", "cat", "echo", "tail", "head", "sleep", "true",
    "false", ":", "", "which", "env", "source", "set", "clear", "wc", "date",
    "mkdir", "touch", "printf",
}
_CD_PREFIX = re.compile(r"^\s*cd\s+[^&;]+&&\s*")


def _proc(cmd: str) -> str | None:
    """Substantive process head of a command (basename), or None for pure-trivial commands
    (cd/echo/ls/...) so navigation noise does not dominate the redundancy ranking."""
    c = cmd.strip()
    while True:
        nxt = _CD_PREFIX.sub("", c)
        if nxt == c:
            break
        c = nxt
    head = c.split("&&", 1)[0].strip().split(" ", 1)[0].rsplit("/", 1)[-1]
    return head if head and head not in _TRIVIAL_HEADS else None


def _sig(cmd: str) -> str:
    """Normalized FULL-command signature for redundancy, so `git status` and `git diff` are
    different operations (keying on the binary alone wildly over-counts git/rg/uv re-runs)."""
    return re.sub(r"\s+", " ", _strip_cd(cmd).strip())


def _bucket(
    a: Audit, work: int, redundant: int, red_tok: int, red_x: int, red_x_tok: int
) -> None:
    """Classify one finished user question by its answer-work."""
    a.questions += 1
    if work == 0:
        a.q_no_work += 1  # conversational; answered from context
    elif redundant == work:
        a.q_cache += 1  # all answer-work was re-acquisition -> answerable from context
    elif redundant > 0:
        a.q_partial += 1
    else:
        a.q_new += 1  # genuinely needed new info
    a.q_redundant_tokens += red_tok
    if red_x > 0:  # some answer-work re-acquired content first seen in a PRIOR session
        a.q_cross += 1
        a.q_cross_tokens += red_x_tok


@dataclass
class _Group:
    gid: str
    mtime: float
    agents: list[tuple[str, Path, bool]]  # (agent_id, path, is_sub); main agent first


@dataclass
class _GState:
    """Group-level clock shared across a group's agents, for the cross-agent canary. ``seq`` is a
    monotonic event counter spanning all agents (processed main-first); ``last_mut`` is the group's
    most recent source mutation; ``proc_last`` maps a full-command sig to (seq, agent_id) of its
    last run by ANY agent. A run is cross-agent redundant if a different agent ran the same command
    with no group mutation since."""
    seq: int = 0
    last_mut: int = 0
    proc_last: dict[str, tuple[int, str]] = field(default_factory=dict)


def _group(paths: list[Path]) -> list[_Group]:
    """Bundle a main session file with its subagent transcripts into one ordered group.

    Claude writes subagents to ``<session-id>/subagents/agent-*.jsonl`` next to the main
    ``<session-id>.jsonl``; the directory name two levels up is the parent session id. Files with
    no ``subagents`` path segment (main Claude sessions, all Codex rollouts) become single-agent
    groups, so behavior is unchanged when no subagents exist. Groups are ordered oldest-first by the
    main file's mtime; within a group the main agent runs before its subagents."""
    by_gid: dict[str, list[tuple[str, Path, bool]]] = {}
    for p in paths:
        if "subagents" in p.parts:
            gid = p.parts[p.parts.index("subagents") - 1]
            by_gid.setdefault(gid, []).append((p.stem, p, True))
        else:
            by_gid.setdefault(p.stem, []).append(("main", p, False))
    groups: list[_Group] = []
    for gid, members in by_gid.items():
        members.sort(key=lambda m: (m[2], m[1].stat().st_mtime))  # main (False) first, then subs
        mains = [m for m in members if not m[2]]
        mtime = (mains[0] if mains else members[0])[1].stat().st_mtime
        groups.append(_Group(gid, mtime, members))
    groups.sort(key=lambda g: g.mtime)
    return groups


def _run_agent(
    a: Audit,
    events: list[Prompt | Call],
    *,
    agent_id: str,
    group_read: dict[str, str],
    g_read: dict[str, str],
    gstate: _GState,
    do_questions: bool,
    is_sub: bool,
) -> None:
    """Replay one agent's stream. ``group_read`` is shared across the group's agents, so a
    subagent's identical re-read of an orchestrator/sibling file lands in the cross-agent bucket.
    Each agent has its own fresh ``s_read`` (own context). ``gstate`` carries the group clock for
    the cross-agent canary. ``do_questions`` is True only for the main agent; subagents have no
    human turns, so they feed levers 1-2 but not answerability. ``is_sub`` routes tallies into the
    per-role splits for the agent/subagent grid."""
    s_read: dict[str, str] = {}  # this agent's own context (fresh per agent)
    read_last: dict[str, int] = {}  # path -> seq (Codex no-sha reads)
    proc_last: dict[str, int] = {}  # full-command sig -> seq (verbatim re-run gate)
    own_proc_last: dict[str, int] = {}  # expensive command sig -> seq (within-agent canary gate)
    open_read: dict[str, list[int]] = {}  # file -> [read_tokens, edited_span] (over-fetch)
    own_last_mut = 0  # this agent's most recent source mutation
    work = redundant = q_red_tok = redundant_x = q_red_x_tok = 0
    in_question = False
    for ev in events:
        if isinstance(ev, Prompt):
            if do_questions:
                if in_question:
                    _bucket(a, work, redundant, q_red_tok, redundant_x, q_red_x_tok)
                in_question = True
                work = redundant = q_red_tok = redundant_x = q_red_x_tok = 0
            continue
        gstate.seq += 1
        seq = gstate.seq  # one monotonic clock for the whole group (per-agent gates stay local)
        is_redundant = is_work = is_cross = False
        if ev.name in READ_TOOLS and ev.key:
            is_work = True
            a.read_tokens += ev.tokens
            if is_sub:
                a.sub_read += ev.tokens
            else:
                a.main_read += ev.tokens
            if ev.sha is not None:  # Claude: content-hash gate
                if s_read.get(ev.key) == ev.sha:
                    a.reuse_in += ev.tokens  # already in THIS agent's context = free
                    is_redundant = True
                elif group_read.get(ev.key) == ev.sha:
                    a.reuse_xagent += ev.tokens  # a sibling/orchestrator already had it
                    is_redundant = True
                elif g_read.get(ev.key) == ev.sha:
                    a.reuse_x += ev.tokens
                    is_redundant = is_cross = True
                s_read[ev.key] = ev.sha
                group_read[ev.key] = ev.sha
            else:  # Codex: re-read of the same path with no mutation since = redundant
                if ev.key in read_last and own_last_mut <= read_last[ev.key]:
                    a.reuse_in += ev.tokens
                    is_redundant = True
                read_last[ev.key] = seq
            if is_redundant:
                if is_sub:
                    a.sub_reuse += ev.tokens
                else:
                    a.main_reuse += ev.tokens
        elif ev.name == "Bash" and ev.key:
            p = _proc(ev.key)
            if p is not None:
                is_work = True
                sig = _sig(ev.key)  # redundancy keys on the FULL command, not the binary
                a.proc_runs[p] = a.proc_runs.get(p, 0) + 1
                if is_sub:
                    a.sub_runs += 1
                else:
                    a.main_runs += 1
                if sig in proc_last and own_last_mut <= proc_last[sig]:
                    a.proc_redundant[p] = a.proc_redundant.get(p, 0) + 1
                    is_redundant = True
                    if is_sub:
                        a.sub_redundant += 1
                    else:
                        a.main_redundant += 1
                proc_last[sig] = seq
                if p in _EXPENSIVE:  # canary: same command re-run with no source change since.
                    # Key on the full command sig, NOT the head: head-keying conflates distinct
                    # commands (python -c probe vs python -m pytest) and inflates this ~250x.
                    if is_sub:
                        a.sub_exp_runs += 1
                    else:
                        a.main_exp_runs += 1
                    prior = gstate.proc_last.get(sig)
                    if sig in own_proc_last and own_last_mut <= own_proc_last[sig]:
                        if is_sub:  # within-agent: this agent re-ran the same command, no change
                            a.sub_exp_reuse += 1
                        else:
                            a.main_exp_reuse += 1
                    elif prior is not None and prior[1] != agent_id and gstate.last_mut <= prior[0]:
                        a.exp_xagent += 1  # another agent already ran the same command, no change
                    own_proc_last[sig] = seq
                    gstate.proc_last[sig] = (seq, agent_id)
        if ev.mutates:
            own_last_mut = seq
            gstate.last_mut = seq
        # over-fetch: a full-file Read, later anchored by Edit(s) to that file
        if ev.name == "Read" and ev.key:
            if ev.key in open_read:
                _finalize_overfetch(a, ev.key, open_read.pop(ev.key))
            open_read[ev.key] = [ev.tokens, 0]
        elif ev.name in EDIT_TOOLS and ev.key and ev.key in open_read:
            open_read[ev.key][1] += ev.span
        if do_questions and in_question and is_work:  # attribute answer-work to the question
            work += 1
            if is_redundant:
                redundant += 1
                q_red_tok += ev.tokens
                if is_cross:
                    redundant_x += 1
                    q_red_x_tok += ev.tokens
    if do_questions and in_question:
        _bucket(a, work, redundant, q_red_tok, redundant_x, q_red_x_tok)
    for key, rec in open_read.items():  # files read but not re-read before the agent ended
        _finalize_overfetch(a, key, rec)


def _finalize_overfetch(a: Audit, key: str, rec: list[int]) -> None:
    """A Read with downstream edits is anchored; the rest of the file (read - used x BUFFER) is
    over-fetch. A Read with no downstream edit is Unknown (read to understand, not waste)."""
    read_tok, used = rec
    if used == 0:
        a.of_unknown += read_tok
        cls = _file_class(key)
        a.of_unknown_by_class[cls] = a.of_unknown_by_class.get(cls, 0) + read_tok
        return
    necessary = min(read_tok, used * _OVERFETCH_BUFFER)
    a.of_anchored += read_tok
    a.of_necessary += necessary
    a.of_over += read_tok - necessary


def audit(paths: list[Path], fmt: str = "auto") -> Audit:
    a = Audit()
    g_read: dict[str, str] = {}  # path -> sha promoted from a PRIOR group (cross-session)
    for grp in _group(paths):
        group_read: dict[str, str] = {}  # shared across this group's agents (cross-agent reads)
        gstate = _GState()  # shared clock for the cross-agent canary
        counted = False
        for agent_id, path, is_sub in grp.agents:
            events = parse(path, fmt)
            if not events:
                continue
            if not counted:
                a.sessions += 1  # count the group once, on its first non-empty agent
                counted = True
            if is_sub:
                a.subagents += 1
            _run_agent(
                a, events, agent_id=agent_id, group_read=group_read, g_read=g_read,
                gstate=gstate, do_questions=not is_sub, is_sub=is_sub,
            )
        g_read.update(group_read)  # the whole group's reads become "prior" for later groups
    return a


def render(a: Audit, target: str) -> str:
    L: list[str] = []
    L.append(f"# Session reuse audit: {target}\n")
    sub = f" (+{a.subagents} subagent transcripts)" if a.subagents else ""
    L.append(f"{a.sessions} session groups{sub} analyzed. Tokenizer: {TOKENIZER}.\n")

    runs = sum(a.proc_runs.values())
    red = sum(a.proc_redundant.values())
    L.append("## 1. Redundant tool calls (re-run, no mutation since last run)")
    L.append("| process | runs | redundant | % |")
    L.append("| --- | --- | --- | --- |")
    top = sorted(a.proc_runs.items(), key=lambda kv: -kv[1])[:10]
    for p, n in top:
        r = a.proc_redundant.get(p, 0)
        L.append(f"| {p[:20]} | {n} | {r} | {100 * r / max(n, 1):.0f}% |")
    L.append(f"| **all** | **{runs}** | **{red}** | **{100 * red / max(runs, 1):.1f}%** |\n")

    reuse = a.reuse_in + a.reuse_xagent + a.reuse_x
    L.append("## 2. Context reuse (identical-byte re-reads, hash-gated)")
    L.append(f"read tokens: {a.read_tokens:,}")
    L.append(
        f"reusable: {reuse:,} ({100 * reuse / max(a.read_tokens, 1):.1f}%) "
        f"= within-agent/free {a.reuse_in:,} + cross-agent/memory {a.reuse_xagent:,} "
        f"+ cross-session/conditional {a.reuse_x:,}\n"
    )
    if a.subagents:
        L.append(
            f"Cross-agent: {a.reuse_xagent:,} tokens were re-read by a subagent in fresh context "
            f"after the orchestrator (or a sibling) had already fetched the identical bytes -- the "
            f"reuse a shared memory layer could serve instead of a full re-read.\n"
        )

    L.append("## 3. Question answerability (could the user's turn be answered from context?)")
    L.append("| bucket | questions |")
    L.append("| --- | --- |")
    L.append(f"| needed new info | {a.q_new} |")
    L.append(f"| answerable from context (all answer-work redundant) | {a.q_cache} |")
    L.append(f"| partial (some redundant answer-work) | {a.q_partial} |")
    L.append(f"| conversational (no tool calls) | {a.q_no_work} |")
    work_q = a.questions - a.q_no_work
    L.append(f"| **total** | **{a.questions}** |")
    L.append(
        f"\n{a.q_no_work} turns were conversational (no tools). Of the {work_q} that drove tool "
        f"work, {a.q_cache} were fully answerable from context (all answer-work redundant) and "
        f"{a.q_partial} partial; ~{a.q_redundant_tokens:,} tokens of answer-work were redundant "
        f"re-acquisition.\n"
    )
    L.append(
        f"Cross-session: {a.q_cross} of those work-turns re-acquired content first seen in an "
        f"EARLIER session (~{a.q_cross_tokens:,} tokens) -- the answer was partly available from a "
        f"prior session. (File re-reads only; command re-runs and question-to-answer matching are "
        f"not measured.)\n"
    )

    of_read = a.of_anchored + a.of_unknown
    of_pct = 100 * a.of_over / max(a.of_anchored, 1)
    unk_pct = 100 * a.of_unknown / max(of_read, 1)
    L.append("## 4. Over-fetch (Read tokens not near a downstream edit) -- inference-token lever")
    L.append(f"Read-tool tokens: {of_read:,}  (edit-anchored {a.of_anchored:,}, "
             f"Unknown/understanding {a.of_unknown:,})")
    L.append(
        f"Within edit-anchored reads (used = edited span x{_OVERFETCH_BUFFER}): "
        f"**over-fetch {a.of_over:,} ({of_pct:.0f}% of anchored)**, necessary {a.of_necessary:,}. "
        f"Reducible by targeted retrieval (serve the span, not the whole file) -- and it is "
        f"inference tokens on the FIRST read, not data movement on a repeat.\n"
    )
    L.append(
        f"The {a.of_unknown:,} Unknown tokens ({unk_pct:.0f}% of reads) had no downstream edit -- "
        f"read to understand. NOT counted as waste: agents paraphrase, so non-use leaves no trace. "
        f"Settling whether THOSE are over-fetched needs a counterfactual (span+summary vs full "
        f"file on real tasks), not this static auditor.\n"
    )
    if a.of_unknown_by_class:
        L.append("Unknown by file class (source read-once = the real over-fetch candidate; "
                 "log/output = polling, not reducible):")
        L.append("| class | tokens | % of Unknown |")
        L.append("| --- | --- | --- |")
        for c, t in sorted(a.of_unknown_by_class.items(), key=lambda kv: -kv[1]):
            L.append(f"| {c} | {t:,} | {100 * t / max(a.of_unknown, 1):.0f}% |")
        L.append("")

    L.append("## Caveats")
    L.append("- Change-gated: post-edit re-reads/re-runs are NOT counted (legitimate work).")
    L.append("- Over-fetch is the realer (inference-token) lever; re-read reuse (sections 2-3) is "
             "mostly DATA MOVEMENT (same bytes, different source). Over-fetch anchors on Edit/"
             "MultiEdit old_string (Write/Codex-patch carry no span, so they land in Unknown).")
    L.append("- 'Answerable from context' = the answer-work was redundant re-fetch; it measures "
             "the wasted re-fetch, not proof a model could answer with zero context.")
    L.append("- Token axis only; within-agent reuse is free (already in context), cross-agent and "
             "cross-session save only if a bounded summary/span suffices (else same bytes from a "
             "different source). Cross-agent is the subagent case: fresh context, so unlike a "
             "main-agent re-read it is NOT already in the window.")
    return "\n".join(L)


def _combine(audits: list[Audit]) -> Audit:
    """Sum per-project Audits for the combined-totals row (scalar fields add; proc dicts merge).
    Cross-session reuse is meaningless across unrelated repos, so we sum the per-role tallies
    rather than re-running audit over a mixed path list."""
    import dataclasses

    c = Audit()
    for a in audits:
        for f in dataclasses.fields(Audit):
            v = getattr(a, f.name)
            if isinstance(v, int):
                setattr(c, f.name, getattr(c, f.name) + v)
            elif isinstance(v, dict):
                d = getattr(c, f.name)
                for k, n in v.items():
                    d[k] = d.get(k, 0) + n
    return c


def _grid_block(label: str, a: Audit) -> list[str]:
    """One project's lever grid, each row split main agent / subagents / combined."""

    def pc(r: int, n: int) -> str:
        return f"{r}/{n} ({100 * r / max(n, 1):.0f}%)"

    def rpc(reuse: int, read: int) -> str:
        return f"{reuse:,} ({100 * reuse / max(read, 1):.1f}%)"

    total_reuse = a.reuse_in + a.reuse_xagent + a.reuse_x
    work_q = a.questions - a.q_no_work
    L = [
        f"### {label}  ({a.sessions} groups, {a.subagents} subagents)",
        "",
        "| lever | main agent | subagents | combined |",
        "| --- | --- | --- | --- |",
        f"| Redundant tool calls (verbatim floor) | {pc(a.main_redundant, a.main_runs)} "
        f"| {pc(a.sub_redundant, a.sub_runs)} "
        f"| {pc(a.main_redundant + a.sub_redundant, a.main_runs + a.sub_runs)} |",
        f"| Read tokens (denominator) | {a.main_read:,} | {a.sub_read:,} | {a.read_tokens:,} |",
        f"| Context reuse: reusable re-reads (mech 3) | {rpc(a.main_reuse, a.main_read)} "
        f"| {rpc(a.sub_reuse, a.sub_read)} | {rpc(total_reuse, a.read_tokens)} |",
        f"| -- of which cross-agent / memory opp (mech 6) | -- | {a.reuse_xagent:,} "
        f"| {a.reuse_xagent:,} |",
        f"| Outcome reuse / canary: expensive re-run, no source change (mech 2) "
        f"| {pc(a.main_exp_reuse, a.main_exp_runs)} | {pc(a.sub_exp_reuse, a.sub_exp_runs)} "
        f"| {pc(a.main_exp_reuse + a.sub_exp_reuse, a.main_exp_runs + a.sub_exp_runs)} |",
        f"| -- of which cross-agent (a sibling/orchestrator already ran it) | -- | {a.exp_xagent} "
        f"| {a.exp_xagent} |",
        f"| **Over-fetch** (edit-anchored reads, used x{_OVERFETCH_BUFFER}) -- inference tokens "
        f"| -- | -- | {a.of_over:,} ({100 * a.of_over / max(a.of_anchored, 1):.0f}% of "
        f"{a.of_anchored:,} anchored; {a.of_unknown:,} Unknown) |",
        f"| Questions answerable from ctx | {a.q_cache}/{work_q} | -- | {a.q_cache}/{work_q} |",
        "",
    ]
    return L


def render_grid(results: list[tuple[str, Audit]]) -> str:
    """Agent/subagent lever grid across one or more projects, plus a combined-totals block."""
    L = [
        "# Agent / subagent reuse grid",
        "",
        "Each lever split by who did the work: the main (orchestrator) agent vs its subagents, "
        "which run in FRESH context. Mechanisms 1 (intent routing) and 4 (procedure recall) are "
        "qualitative / cross-session and do not split by agent; see the prose measurement doc.",
        "",
        "Note: the 'redundant tool calls' row keys on the EXACT command string + no-mutation gate, "
        "so it is a verbatim-re-run floor (~0%); it is NOT the outcome-reuse/canary lever, which "
        "gates on whether the SOURCE changed (process-level), ~19-29%. See mechanism 2 in the doc.",
        "",
    ]
    for label, a in results:
        L += _grid_block(Path(label).name, a)
    if len(results) > 1:
        L += _grid_block("ALL PROJECTS COMBINED", _combine([a for _, a in results]))
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dir", help="directory of Claude .jsonl session files")
    ap.add_argument(
        "--days", type=float, default=None, help="only sessions modified in last N days"
    )
    ap.add_argument("--md", help="also write the report to this markdown file")
    ap.add_argument(
        "--format", default="auto", choices=["auto", "claude", "codex"],
        help="transcript format (auto-sniffs by default)",
    )
    ap.add_argument(
        "--grid", action="store_true",
        help="emit the agent/subagent lever grid instead of the prose report",
    )
    args = ap.parse_args()

    paths = sorted(Path(args.dir).rglob("*.jsonl"))  # recursive: Codex nests by YYYY/MM/DD
    if args.days is not None:
        cutoff = time.time() - args.days * 86400
        paths = [p for p in paths if p.stat().st_mtime >= cutoff]
    a = audit(paths, args.format)
    report = render_grid([(args.dir, a)]) if args.grid else render(a, args.dir)
    print(report)
    if args.md:
        Path(args.md).write_text(report + "\n")
        print(f"\n[written to {args.md}]")


if __name__ == "__main__":
    main()
