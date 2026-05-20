import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stele import ArtifactNotFound, Stele
from stele.core.reference import parse_reference

BACKENDS = ["memory", "sqlite"]
if os.environ.get("STELE_PG_DSN"):
    BACKENDS.append("postgres")
if os.environ.get("STELE_MARIADB_DSN"):
    BACKENDS.append("mariadb")
if os.environ.get("STELE_CLICKHOUSE_DSN"):
    BACKENDS.append("clickhouse")


def _stash_for_backend(tmp_path: Path, backend: str) -> Stele:
    if backend == "sqlite":
        return Stele.from_config(
            {
                "backend": {"type": "sqlite", "path": str(tmp_path / "stele.db")},
                "pii": {"raw_fetch_enabled": True},
            }
        )
    if backend == "postgres":
        return Stele.from_config(
            {
                "backend": {"type": "postgres", "dsn": os.environ["STELE_PG_DSN"]},
                "pii": {"raw_fetch_enabled": True},
            }
        )
    if backend == "mariadb":
        return Stele.from_config(
            {
                "backend": {
                    "type": "mariadb",
                    "dsn": os.environ["STELE_MARIADB_DSN"],
                },
                "pii": {"raw_fetch_enabled": True},
            }
        )
    if backend == "clickhouse":
        return Stele.from_config(
            {
                "backend": {
                    "type": "clickhouse",
                    "dsn": os.environ["STELE_CLICKHOUSE_DSN"],
                },
                "pii": {"raw_fetch_enabled": True},
            }
        )
    return Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"raw_fetch_enabled": True}}
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_exact_store_fetch_delete(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    namespace = f"ns_{uuid.uuid4().hex}"
    stored = stash.store("needle content", namespace=namespace, session_id="s1")

    fetched = stash.fetch(stored.reference, raw=True)

    assert fetched.content == "needle content"
    assert stash.delete(stored.reference) is True
    with pytest.raises(ArtifactNotFound):
        stash.fetch(stored.reference)
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_list_by_namespace_and_session(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    namespace_a = f"a_{uuid.uuid4().hex}"
    namespace_b = f"b_{uuid.uuid4().hex}"
    stash.store("one", namespace=namespace_a, session_id="s1")
    stash.store("two", namespace=namespace_b, session_id="s1")
    stash.store("three", namespace=namespace_a, session_id="s2")

    assert len(stash.list(namespace=namespace_a).items) == 2
    assert len(stash.list(namespace=namespace_a, session_id="s1").items) == 1
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_ttl_cleanup(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    namespace = f"ttl_{uuid.uuid4().hex}"
    stored = stash.store("expires", namespace=namespace, lifecycle="ttl", ttl_seconds=60)
    record = stash.storage.fetch(parse_reference(stored.reference))
    stash.storage.store(
        record.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    )

    result = stash.cleanup_expired()

    assert result.deleted_count >= 1
    with pytest.raises(ArtifactNotFound):
        stash.fetch(stored.reference)
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_large_round_trip(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    content = "x" * 1_000_000
    stored = stash.store(content)

    assert stash.fetch(stored.reference, raw=True).content == content
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_purge_namespace_drops_target_only(tmp_path: Path, backend: str) -> None:
    """GDPR-style namespace purge: target ns drops to zero, other ns intact."""
    stash = _stash_for_backend(tmp_path, backend)
    ns_a = f"a_{uuid.uuid4().hex}"
    ns_b = f"b_{uuid.uuid4().hex}"
    stash.store("one", namespace=ns_a)
    stash.store("two", namespace=ns_a)
    stash.store("three", namespace=ns_b)

    report = stash.purge_namespace(ns_a)

    assert report.namespace == ns_a
    assert report.dry_run is False
    assert report.artifacts == 2
    assert stash.list(namespace=ns_a).items == []
    assert len(stash.list(namespace=ns_b).items) == 1
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_purge_namespace_dry_run_no_mutation(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    ns = f"dry_{uuid.uuid4().hex}"
    stash.store("alpha", namespace=ns)
    stash.store("beta", namespace=ns)

    report = stash.purge_namespace(ns, dry_run=True)

    assert report.dry_run is True
    assert report.artifacts == 2
    assert len(stash.list(namespace=ns).items) == 2  # unchanged
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_purge_namespace_idempotent(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    ns = f"idem_{uuid.uuid4().hex}"
    stash.store("only", namespace=ns)
    first = stash.purge_namespace(ns)
    second = stash.purge_namespace(ns)

    assert first.artifacts == 1
    assert second.artifacts == 0
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_purge_namespace_rejects_empty(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    with pytest.raises(ValueError):
        stash.purge_namespace("")
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_store_many_observably_equivalent(tmp_path: Path, backend: str) -> None:
    """N rows in one store_many() ≡ N rows in N store() calls — same final
    state, all rows fetchable by reference."""
    from stele.core.artifact import StoreRequest

    stash = _stash_for_backend(tmp_path, backend)
    namespace = f"bw_{uuid.uuid4().hex}"

    items = [
        StoreRequest(content=f"row-{i}", namespace=namespace, session_id="s1")
        for i in range(5)
    ]
    results = stash.store_many(items)

    assert len(results) == 5
    for i, r in enumerate(results):
        fetched = stash.fetch(r.reference, raw=True)
        assert fetched.content == f"row-{i}"
    assert len(stash.list(namespace=namespace).items) == 5
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_store_many_empty_returns_empty(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    assert stash.store_many([]) == []
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_store_many_preserves_input_order(tmp_path: Path, backend: str) -> None:
    """Acceptance: results list ordering matches input. Important for
    callers like memexify that pair input rows with idempotency keys."""
    from stele.core.artifact import StoreRequest

    stash = _stash_for_backend(tmp_path, backend)
    namespace = f"ord_{uuid.uuid4().hex}"
    contents = ["alpha", "bravo", "charlie", "delta"]
    items = [StoreRequest(content=c, namespace=namespace) for c in contents]
    results = stash.store_many(items)
    fetched = [stash.fetch(r.reference, raw=True).content for r in results]
    assert fetched == contents
    stash.close()
