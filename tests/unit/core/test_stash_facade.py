import pytest

from stele import PIIBlockedError, Stele, StoredResult


def test_store_returns_compact_result() -> None:
    stash = Stele.from_config()

    result = stash.store("hello " * 1000)

    assert isinstance(result, StoredResult)
    assert result.reference.startswith("stele://")
    assert len(result.summary) < result.byte_size


def test_fetch_defaults_to_scrubbed_content() -> None:
    stash = Stele.from_config({"pii": {"enabled": True}})  # scrubbing is opt-in
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


# --- Phase 4: mode dispatch + chunk store + indexing_status wiring (T21) ---

import time  # noqa: E402

from stele import CapabilityError  # noqa: E402


def _sync_memory() -> Stele:
    return Stele.from_config(
        {"backend": {"type": "memory"}, "indexing": {"mode": "sync"}}
    )


def test_vector_mode_dispatch() -> None:
    stash = _sync_memory()
    stored = stash.store("the user strongly prefers dark mode dashboards", namespace="n")
    hits = stash.search(stored.reference, "dark mode", mode="vector")
    assert hits
    assert all(h.retrieval_mode == "vector" for h in hits)
    stash.close()


def test_hybrid_mode_dispatch() -> None:
    stash = _sync_memory()
    stored = stash.store("rebuild the postgres index to fix the deployment", namespace="n")
    hits = stash.search(stored.reference, "postgres index", mode="hybrid")
    assert hits
    assert hits[0].retrieval_mode == "hybrid"
    stash.close()


def test_default_mode_drives_dispatch() -> None:
    stash = Stele.from_config(
        {
            "backend": {"type": "memory"},
            "indexing": {"mode": "sync"},
            "retrieval": {"default_mode": "vector"},
        }
    )
    stored = stash.store("semantic vector retrieval over chunks", namespace="n")
    hits = stash.search(stored.reference, "vector retrieval")  # no explicit mode
    assert hits
    assert all(h.retrieval_mode == "vector" for h in hits)
    stash.close()


def test_vector_mode_without_chunk_store_raises() -> None:
    stash = Stele.from_config({"indexing": {"mode": "skip"}})  # no chunk store
    stored = stash.store("some text")
    with pytest.raises(CapabilityError):
        stash.search(stored.reference, "text", mode="vector")
    stash.close()


def test_indexing_status_sync() -> None:
    stash = _sync_memory()
    stored = stash.store("indexed synchronously", namespace="n")
    result = stash.indexing_status(stored.artifact_id)
    assert result.status == "indexed"
    stash.close()


def test_async_store_returns_immediately_and_transitions() -> None:
    stash = Stele.from_config(
        {"backend": {"type": "memory"}, "indexing": {"mode": "async"}}
    )
    stored = stash.store("asynchronously indexed content about kafka streams", namespace="n")
    assert stored.index_status in {"queued", "indexed"}
    # Searching before indexing completes must not raise.
    stash.search(stored.reference, "kafka", mode="vector")
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if stash.indexing_status(stored.artifact_id).status == "indexed":
            break
        time.sleep(0.02)
    assert stash.indexing_status(stored.artifact_id).status == "indexed"
    hits = stash.search(stored.reference, "kafka streams", mode="vector")
    assert hits
    stash.close()  # must close the task backend without raising
