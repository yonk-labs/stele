from stele import Stele
from stele.core.memory_record import MemoryScope


class _SpyRevisor:
    active = True

    def __init__(self):
        self.supersede_calls = []
        self.ingested = []

    def ingest_evidence(self, *, stele_ref, text, namespace,
                        effective_from=None, session_id=None, extra=None):
        self.ingested.append(stele_ref)

    def supersede(self, *, old_ref, new_ref, reason=None):
        self.supersede_calls.append((old_ref, new_ref, reason))
        return 1

    def retract(self, *, stele_ref, reason="", retracted_at=None):
        return 0

    def search_current(self, query, *, namespace, limit,
                       retracted_behavior, version_filter):
        return []

    def search_as_of(self, query, *, namespace, limit, as_of,
                     retracted_behavior, version_filter):
        return []

    def close(self):
        return None


def test_supersede_projects_real_document_refs_not_synthetic_mem_refs():
    s = Stele.from_config({"backend": {"type": "memory"}})
    spy = _SpyRevisor()
    s._revisor = spy  # pre-empt the lazy NoOp (verified property semantics)

    ns = "bug4"
    scope = MemoryScope(namespace=ns)
    art1 = s.store("Acme uses kafka.", namespace=ns)
    m1 = s.memory.add(text="kafka", kind="fact",
                      source_refs=[art1.reference], scope=scope)
    art2 = s.store("Acme migrated to redpanda.", namespace=ns)
    m2 = s.memory.add(text="redpanda", kind="fact",
                      source_refs=[art2.reference], scope=scope,
                      supersedes=[m1.record.id])

    assert m1.record.id in m2.superseded_ids
    assert len(spy.supersede_calls) == 1, spy.supersede_calls
    old_ref, new_ref, reason = spy.supersede_calls[0]
    # BUG-4: must be the REAL artifact/document refs, not stele://<ns>/mem-<id>
    assert old_ref == art1.reference, old_ref
    assert new_ref == art2.reference, new_ref
    assert "/mem-" not in old_ref and "/mem-" not in new_ref
    assert reason == "superseded"
    s.close()
