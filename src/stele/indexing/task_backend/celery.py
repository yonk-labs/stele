"""CeleryTaskBackend stub — Phase 4 ships CapabilityError only."""

from __future__ import annotations

from stele.core.exceptions import CapabilityError
from stele.indexing.task_backend.base import IndexTask, TaskStatus


class CeleryTaskBackend:
    name: str = "celery"

    def __init__(self, *, dsn: str) -> None:
        del dsn
        raise CapabilityError(
            "celery task backend not implemented; "
            "use task_backend='in_process' or supply your own TaskBackend Protocol implementation"
        )

    def submit(self, task: IndexTask) -> str:  # pragma: no cover
        raise CapabilityError("celery task backend not implemented")

    def status(self, task_id: str) -> TaskStatus:  # pragma: no cover
        raise CapabilityError("celery task backend not implemented")

    def close(self) -> None:  # pragma: no cover
        pass
