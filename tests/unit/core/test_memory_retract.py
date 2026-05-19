from stele.core.memory import Memory
from stele.core.memory_record import MemoryScope
from stele.pii.scrubber import DisabledPIIScrubber
from stele.revisor.base import NoOpRevisor
from stele.storage.memory_store.memory import InProcessMemoryStore


class RecordingRevisor(NoOpRevisor):
    active = True

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def ingest_evidence(self, **kw: object) -> None:
        self.calls.append(("ingest", kw["stele_ref"]))

    def supersede(
        self, *, old_ref: str, new_ref: str, reason: str | None = None
    ) -> int:
        self.calls.append(("supersede", old_ref, new_ref))
        return 1

    def retract(
        self, *, stele_ref: str, reason: str = "", retracted_at: object | None = None
    ) -> int:
        self.calls.append(("retract", stele_ref))
        return 1


def _mem(rev: NoOpRevisor) -> Memory:
    s = InProcessMemoryStore()
    s.initialize()
    return Memory(s, DisabledPIIScrubber(), revisor=rev)


def test_retract_sets_status_and_projects() -> None:
    rev = RecordingRevisor()
    m = _mem(rev)
    res = m.add(
        text="x", kind="fact", source_refs=["stele://n/a"],
        scope=MemoryScope(namespace="n"),
    )
    rec = m.retract(res.record.id, reason="wrong")
    assert rec.status == "retracted"
    assert ("retract", f"stele://n/mem-{res.record.id}") in rev.calls


def test_add_with_supersedes_projects_supersede() -> None:
    rev = RecordingRevisor()
    m = _mem(rev)
    a = m.add(
        text="old", kind="fact", source_refs=["stele://n/a"],
        scope=MemoryScope(namespace="n"),
    )
    m.add(
        text="new", kind="fact", source_refs=["stele://n/b"],
        scope=MemoryScope(namespace="n"), supersedes=[a.record.id],
    )
    # BUG-4: the graph-supersede projection mirrors memory supersession at the
    # evidence-document level — it must use the memories' real source_refs[0]
    # document refs, not synthetic stele://<ns>/mem-<id> refs.
    assert (
        "supersede",
        "stele://n/a",
        "stele://n/b",
    ) in rev.calls


def test_noop_default_is_inert() -> None:
    m = _mem(NoOpRevisor())
    res = m.add(
        text="x", kind="fact", source_refs=["stele://n/a"],
        scope=MemoryScope(namespace="n"),
    )
    assert m.retract(res.record.id).status == "retracted"
