import pytest

from stele import PIIBlockedError, Stele, StoredResult


def test_store_returns_compact_result() -> None:
    stash = Stele.from_config()

    result = stash.store("hello " * 1000)

    assert isinstance(result, StoredResult)
    assert result.reference.startswith("stele://")
    assert len(result.summary) < result.byte_size


def test_fetch_defaults_to_scrubbed_content() -> None:
    stash = Stele.from_config()
    stored = stash.store("Email alice@example.com for details.")

    fetched = stash.fetch(stored.reference)

    assert "alice@example.com" not in str(fetched.content)
    assert "[EMAIL_1]" in str(fetched.content)


def test_raw_fetch_requires_config_opt_in() -> None:
    stash = Stele.from_config()
    stored = stash.store("Email alice@example.com for details.")

    with pytest.raises(PIIBlockedError):
        stash.fetch(stored.reference, raw=True)


def test_raw_fetch_when_enabled_returns_exact_content() -> None:
    stash = Stele.from_config({"pii": {"raw_fetch_enabled": True}})
    stored = stash.store("Email alice@example.com for details.")

    assert stash.fetch(stored.reference, raw=True).content == "Email alice@example.com for details."
