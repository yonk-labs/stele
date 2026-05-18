from stele.runtime.health import AdapterHealth, build_health


def test_all_available_is_healthy() -> None:
    h = build_health(
        exact_store_available=True, memory_store_available=True,
        index_available=True, recall_available=True, pii_mode="scrub",
    )
    assert isinstance(h, AdapterHealth)
    assert h.status == "healthy"
    assert h.degraded_reason is None
    assert h.capabilities["recall"] is True


def test_missing_dependency_is_explicit() -> None:
    h = build_health(
        exact_store_available=True, memory_store_available=True,
        index_available=False, recall_available=True, pii_mode="scrub",
        missing_dependency="chunkshop",
    )
    assert h.status == "missing_dependency"
    assert h.degraded_reason and "chunkshop" in h.degraded_reason


def test_degraded_recall_does_not_pretend_healthy() -> None:
    h = build_health(
        exact_store_available=True, memory_store_available=True,
        index_available=True, recall_available=False, pii_mode="scrub",
    )
    assert h.status == "degraded"  # never silently "healthy"
    assert h.degraded_reason


def test_disabled_and_queue_depth() -> None:
    h = build_health(
        exact_store_available=False, memory_store_available=False,
        index_available=False, recall_available=False, pii_mode="off",
        disabled=True, pending_queue_depth=7,
    )
    assert h.status == "disabled"
    assert h.pending_queue_depth == 7


def test_stale_index_reported() -> None:
    h = build_health(
        exact_store_available=True, memory_store_available=True,
        index_available=True, recall_available=True, pii_mode="scrub",
        stale_index=True,
    )
    assert h.status == "stale_index"
