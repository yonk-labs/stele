"""Stele.cleanup() — expired-artifact + opt-in horizon-bounded
superseded-memory purge (whats-next #6).

Load-bearing safety invariant: with NO retention horizon, the
superseded-purge is a NO-OP. It must never silently destroy
``as_of`` time-travel history by default.
"""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele import Stele
from stele.core.artifact import CleanupReport
from stele.core.memory_record import MemoryQuery, MemoryScope


@pytest.fixture
def stele(tmp_path: Path) -> Stele:
    return Stele.from_config(
        {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
    )


def _add(stele: Stele, text: str, user: str, supersedes: list[str] | None = None):  # type: ignore[no-untyped-def]
    return stele.memory.add(
        text=text,
        kind="preference",
        source_refs=["stele://default/doc"],
        scope=MemoryScope(user_id=user),
        supersedes=supersedes,
    )


def test_default_safe_no_horizon_preserves_time_travel_history(stele: Stele) -> None:
    """THE load-bearing safety test: cleanup() with no
    superseded_memory_before purges ZERO superseded memories, so a
    superseded record stays reachable via ``as_of`` time-travel."""
    user = "alice"
    old = _add(stele, "user prefers Helix", user)
    t_between = datetime.now(UTC) + timedelta(milliseconds=10)
    time.sleep(0.05)
    _add(stele, "user prefers Zed", user, supersedes=[old.record.id])

    report = stele.cleanup()

    assert isinstance(report, CleanupReport)
    assert report.superseded_memories_purged == 0
    # History preserved: as_of before the supersession still finds the old one.
    hits = stele.memory.search(
        MemoryQuery(
            query="prefers",
            scope=MemoryScope(user_id=user),
            as_of=t_between,
        )
    )
    assert {h.id for h in hits} == {old.record.id}
    assert stele.memory.get(old.record.id) is not None


def test_bounded_purge_removes_only_records_past_horizon(stele: Stele) -> None:
    """A cutoff after the supersession purges the old superseded record;
    a more-recently-superseded record (effective_until after the cutoff)
    is retained — recent time-travel history survives."""
    user = "bob"

    # Record 1: superseded early (effective_until = T_old).
    r1 = _add(stele, "fact one v1", user)
    time.sleep(0.05)
    _add(stele, "fact one v2", user, supersedes=[r1.record.id])
    t_old_superseded = datetime.now(UTC)

    time.sleep(0.05)
    cutoff = datetime.now(UTC)
    time.sleep(0.05)

    # Record 2: superseded AFTER the cutoff (effective_until = T_new > cutoff).
    r2 = _add(stele, "fact two v1", user)
    time.sleep(0.05)
    _add(stele, "fact two v2", user, supersedes=[r2.record.id])

    report = stele.cleanup(superseded_memory_before=cutoff)

    assert report.superseded_memories_purged == 1
    # Old superseded record is hard-deleted.
    assert stele.memory.get(r1.record.id) is None
    # as_of before the old supersession no longer finds it (past the
    # retention horizon — acceptable, by design).
    pre = stele.memory.search(
        MemoryQuery(
            query="fact",
            scope=MemoryScope(user_id=user),
            as_of=t_old_superseded - timedelta(milliseconds=10),
        )
    )
    assert r1.record.id not in {h.id for h in pre}
    # The newer superseded record is RETAINED (its window ended after cutoff).
    assert stele.memory.get(r2.record.id) is not None


def test_cleanup_still_expires_ttl_artifacts(stele: Stele) -> None:
    """Parity with the old cleanup_expired: cleanup() still expires
    TTL'd artifacts."""
    stored = stele.store("expiring payload", lifecycle="ttl", ttl_seconds=60)
    from stele.core.reference import parse_reference

    record = stele.storage.fetch(parse_reference(stored.reference))
    stele.storage.store(
        record.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
    )

    report = stele.cleanup()

    assert report.artifacts_expired >= 1
    from stele.core.exceptions import ArtifactNotFound

    with pytest.raises(ArtifactNotFound):
        stele.fetch(stored.reference)


def test_cleanup_expired_back_compat_unchanged(stele: Stele) -> None:
    """The legacy cleanup_expired entrypoint still works and returns a
    CleanupResult (it is NOT removed or changed)."""
    stored = stele.store("expiring payload", lifecycle="ttl", ttl_seconds=60)
    from stele.core.reference import parse_reference

    record = stele.storage.fetch(parse_reference(stored.reference))
    stele.storage.store(
        record.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
    )

    result = stele.cleanup_expired()

    from stele.core.artifact import CleanupResult

    assert isinstance(result, CleanupResult)
    assert result.deleted_count >= 1
