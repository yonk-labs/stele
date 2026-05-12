"""Indexing job models."""

from pydantic import BaseModel

from stele.core.types import IndexStatus


class IndexJob(BaseModel):
    artifact_id: str
    status: IndexStatus


class IndexResult(BaseModel):
    artifact_id: str
    status: IndexStatus
    message: str | None = None

