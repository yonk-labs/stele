"""TaskBackend Protocol + supporting models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class IndexTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str
    reference: str
    namespace: str
    submitted_at: datetime


class TaskStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    state: Literal["pending", "running", "succeeded", "failed"]
    message: str | None = None


class TaskBackend(Protocol):
    name: str  # "in_process" | "redis" | "celery"

    def submit(self, task: IndexTask) -> str:
        """Submit task. Returns a task_id."""
        ...

    def status(self, task_id: str) -> TaskStatus:
        ...

    def close(self) -> None:
        ...
