"""Smoke test for the session reuse audit tool: crafted sessions exercise all three levers,
within-session and cross-session."""

from __future__ import annotations

import json
import os
from pathlib import Path

from benchmarks.session_reuse_audit import audit


def _user(text: str) -> dict[str, object]:
    return {"type": "user", "message": {"content": text}}


def _use(tid: str, name: str, inp: dict[str, str]) -> dict[str, object]:
    block = {"type": "tool_use", "id": tid, "name": name, "input": inp}
    return {"type": "assistant", "message": {"content": [block]}}


def _result(tid: str, content: str) -> dict[str, object]:
    block = {"type": "tool_result", "tool_use_id": tid, "content": content}
    return {"type": "user", "message": {"content": [block]}}


def _write(path: Path, events: list[dict[str, object]], mtime: float) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events))
    os.utime(path, (mtime, mtime))


def test_session_reuse_audit_levers(tmp_path: Path) -> None:
    events = [
        _user("Q1: read a"),
        _use("t1", "Read", {"file_path": "/a"}),
        _result("t1", "AAAAAAA"),  # new read -> Q1 needs new info
        _user("Q2: read a again"),
        _use("t2", "Read", {"file_path": "/a"}),
        _result("t2", "AAAAAAA"),  # identical re-read -> reuse_in; Q2 fully answerable
        _user("Q3: edit, reread, test twice"),
        _use("t3", "Edit", {"file_path": "/a"}),
        _result("t3", "done"),  # mutation
        _use("t4", "Read", {"file_path": "/a"}),
        _result("t4", "BBBBBBB"),  # changed bytes -> NOT reusable
        _use("t5", "Bash", {"command": "pytest -q"}),
        _result("t5", "ok"),  # first run
        _use("t6", "Bash", {"command": "pytest -q"}),
        _result("t6", "ok"),  # re-run, no mutation since -> redundant; Q3 partial
    ]
    sess = tmp_path / "s.jsonl"
    _write(sess, events, 1000.0)
    a = audit([sess])

    assert a.sessions == 1
    assert a.reuse_in > 0  # identical re-read counted; changed re-read not
    assert a.proc_runs.get("pytest") == 2
    assert a.proc_redundant.get("pytest") == 1
    assert a.q_new >= 1
    assert a.q_cache == 1
    assert a.q_partial == 1
    assert a.q_cross == 0  # single session, nothing cross-session
    # canary lever: pytest run twice with no source edit between the two runs -> within-agent reuse
    assert a.main_exp_runs == 2
    assert a.main_exp_reuse == 1
    assert a.exp_xagent == 0  # single agent, no cross-agent re-run


def _cx_user(text: str) -> dict[str, object]:
    return {"type": "event_msg", "payload": {"type": "user_message", "message": text}}


def _cx_exec(cid: str, cmd: str) -> dict[str, object]:
    payload = {"type": "function_call", "call_id": cid, "name": "exec_command",
               "arguments": json.dumps({"cmd": cmd})}
    return {"type": "response_item", "payload": payload}


def _cx_out(cid: str, output: str) -> dict[str, object]:
    return {"type": "response_item",
            "payload": {"type": "function_call_output", "call_id": cid, "output": output}}


def test_codex_format_adapter(tmp_path: Path) -> None:
    events = [
        {"type": "session_meta", "payload": {}},
        _cx_user("do it"),
        _cx_exec("c1", "cat /a"),
        _cx_out("c1", "Original token count: 100\nOutput:\nhello world"),  # a read, true size 100
        _cx_exec("c2", "pytest -q"),
        _cx_out("c2", "ok"),  # run 1
        _cx_exec("c3", "pytest -q"),
        _cx_out("c3", "ok"),  # identical re-run, no mutation since -> redundant
    ]
    sess = tmp_path / "rollout.jsonl"
    sess.write_text("\n".join(json.dumps(e) for e in events))
    a = audit([sess], fmt="codex")

    assert a.sessions == 1
    assert a.read_tokens == 100  # parsed from the exec wrapper's "Original token count"
    assert a.proc_runs.get("pytest") == 2
    assert a.proc_redundant.get("pytest") == 1  # full-command sig + no-mutation gate


def test_cross_session_answerability(tmp_path: Path) -> None:
    # session 1 reads /a; session 2's question re-reads the SAME unchanged /a -> the answer was
    # available from the earlier session.
    s1 = tmp_path / "s1.jsonl"
    s2 = tmp_path / "s2.jsonl"
    _write(s1, [_user("do work"), _use("t1", "Read", {"file_path": "/a"}),
               _result("t1", "AAAAAAA")], 1000.0)
    _write(s2, [_user("can this come from before?"), _use("t9", "Read", {"file_path": "/a"}),
               _result("t9", "AAAAAAA")], 2000.0)
    a = audit([s2, s1])  # pass out of order; audit sorts oldest-first by mtime

    assert a.sessions == 2
    assert a.reuse_x > 0  # cross-session identical re-read
    assert a.reuse_in == 0  # not a within-session repeat
    assert a.q_cross == 1  # session 2's question re-acquired session 1's content


def test_subagent_cross_agent_reuse(tmp_path: Path) -> None:
    # Main session reads /a; a subagent (separate fresh-context transcript under
    # <session>/subagents/) re-reads the SAME unchanged /a. That is cross-AGENT reuse: the subagent
    # paid full tokens for bytes the orchestrator already had -- NOT free (different context), NOT
    # cross-session (same group).
    main = tmp_path / "sess1.jsonl"
    sub_dir = tmp_path / "sess1" / "subagents"
    sub_dir.mkdir(parents=True)
    sub = sub_dir / "agent-aaa.jsonl"
    _write(main, [_user("read a"), _use("t1", "Read", {"file_path": "/a"}),
                  _result("t1", "AAAAAAA")], 1000.0)
    _write(sub, [_user("Task: inspect a"), _use("t2", "Read", {"file_path": "/a"}),
                 _result("t2", "AAAAAAA")], 1001.0)
    a = audit([main, sub])

    assert a.sessions == 1  # one group: main + its subagent
    assert a.subagents == 1
    assert a.reuse_xagent > 0  # subagent re-read what the orchestrator already had
    assert a.reuse_in == 0  # subagent's own context never repeated
    assert a.reuse_x == 0  # not cross-session; same group
    assert a.q_cross == 0  # subagents carry no user questions (do_questions off)
    # per-role split conservation (the grid relies on these adding up)
    assert a.main_read + a.sub_read == a.read_tokens
    assert a.main_reuse + a.sub_reuse == a.reuse_in + a.reuse_xagent + a.reuse_x
    assert a.sub_reuse == a.reuse_xagent and a.main_reuse == 0  # only the subagent re-read


def test_cross_agent_canary(tmp_path: Path) -> None:
    # Main agent runs pytest; a subagent re-runs pytest with NO source change since -> cross-agent
    # canary: a shared outcome cache could serve the orchestrator's result instead of re-executing.
    main = tmp_path / "sess1.jsonl"
    sub_dir = tmp_path / "sess1" / "subagents"
    sub_dir.mkdir(parents=True)
    sub = sub_dir / "agent-bbb.jsonl"
    _write(main, [_user("run tests"), _use("m1", "Bash", {"command": "pytest -q"}),
                  _result("m1", "ok")], 1000.0)
    _write(sub, [_user("Task: verify"), _use("s1", "Bash", {"command": "pytest -q"}),
                 _result("s1", "ok")], 1001.0)
    a = audit([main, sub])

    assert a.main_exp_runs == 1 and a.sub_exp_runs == 1
    assert a.exp_xagent == 1  # subagent re-ran what the orchestrator already ran, no source change
    assert a.main_exp_reuse == 0 and a.sub_exp_reuse == 0  # neither re-ran within its own context


def test_overfetch(tmp_path: Path) -> None:
    big = "\n".join(f"line {i} content here padding padding" for i in range(200))  # large file
    events = [
        _user("read big, edit one line"),
        _use("r1", "Read", {"file_path": "/big.py"}),
        _result("r1", big),  # large read
        _use("e1", "Edit", {"file_path": "/big.py",
                            "old_string": "line 5 content here padding padding"}),
        _result("e1", "done"),  # tiny edited span -> most of the read was over-fetch
        _user("read another, never edit it"),
        _use("r2", "Read", {"file_path": "/other.py"}),
        _result("r2", "some content read for understanding only"),  # no downstream edit -> Unknown
    ]
    sess = tmp_path / "s.jsonl"
    _write(sess, events, 1000.0)
    a = audit([sess])

    assert a.of_anchored > 0  # /big.py read was anchored by an edit
    assert a.of_over > 0  # most of the big read was not near the small edit
    assert a.of_over < a.of_anchored  # but some is credited necessary (span x buffer)
    assert a.of_unknown > 0  # /other.py read had no downstream edit
    assert a.of_unknown_by_class.get("source", 0) == a.of_unknown  # /other.py is .py = source
