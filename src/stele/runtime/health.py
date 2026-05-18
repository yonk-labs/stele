"""Adapter health contract (T-RAM-007).

Background memory must never silently degrade. ``build_health`` derives an
explicit status; degraded recall is never reported as healthy. Pure +
testable without a live LLM/provider.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, NamedTuple

HealthStatus = Literal[
    "healthy", "degraded", "disabled",
    "missing_dependency", "stale_index", "policy_blocked",
]


class AdapterHealth(NamedTuple):
    status: HealthStatus
    exact_store_available: bool
    memory_store_available: bool
    index_available: bool
    recall_available: bool
    pii_mode: str
    pending_queue_depth: int
    last_capture_at: datetime | None
    last_extract_at: datetime | None
    last_index_at: datetime | None
    last_recall_at: datetime | None
    degraded_reason: str | None
    capabilities: dict[str, bool]


def build_health(
    *,
    exact_store_available: bool,
    memory_store_available: bool,
    index_available: bool,
    recall_available: bool,
    pii_mode: str,
    disabled: bool = False,
    missing_dependency: str | None = None,
    stale_index: bool = False,
    policy_blocked: str | None = None,
    pending_queue_depth: int = 0,
    last_capture_at: datetime | None = None,
    last_extract_at: datetime | None = None,
    last_index_at: datetime | None = None,
    last_recall_at: datetime | None = None,
) -> AdapterHealth:
    status: HealthStatus
    reason: str | None = None
    # Precedence: explicit off-states first, then degraded, then healthy.
    if disabled:
        status, reason = "disabled", "adapter disabled by config"
    elif missing_dependency:
        status = "missing_dependency"
        reason = f"missing optional dependency: {missing_dependency}"
    elif policy_blocked:
        status, reason = "policy_blocked", policy_blocked
    elif stale_index:
        status, reason = "stale_index", "index is stale; re-index required"
    elif not (exact_store_available and memory_store_available and recall_available):
        status = "degraded"
        missing = [
            name
            for name, ok in (
                ("exact_store", exact_store_available),
                ("memory_store", memory_store_available),
                ("recall", recall_available),
            )
            if not ok
        ]
        reason = "unavailable: " + ", ".join(missing)
    else:
        status = "healthy"
    return AdapterHealth(
        status=status,
        exact_store_available=exact_store_available,
        memory_store_available=memory_store_available,
        index_available=index_available,
        recall_available=recall_available,
        pii_mode=pii_mode,
        pending_queue_depth=pending_queue_depth,
        last_capture_at=last_capture_at,
        last_extract_at=last_extract_at,
        last_index_at=last_index_at,
        last_recall_at=last_recall_at,
        degraded_reason=reason,
        capabilities={
            "exact_store": exact_store_available,
            "memory_store": memory_store_available,
            "index": index_available,
            "recall": recall_available,
        },
    )
