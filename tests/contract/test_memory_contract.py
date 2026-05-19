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


@pytest.mark.parametrize("backend", BACKENDS)
def test_search_with_score_matches_search_scope_and_temporal(
    tmp_path: Path,
    backend: str,
) -> None:
    """BUG-1: search_with_score must honor the SAME scope + temporal
    semantics as search. It previously used strict full-scope equality and
    a status='active'-only filter, silently dropping in-scope / still-valid
    records that search() returns."""
    s = _stele(tmp_path, backend)
    user = _unique_user()

    # Case 1 — hierarchical scope: record carries a session_id; the query
    # scope omits it. search() matches hierarchically (only filters non-None
    # scope fields); search_with_score() must agree.
    scoped = MemoryScope(user_id=user, session_id="sess-A")
    query_scope = MemoryScope(user_id=user)
    s.memory.add(
        text="acme kafka streaming pipeline",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=scoped,
    )

    # Case 2 — superseded-but-still-valid at now: search()'s default view
    # keeps a record that is status='active' OR (superseded AND
    # effective_until > now). A live record superseded by a *future*-dated
    # one stays valid; search_with_score must keep it too.
    older = s.memory.add(
        text="acme kafka retention policy",
        kind="fact",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id=user),
    )
    s.memory.add(
        text="acme kafka retention revised",
        kind="fact",
        source_refs=["stele://default/c"],
        scope=MemoryScope(user_id=user),
        supersedes=[older.record.id],
    )

    # Corpus is << limit (20) on purpose: this asserts parity of the
    # CANDIDATE SET (scope + temporal predicate), not ranking/truncation.
    # search orders by effective_from DESC, search_with_score by score DESC;
    # with a small corpus LIMIT never truncates, so ordering can't perturb
    # set membership. Do NOT raise the corpus past `limit` without rethinking
    # this assertion (post-LIMIT subsets can legitimately differ by design).
    s_ids = {
        r.id
        for r in s.memory.search(
            MemoryQuery(query="kafka", scope=query_scope, limit=20)
        )
    }
    sws_ids = {
        h.record.id
        for h in s.memory.search_with_score("kafka", query_scope, limit=20)
    }
    assert s_ids == sws_ids and len(s_ids) >= 2, (
        f"BUG-1 [{backend}]: search={s_ids} search_with_score={sws_ids} "
        "must agree on hierarchical scope + temporal validity"
    )


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


@pytest.mark.parametrize("backend", BACKENDS)
def test_purge_superseded_predicate_identical_across_backends(
    tmp_path: Path,
    backend: str,
) -> None:
    """Every real memory-store backend applies the SAME predicate:
    status='superseded' AND effective_until < cutoff. Active and
    superseded-but-recent records survive."""
    import time

    s = _stele(tmp_path, backend)
    user = _unique_user()
    scope = MemoryScope(user_id=user)

    # old: superseded before the cutoff -> purged
    old = s.memory.add(
        text="alpha v1",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=scope,
    )
    time.sleep(0.05)
    s.memory.add(
        text="alpha v2",
        kind="fact",
        source_refs=["stele://default/b"],
        scope=scope,
        supersedes=[old.record.id],
    )
    time.sleep(0.05)
    cutoff = datetime.now(UTC)
    time.sleep(0.05)

    # recent: superseded AFTER the cutoff -> retained
    recent = s.memory.add(
        text="beta v1",
        kind="fact",
        source_refs=["stele://default/c"],
        scope=scope,
    )
    time.sleep(0.05)
    new = s.memory.add(
        text="beta v2",
        kind="fact",
        source_refs=["stele://default/d"],
        scope=scope,
        supersedes=[recent.record.id],
    )

    purged = s.memory.purge_superseded(cutoff)

    assert purged == 1
    assert s.memory.get(old.record.id) is None  # past the horizon
    assert s.memory.get(recent.record.id) is not None  # superseded-but-recent
    assert s.memory.get(new.record.id) is not None  # active head untouched
