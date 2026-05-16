"""Tests for InProcessTaskBackend + Redis/Celery stubs."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from stele.core.exceptions import CapabilityError
from stele.indexing.task_backend import IndexTask
from stele.indexing.task_backend.in_process import InProcessTaskBackend


def _task() -> IndexTask:
    return IndexTask(
        artifact_id="aid",
        reference="stele://default/aid",
        namespace="default",
        submitted_at=datetime.now(UTC),
    )


def test_in_process_submit_runs_and_succeeds() -> None:
    completed: list[str] = []

    def worker(t: IndexTask) -> None:
        completed.append(t.artifact_id)

    backend = InProcessTaskBackend(worker=worker)
    try:
        task_id = backend.submit(_task())
        # Wait briefly for the background thread
        for _ in range(100):
            status = backend.status(task_id)
            if status.state in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        final = backend.status(task_id)
        assert final.state == "succeeded"
        assert completed == ["aid"]
    finally:
        backend.close()


def test_in_process_failure_recorded() -> None:
    def worker(t: IndexTask) -> None:
        raise RuntimeError("simulated indexing failure")

    backend = InProcessTaskBackend(worker=worker)
    try:
        task_id = backend.submit(_task())
        for _ in range(100):
            status = backend.status(task_id)
            if status.state in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        final = backend.status(task_id)
        assert final.state == "failed"
        assert "simulated" in (final.message or "")
    finally:
        backend.close()


def test_in_process_status_pending_before_run() -> None:
    started = []

    def slow_worker(t: IndexTask) -> None:
        started.append(t.artifact_id)
        time.sleep(0.2)

    backend = InProcessTaskBackend(worker=slow_worker)
    try:
        task_id = backend.submit(_task())
        immediate = backend.status(task_id)
        assert immediate.state in {"pending", "running"}
    finally:
        backend.close()


def test_redis_task_backend_raises_capability_error() -> None:
    from stele.indexing.task_backend.redis import RedisTaskBackend

    with pytest.raises(CapabilityError, match="redis"):
        RedisTaskBackend(dsn="redis://localhost:6379/0")


def test_celery_task_backend_raises_capability_error() -> None:
    from stele.indexing.task_backend.celery import CeleryTaskBackend

    with pytest.raises(CapabilityError, match="celery"):
        CeleryTaskBackend(dsn="redis://localhost:6379/0")
