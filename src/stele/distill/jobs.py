from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from stele.distill.models import DistilledView

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="stele-distill")


@dataclass
class DistillJob:
    id: str
    future: Future[DistilledView]


def submit_job(
    coro_factory: Callable[[], Coroutine[Any, Any, DistilledView]],
) -> DistillJob:
    """Run an async distill call in a worker thread; return a handle immediately."""
    job_id = uuid.uuid4().hex
    future: Future[DistilledView] = _EXECUTOR.submit(lambda: asyncio.run(coro_factory()))
    return DistillJob(id=job_id, future=future)
