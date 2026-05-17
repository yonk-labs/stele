from datetime import UTC, datetime

from stele.core.memory_record import MemoryRecord, MemoryScope
from stele.storage.memory_store.memory import InProcessMemoryStore


def _rec(mid: str) -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id=mid,
        text="t",
        kind="fact",
        scope=MemoryScope(namespace="n"),
        source_refs=["stele://n/a"],
        created_at=now,
        updated_at=now,
        effective_from=now,
    )


def test_set_retracted_flips_status_and_effective_until() -> None:
    s = InProcessMemoryStore()
    s.initialize()
    s.add(_rec("m1"), [])
    when = datetime.now(UTC)
    s.set_retracted("m1", when)
    got = s.get("m1")
    assert got is not None and got.status == "retracted"
    assert got.effective_until == when
