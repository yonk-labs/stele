from __future__ import annotations

import time

from stele import Stele
from stele.core.memory_record import MemoryScope
from stele.distill.models import DistilledView


def test_submit_returns_handle_and_result_completes():
    s = Stele.from_config({"backend": {"type": "memory"}})
    scope = MemoryScope(namespace="t-jobs")
    ref = str(s.store("a fact", namespace="t-jobs").reference)
    s.memory.add(text="a fact about kafka", kind="fact", source_refs=[ref], scope=scope,
                 summary="kafka fact")
    job = s.distill.submit("facts", scope)
    assert job.id
    # poll for completion
    view = None
    for _ in range(100):
        view = s.distill.result(job.id)
        if view is not None:
            break
        time.sleep(0.02)
    assert isinstance(view, DistilledView)
    assert view.mode == "facts"


def test_result_unknown_job_raises():
    import pytest
    s = Stele.from_config({"backend": {"type": "memory"}})
    with pytest.raises(KeyError):
        s.distill.result("nope")
