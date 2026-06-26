"""Memory contract tests parametrized across backends (SC-008)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from stele import Stele
from stele.core.memory_record import MemoryKind, MemoryQuery, MemoryScope

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

    # purge_superseded is intentionally GLOBAL (a retention sweep, not
    # scope-bounded), so on a shared backend (Postgres test container,
    # concurrent tests in the same session) other rows can also match.
    # The contract this test enforces is the PREDICATE — which rows are
    # purged vs retained — and that's already covered by the per-record
    # assertions below. The strict count works on fresh per-test stores
    # (memory, sqlite tmp_path) and is a lower bound everywhere else.
    assert purged >= 1
    assert s.memory.get(old.record.id) is None  # past the horizon
    assert s.memory.get(recent.record.id) is not None  # superseded-but-recent
    assert s.memory.get(new.record.id) is not None  # active head untouched


@pytest.mark.parametrize("backend", BACKENDS)
def test_list_with_as_of_returns_records_valid_at_that_time(
    tmp_path: Path, backend: str
) -> None:
    """Issue #3 — the late-binding filter trap.

    A record that was active at `as_of` but has since been RETRACTED must
    still appear in ``Memory.list(scope, as_of=t_between)``. The naive
    consumer pattern (``list(status_filter=["active"]) + Python time
    filter``) silently drops it because current status is now 'retracted'.
    The fix pushes the time-window filter down to SQL and expands the
    default status set when ``as_of`` is set.
    """
    import time as _time

    s = _stele(tmp_path, backend)
    user = _unique_user()
    r = s.memory.add(
        text="fact-at-t0",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    t_between = datetime.now(UTC) + timedelta(milliseconds=10)
    _time.sleep(0.05)  # ensure retraction lands strictly after t_between
    s.memory.retract(r.record.id, reason="wrong")

    # Default (no explicit status_filter) + as_of: must include the
    # was-active-at-as_of record even though current status is 'retracted'.
    historical = s.memory.list(MemoryScope(user_id=user), as_of=t_between)
    assert {m.id for m in historical} == {r.record.id}

    # Current view (no as_of) keeps current behavior: default
    # status_filter=["active","superseded"] excludes retracted.
    current = s.memory.list(MemoryScope(user_id=user))
    assert r.record.id not in {m.id for m in current}


@pytest.mark.parametrize("backend", BACKENDS)
def test_list_with_as_of_excludes_future_records(
    tmp_path: Path, backend: str
) -> None:
    """Records whose ``effective_from`` is AFTER ``as_of`` must not appear."""
    import time as _time

    s = _stele(tmp_path, backend)
    user = _unique_user()
    t_before = datetime.now(UTC)
    _time.sleep(0.05)  # ensure the new record's effective_from > t_before
    s.memory.add(
        text="fact-after-as_of",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    out = s.memory.list(MemoryScope(user_id=user), as_of=t_before)
    assert out == []


@pytest.mark.parametrize("backend", BACKENDS)
def test_list_with_as_of_and_explicit_status_filter_composes(
    tmp_path: Path, backend: str
) -> None:
    """Explicit ``status_filter`` + ``as_of`` composes: a record is returned
    only if it (a) was valid at as_of AND (b) currently matches the filter.
    Honor what the caller asked for — don't expand the status set."""
    import time as _time

    s = _stele(tmp_path, backend)
    user = _unique_user()
    r = s.memory.add(
        text="fact-at-t0",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    t_between = datetime.now(UTC) + timedelta(milliseconds=10)
    _time.sleep(0.05)
    s.memory.retract(r.record.id)

    # Was valid at as_of, but caller explicitly asked for active only:
    # current status is retracted, so it must NOT appear.
    active_only = s.memory.list(
        MemoryScope(user_id=user), status_filter=["active"], as_of=t_between
    )
    assert active_only == []

    # Caller explicitly asks for retracted: it's valid at as_of AND
    # currently retracted -> appears.
    retracted_only = s.memory.list(
        MemoryScope(user_id=user), status_filter=["retracted"], as_of=t_between
    )
    assert {m.id for m in retracted_only} == {r.record.id}


@pytest.mark.parametrize("backend", BACKENDS)
def test_purge_namespace_drops_memory_in_target_only(
    tmp_path: Path, backend: str
) -> None:
    """Stele.purge_namespace drops every memory row in the target namespace
    while leaving other namespaces intact. Live and historical rows alike."""
    s = _stele(tmp_path, backend)
    ns_a = f"a_{uuid.uuid4().hex}"
    ns_b = f"b_{uuid.uuid4().hex}"

    s.memory.add(
        text="alpha", kind="fact",
        source_refs=["stele://x/a"],
        scope=MemoryScope(namespace=ns_a),
    )
    s.memory.add(
        text="beta", kind="fact",
        source_refs=["stele://x/a"],
        scope=MemoryScope(namespace=ns_a),
    )
    keep = s.memory.add(
        text="gamma", kind="fact",
        source_refs=["stele://x/a"],
        scope=MemoryScope(namespace=ns_b),
    )

    report = s.purge_namespace(ns_a)

    assert report.memories == 2
    assert s.memory.list(MemoryScope(namespace=ns_a)) == []
    survivors = s.memory.list(MemoryScope(namespace=ns_b))
    assert {m.id for m in survivors} == {keep.record.id}


@pytest.mark.parametrize("backend", BACKENDS)
def test_purge_namespace_drops_superseded_history(
    tmp_path: Path, backend: str
) -> None:
    """Purge drops historical (superseded) rows too — namespace deletion
    is a deliberate forget; as_of time-travel does not survive purge."""
    s = _stele(tmp_path, backend)
    ns = f"hist_{uuid.uuid4().hex}"
    scope = MemoryScope(namespace=ns)

    r1 = s.memory.add(
        text="v1", kind="fact",
        source_refs=["stele://x/a"], scope=scope,
    )
    # Supersede to create historical row
    s.memory.add(
        text="v2", kind="fact",
        source_refs=["stele://x/a"], scope=scope,
        supersedes=[r1.record.id],
    )

    # Both rows live (1 active + 1 superseded). Purge drops both.
    report = s.purge_namespace(ns)
    assert report.memories == 2
    assert (
        s.memory.list(
            scope, status_filter=["active", "superseded", "retracted", "disputed", "deleted"]
        )
        == []
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_add_many_observably_equivalent(tmp_path: Path, backend: str) -> None:
    """N memories in one add_many() ≡ N memories in N add() calls — same
    final state, all rows retrievable, scope honored per row."""
    from stele.core.memory_record import AddRequest

    s = _stele(tmp_path, backend)
    user = _unique_user()
    items = [
        AddRequest(
            text=f"fact {i}",
            kind="fact",
            source_refs=[f"stele://x/{i}"],
            scope=MemoryScope(user_id=user),
        )
        for i in range(4)
    ]
    results = s.memory.add_many(items)
    assert len(results) == 4
    listed = s.memory.list(MemoryScope(user_id=user), limit=50)
    assert {m.id for m in listed} == {r.record.id for r in results}


@pytest.mark.parametrize("backend", BACKENDS)
def test_add_many_empty_returns_empty(tmp_path: Path, backend: str) -> None:
    s = _stele(tmp_path, backend)
    assert s.memory.add_many([]) == []


@pytest.mark.parametrize("backend", BACKENDS)
def test_lifecycle_kinds_store_and_supersede(tmp_path: Path, backend: str) -> None:
    """#38: the cq lifecycle kinds are storable, and an L2 workaround is
    superseded by an L3 tool_recommendation via the existing supersession
    plumbing (no new behavior needed upstream)."""
    s = _stele(tmp_path, backend)
    user = _unique_user()
    wa = s.memory.add(
        text="pin transitive dep to dodge the resolver bug",
        kind="workaround",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    stored_wa = s.memory.get(wa.record.id)
    assert stored_wa is not None and stored_wa.kind == "workaround"
    rec = s.memory.add(
        text="use the new resolver flag that fixes it natively",
        kind="tool_recommendation",
        source_refs=["stele://default/b"],
        scope=MemoryScope(user_id=user),
        supersedes=[wa.record.id],
    )
    assert rec.superseded_ids == [wa.record.id]
    # The L4 signal is just another kind stele can store.
    gap = s.memory.add(
        text="no first-class tool exists for X",
        kind="tool_gap",
        source_refs=["stele://default/c"],
        scope=MemoryScope(user_id=user),
    )
    stored_gap = s.memory.get(gap.record.id)
    assert stored_gap is not None and stored_gap.kind == "tool_gap"


@pytest.mark.parametrize("backend", BACKENDS)
def test_tripartite_round_trip_and_search(tmp_path: Path, backend: str) -> None:
    """#37A: summary/detail/action round-trip, and a term living only in
    `detail` is findable (search indexes the composed insight)."""
    s = _stele(tmp_path, backend)
    user = _unique_user()
    r = s.memory.add(
        text="kafka consumer note",
        summary="consumers rebalance on deploy",
        detail="the cooperative-sticky assignor avoids the rebalancing storm",
        action="set partition.assignment.strategy to cooperative-sticky",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=MemoryScope(user_id=user),
    )
    got = s.memory.get(r.record.id)
    assert got is not None
    assert got.summary == "consumers rebalance on deploy"
    assert got.action == "set partition.assignment.strategy to cooperative-sticky"
    # "assignor" appears only in `detail`, not in `text`.
    hits = s.memory.search(
        MemoryQuery(query="assignor", scope=MemoryScope(user_id=user))
    )
    assert r.record.id in {h.id for h in hits}


@pytest.mark.parametrize("backend", BACKENDS)
def test_reobservation_evolves_evidence(tmp_path: Path, backend: str) -> None:
    """#37B: re-observing an assertion bumps confirmations and raises
    confidence (never above 1.0); the text is never mutated; one row."""
    s = _stele(tmp_path, backend)
    user = _unique_user()
    scope = MemoryScope(user_id=user)
    first = s.memory.add(
        text="prod runs in us-east-1",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=scope,
        confidence=0.5,
    )
    assert first.record.confirmations == 1
    assert first.record.confidence == pytest.approx(0.5)
    again = s.memory.add(
        text="prod runs in us-east-1",
        kind="fact",
        source_refs=["stele://default/b"],
        scope=scope,
        confidence=0.5,
    )
    assert again.record.id == first.record.id
    assert again.record.confirmations == 2
    assert again.record.confidence > 0.5
    assert again.record.text == "prod runs in us-east-1"
    assert len(s.memory.list(scope, limit=50)) == 1


@pytest.mark.parametrize("backend", BACKENDS)
def test_search_with_score_stamps_last_queried(tmp_path: Path, backend: str) -> None:
    """#37B: recall stamps last_queried on the rows it surfaces."""
    s = _stele(tmp_path, backend)
    user = _unique_user()
    scope = MemoryScope(user_id=user)
    r = s.memory.add(
        text="vault rotation cadence is 90 days",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=scope,
    )
    before = s.memory.get(r.record.id)
    assert before is not None and before.last_queried is None
    hits = s.memory.search_with_score("vault rotation", scope)
    assert r.record.id in {h.record.id for h in hits}
    after = s.memory.get(r.record.id)
    assert after is not None and after.last_queried is not None


@pytest.mark.parametrize("backend", BACKENDS)
def test_add_many_within_batch_dedup_merges(tmp_path: Path, backend: str) -> None:
    """#37B: add_many stays observably equal to N adds — an identical row
    later in the same batch confirms the first instead of inserting a twin."""
    from stele.core.memory_record import AddRequest

    s = _stele(tmp_path, backend)
    user = _unique_user()
    scope = MemoryScope(user_id=user)
    items = [
        AddRequest(
            text="same assertion",
            kind="fact",
            source_refs=["stele://x/1"],
            scope=scope,
        ),
        AddRequest(
            text="same assertion",
            kind="fact",
            source_refs=["stele://x/2"],
            scope=scope,
        ),
    ]
    results = s.memory.add_many(items)
    assert results[0].duplicate_of is None
    assert results[1].duplicate_of == results[0].record.id
    assert results[1].record.id == results[0].record.id
    assert results[1].record.confirmations == 2
    assert len(s.memory.list(scope, limit=50)) == 1


@pytest.mark.parametrize("backend", BACKENDS)
def test_add_many_with_supersession(tmp_path: Path, backend: str) -> None:
    """Per-row supersession works inside a batch."""
    from stele.core.memory_record import AddRequest

    s = _stele(tmp_path, backend)
    user = _unique_user()
    old = s.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=["stele://x/old"],
        scope=MemoryScope(user_id=user),
    )
    items = [
        AddRequest(
            text="user prefers Zed",
            kind="preference",
            source_refs=["stele://x/new"],
            scope=MemoryScope(user_id=user),
            supersedes=[old.record.id],
        ),
    ]
    results = s.memory.add_many(items)
    assert results[0].superseded_ids == [old.record.id]
    hits = s.memory.search(
        MemoryQuery(query="prefers", scope=MemoryScope(user_id=user))
    )
    assert {h.id for h in hits} == {results[0].record.id}


@pytest.mark.parametrize("backend", BACKENDS)
def test_by_source_ref_returns_active_back_links(tmp_path: Path, backend: str) -> None:
    """Episodic Phase 1: by_source_ref returns exactly the active-head
    memories whose source_refs contains the given ref, ignoring memories
    that cite a different ref."""
    s = _stele(tmp_path, backend)
    user = _unique_user()
    scope = MemoryScope(user_id=user)
    episode_ref = f"stele://default/episode-{uuid.uuid4().hex}"
    other_ref = f"stele://default/other-{uuid.uuid4().hex}"

    a = s.memory.add(
        text="we switched to keep120",
        kind="decision",
        source_refs=[episode_ref],
        scope=scope,
    )
    b = s.memory.add(
        text="the auth refactor landed",
        kind="fact",
        source_refs=[episode_ref],
        scope=scope,
    )
    s.memory.add(
        text="unrelated note from another session",
        kind="fact",
        source_refs=[other_ref],
        scope=scope,
    )

    linked = s.memory.by_source_ref(scope, episode_ref)
    assert {m.id for m in linked} == {a.record.id, b.record.id}


@pytest.mark.parametrize("backend", BACKENDS)
def test_by_source_ref_excludes_superseded_by_default(
    tmp_path: Path, backend: str
) -> None:
    """A superseded memory is not an active head, so by_source_ref drops it
    unless the caller widens status_filter."""
    s = _stele(tmp_path, backend)
    user = _unique_user()
    scope = MemoryScope(user_id=user)
    episode_ref = f"stele://default/episode-{uuid.uuid4().hex}"

    old = s.memory.add(
        text="user prefers Helix",
        kind="preference",
        source_refs=[episode_ref],
        scope=scope,
    )
    new = s.memory.add(
        text="user prefers Zed",
        kind="preference",
        source_refs=[episode_ref],
        scope=scope,
        supersedes=[old.record.id],
    )

    active = s.memory.by_source_ref(scope, episode_ref)
    assert {m.id for m in active} == {new.record.id}

    widened = s.memory.by_source_ref(
        scope, episode_ref, status_filter=("active", "superseded")
    )
    assert {m.id for m in widened} == {old.record.id, new.record.id}


# Context & Protocol Ledger kinds (Task 1, Phase 1 re-scope).
LEDGER_KINDS = [
    "decision",
    "dead_end",
    "completion",
    "procedure",
    "constraint",
    "verification_method",
    "observation",
]


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("kind", LEDGER_KINDS)
def test_ledger_kind_roundtrips(tmp_path: Path, backend: str, kind: str) -> None:
    """Each ledger kind must store and round-trip unchanged on every backend."""
    s = _stele(tmp_path, backend)
    scope = MemoryScope(namespace="ledger")
    ref = str(s.store("evidence blob", namespace="ledger").reference)
    result = s.memory.add(
        text=f"a {kind} record",
        kind=cast(MemoryKind, kind),
        source_refs=[ref],
        scope=scope,
    )
    got = s.memory.get(result.record.id)
    assert got is not None and got.kind == kind


@pytest.mark.parametrize("backend", BACKENDS)
def test_find_precedent_matches_active_by_metadata(tmp_path: Path, backend: str) -> None:
    """find_precedent returns the active records whose metadata matches all pairs.

    This is the supersession-candidate lookup a consumer (e.g. bento's distiller)
    otherwise reimplements: list active facts, filter by (subject, predicate).
    """
    s = _stele(tmp_path, backend)
    scope = MemoryScope(user_id=_unique_user())
    deploy = s.memory.add(
        text="deploy day is Friday",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=scope,
        metadata={"subject": "deploy_day", "predicate": "is", "object": "Friday"},
    )
    s.memory.add(
        text="owner is alice",
        kind="fact",
        source_refs=["stele://default/b"],
        scope=scope,
        metadata={"subject": "owner", "predicate": "is", "object": "alice"},
    )
    hits = s.memory.find_precedent(
        scope, match={"subject": "deploy_day", "predicate": "is"}, kind="fact"
    )
    assert [h.id for h in hits] == [deploy.record.id]
    assert s.memory.find_precedent(scope, match={"subject": "nope"}) == []


@pytest.mark.parametrize("backend", BACKENDS)
def test_find_precedent_excludes_superseded(tmp_path: Path, backend: str) -> None:
    """Only the current active record is a precedent; superseded ones are gone."""
    s = _stele(tmp_path, backend)
    scope = MemoryScope(user_id=_unique_user())
    meta = {"subject": "deploy_day", "predicate": "is"}
    old = s.memory.add(
        text="deploy day is Friday",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=scope,
        metadata={**meta, "object": "Friday"},
    )
    new = s.memory.add(
        text="deploy day is Tuesday",
        kind="fact",
        source_refs=["stele://default/a"],
        scope=scope,
        metadata={**meta, "object": "Tuesday"},
        supersedes=[old.record.id],
    )
    hits = s.memory.find_precedent(scope, match=meta, kind="fact")
    assert [h.id for h in hits] == [new.record.id]
