"""Memory contract tests parametrized across backends (SC-008)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele import Stele
from stele.core.memory_record import MemoryQuery, MemoryScope

BACKENDS = ["memory", "sqlite"]
if os.environ.get("STELE_PG_DSN"):
    BACKENDS.append("postgres")


def _stele(tmp_path: Path, backend: str) -> Stele:
    if backend == "memory":
        return Stele.from_config({"backend": {"type": "memory"}})
    if backend == "sqlite":
        return Stele.from_config(
            {"backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")}}
        )
    return Stele.from_config(
        {"backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]}}
    )


def _unique_user() -> str:
    """Return a unique user_id so each test run is isolated in shared backends."""
    return f"test-{uuid.uuid4().hex}"


@pytest.mark.parametrize("backend", BACKENDS)
def test_add_then_get(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    user = _unique_user()
    r = s.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    got = s.memory.get(r.record.id)
    assert got is not None
    assert got.text == "user prefers Helix"


@pytest.mark.parametrize("backend", BACKENDS)
def test_supersession_hides_old_in_default_search(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    user = _unique_user()
    old = s.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    new = s.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id=user),
        supersedes=[old.record.id],
    )
    hits = s.memory.search(
        MemoryQuery(query="prefers", scope=MemoryScope(user_id=user))
    )
    assert [h.id for h in hits] == [new.record.id]


@pytest.mark.parametrize("backend", BACKENDS)
def test_as_of_returns_historical(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    user = _unique_user()
    old = s.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    t_between = datetime.now(UTC) + timedelta(milliseconds=10)
    import time

    time.sleep(0.05)  # ensure new memory has later effective_from
    s.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id=user),
        supersedes=[old.record.id],
    )
    hits = s.memory.search(
        MemoryQuery(
            query="prefers",
            scope=MemoryScope(user_id=user),
            as_of=t_between,
        )
    )
    ids = {h.id for h in hits}
    assert ids == {old.record.id}


@pytest.mark.parametrize("backend", BACKENDS)
def test_delete_excludes_from_search(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    user = _unique_user()
    r = s.memory.add(
        text="find me",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    s.memory.delete(r.record.id)
    hits = s.memory.search(
        MemoryQuery(query="find", scope=MemoryScope(user_id=user))
    )
    assert hits == []
    assert s.memory.get(r.record.id) is not None  # still retrievable


@pytest.mark.parametrize("backend", ["mariadb", "clickhouse"])
def test_unsupported_backend_raises_capability_error(
    tmp_path: Path,
    backend: str,
) -> None:
    if backend == "mariadb" and not os.environ.get("STELE_MARIADB_DSN"):
        pytest.skip("STELE_MARIADB_DSN unset")
    if backend == "clickhouse" and not os.environ.get("STELE_CLICKHOUSE_DSN"):
        pytest.skip("STELE_CLICKHOUSE_DSN unset")
    from stele.core.exceptions import CapabilityError

    dsn_env = f"STELE_{backend.upper()}_DSN"
    s = Stele.from_config(
        {"backend": {"type": backend, "dsn": os.environ[dsn_env]}}
    )
    with pytest.raises(CapabilityError) as exc:
        s.memory.add(
            text="x",
            kind="fact",
            source_refs=["stele://default/a"],
            scope=MemoryScope(user_id=_unique_user()),
        )
    assert "not yet implemented" in str(exc.value)
