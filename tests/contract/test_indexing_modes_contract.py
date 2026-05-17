"""Indexing modes contract: skip / sync / async × {memory, sqlite, postgres}.

Contract-level coverage for SC-019 (async returns immediately), SC-020
(indexing_status), SC-021 (search while pending doesn't raise). IndexStatus
uses "queued" (NOT "pending") — assertions align to that.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest

from stele import Stele

_BACKENDS = ["memory", "sqlite"]
if os.environ.get("STELE_PG_DSN"):
    _BACKENDS.append("postgres")


def _stash(backend: str, mode: str, tmp_path: Path) -> Stele:
    cfg: dict[str, object] = {"indexing": {"mode": mode}}
    if backend == "memory":
        cfg["backend"] = {"type": "memory"}
    elif backend == "sqlite":
        cfg["backend"] = {"type": "sqlite", "path": str(tmp_path / f"{uuid.uuid4().hex}.db")}
    else:
        cfg["backend"] = {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}
    return Stele.from_config(cfg)


@pytest.mark.parametrize("backend", _BACKENDS)
def test_skip_mode(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, "skip", tmp_path)
    stored = stash.store("skip mode leaves nothing indexed", namespace="n")
    assert stored.index_status == "skipped"
    assert stash.indexing_status(stored.artifact_id).status == "skipped"
    stash.close()


@pytest.mark.parametrize("backend", _BACKENDS)
def test_sync_mode(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, "sync", tmp_path)
    stored = stash.store("sync mode indexes inline before returning", namespace="n")
    assert stored.index_status == "indexed"
    assert stash.indexing_status(stored.artifact_id).status == "indexed"
    hits = stash.search(stored.reference, "sync mode", mode="vector")
    assert hits
    stash.close()


@pytest.mark.parametrize("backend", _BACKENDS)
def test_async_mode(backend: str, tmp_path: Path) -> None:
    stash = _stash(backend, "async", tmp_path)
    stored = stash.store("async mode indexes on a worker thread", namespace="n")
    # SC-019: returns immediately — queued (or already indexed if worker raced).
    assert stored.index_status in {"queued", "indexed"}
    # SC-021: searching while indexing may be pending must not raise.
    stash.search(stored.reference, "async", mode="vector")
    # SC-020: status transitions to indexed.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if stash.indexing_status(stored.artifact_id).status == "indexed":
            break
        time.sleep(0.02)
    assert stash.indexing_status(stored.artifact_id).status == "indexed"
    assert stash.search(stored.reference, "async mode worker", mode="vector")
    stash.close()
