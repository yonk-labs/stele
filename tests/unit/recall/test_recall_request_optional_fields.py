from datetime import UTC, datetime

from stele.core.memory_record import MemoryScope
from stele.recall.models import RecallRequest


def test_new_fields_default_none_preserve_behavior() -> None:
    r = RecallRequest(query="q", scope=MemoryScope())
    assert r.as_of is None
    assert r.version_filter is None
    assert r.retracted_behavior is None


def test_new_fields_accept_values() -> None:
    r = RecallRequest(
        query="q",
        scope=MemoryScope(),
        as_of=datetime.now(UTC),
        version_filter="v2",
        retracted_behavior="flag",
    )
    assert r.version_filter == "v2" and r.retracted_behavior == "flag"
