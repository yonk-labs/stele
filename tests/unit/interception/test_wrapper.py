from stele import Stele
from stele.interception.wrapper import stash_tool_result


def test_below_threshold_passes_through() -> None:
    stash = Stele.from_config(
        {"interception": {"min_chars": 1000, "min_estimated_tokens": 1000}}
    )

    result = stash_tool_result("short", stash=stash)

    assert result == "short"


def test_large_output_is_replaced_and_scrubbed() -> None:
    stash = Stele.from_config(
        {
            "interception": {"min_chars": 100, "min_estimated_tokens": 25},
            "pii": {"enabled": True},  # scrubbing is opt-in
        }
    )
    raw = "alice@example.com " + ("database row " * 100)

    result = stash_tool_result(raw, stash=stash, namespace="ops")

    assert isinstance(result, str)
    assert "stele://ops/" in result
    assert "alice@example.com" not in result
    assert "[EMAIL_1]" in result
