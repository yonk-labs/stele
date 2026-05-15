"""InProcessTaskBackend — threading.Thread + queue.Queue."""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from typing import Literal

from stele.indexing.task_backend.base import IndexTask, TaskStatus


class InProcessTaskBackend:
    name: str = "in_process"

    def __init__(self, *, worker: Callable[[IndexTask], None]) -> None:
        self._worker = worker
        self._queue: queue.Queue[tuple[str, IndexTask] | None] = queue.Queue()
        self._statuses: dict[str, TaskStatus] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, task: IndexTask) -> str:
        task_id = uuid.uuid4().hex
        with self._lock:
            self._statuses[task_id] = TaskStatus(task_id=task_id, state="pending")
        self._queue.put((task_id, task))
        return task_id

    def status(self, task_id: str) -> TaskStatus:
        with self._lock:
            return self._statuses.get(
                task_id,
                TaskStatus(task_id=task_id, state="failed", message="unknown task_id"),
            )

    def close(self) -> None:
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            task_id, task = item
            self._set_state(task_id, "running")
            try:
                self._worker(task)
            except Exception as exc:
                self._set_state(task_id, "failed", message=f"{type(exc).__name__}: {exc}")
            else:
                self._set_state(task_id, "succeeded")

    def _set_state(
        self,
        task_id: str,
        state: Literal["pending", "running", "succeeded", "failed"],
        *,
        message: str | None = None,
    ) -> None:
        with self._lock:
            self._statuses[task_id] = TaskStatus(task_id=task_id, state=state, message=message)
