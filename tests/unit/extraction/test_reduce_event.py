"""reduce_event: the single per-event reduction filter shared by the live ingest
stream and the batch .jsonl parser. Locks the measured keep120 behavior:
successful results kept truncated (not dropped), failures kept longer, signatures
and non-conversation lines dropped, role + is_error preserved for windowing."""

from __future__ import annotations

from typing import Any

from stele.extraction.session import ReduceConfig, reduce_event


def _result(content: str, is_error: bool = False) -> dict[str, Any]:
    return {"type": "assistant",
            "message": {"content": [{"type": "tool_result", "content": content,
                                     "is_error": is_error}]}}


def test_keep120_truncates_successful_result_to_result_chars() -> None:
    [t] = reduce_event(_result("X" * 500))
    assert t.role == "result" and not t.is_error
    assert len(t.text) == 120  # default keep120: headline kept, body dropped


def test_failures_keep_more_than_successes() -> None:
    [t] = reduce_event(_result("E" * 500, is_error=True))
    assert t.is_error and len(t.text) == 220  # errors are the rule signal


def test_result_chars_is_configurable() -> None:
    [t] = reduce_event(_result("X" * 500), ReduceConfig(result_chars=300))
    assert len(t.text) == 300
    [t2] = reduce_event(_result("X" * 500), ReduceConfig(result_chars=40))
    assert len(t2.text) == 40


def test_drop_success_results_is_opt_in_minify() -> None:
    assert reduce_event(_result("ok output"))                       # kept by default
    assert reduce_event(_result("ok output"), ReduceConfig(drop_success_results=True)) == []
    # errors survive even in drop-success (minify) mode
    assert reduce_event(_result("boom", is_error=True),
                        ReduceConfig(drop_success_results=True))


def test_thinking_signature_dropped_text_kept() -> None:
    sig_only = {"type": "assistant",
                "message": {"content": [{"type": "thinking", "thinking": "",
                                         "signature": "B64" * 500}]}}
    assert reduce_event(sig_only) == []  # empty thinking + signature -> nothing
    with_text = {"type": "assistant",
                 "message": {"content": [{"type": "thinking", "thinking": "real reasoning",
                                          "signature": "sig"}]}}
    [t] = reduce_event(with_text)
    assert t.text == "real reasoning"  # text kept, signature never emitted


def test_non_conversation_lines_dropped() -> None:
    for typ in ("file-history-snapshot", "attachment", "system", "summary", "pr-link"):
        assert reduce_event({"type": typ, "payload": "x" * 1000}) == []


def test_system_reminder_user_strings_skipped() -> None:
    assert reduce_event({"type": "user",
                         "message": {"content": "<system-reminder>x</system-reminder>"}}) == []
    [t] = reduce_event({"type": "user", "message": {"content": "real question"}})
    assert t.role == "user" and t.text == "real question"


def test_role_and_is_error_preserved_for_windowing() -> None:
    ev = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "trying a build"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "cargo build"}},
        {"type": "tool_result", "content": "error[E0432]", "is_error": True},
    ]}}
    turns = reduce_event(ev)
    assert [t.role for t in turns] == ["assistant", "tool", "result"]
    assert turns[1].text.startswith("Bash(")
    assert turns[2].is_error  # failure-first windowing depends on this
