import os
import uuid
from pathlib import Path

import pytest

from stele import CapabilityError, Stele

BACKENDS = ["memory", "sqlite"]
if os.environ.get("STELE_PG_DSN"):
    BACKENDS.append("postgres")
if os.environ.get("STELE_MARIADB_DSN"):
    BACKENDS.append("mariadb")
if os.environ.get("STELE_CLICKHOUSE_DSN"):
    BACKENDS.append("clickhouse")


def _stash_for_backend(
    tmp_path: Path, backend: str, *, extra: dict[str, object] | None = None
) -> Stele:
    backends: dict[str, dict[str, object]] = {
        "memory": {},
        "sqlite": {"backend": {"type": "sqlite", "path": str(tmp_path / "s.db")}},
        "postgres": {"backend": {"type": "postgres", "dsn": os.environ.get("STELE_PG_DSN", "")}},
        "mariadb": {"backend": {"type": "mariadb", "dsn": os.environ.get("STELE_MARIADB_DSN", "")}},
        "clickhouse": {
            "backend": {"type": "clickhouse", "dsn": os.environ.get("STELE_CLICKHOUSE_DSN", "")}
        },
    }
    cfg = dict(backends[backend])
    if extra:
        cfg.update(extra)
    return Stele.from_config(cfg)


@pytest.mark.parametrize("backend", BACKENDS)
def test_search_within_artifact_finds_needle(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    namespace = f"ops_{uuid.uuid4().hex}"
    stored = stash.store(
        "The incident root cause was a missing database index.",
        namespace=namespace,
    )

    hits = stash.search(stored.reference, "database index")

    assert len(hits) == 1
    assert "database index" in hits[0].text
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_query_namespace_isolated(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    namespace_a = f"a_{uuid.uuid4().hex}"
    namespace_b = f"b_{uuid.uuid4().hex}"
    stash.store("Project Apollo uses MariaDB.", namespace=namespace_a)
    stash.store("Project Borealis uses ClickHouse.", namespace=namespace_b)

    hits = stash.query(namespace_a, "MariaDB")

    assert len(hits) == 1
    assert hits[0].metadata["namespace"] == namespace_a
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_unsupported_explicit_mode_raises(tmp_path: Path, backend: str) -> None:
    stash = _stash_for_backend(tmp_path, backend)
    stored = stash.store("some text")

    # vector/hybrid are on by default now (chunk index); graph still needs a
    # graph backend, so it remains unsupported on these stores.
    with pytest.raises(CapabilityError):
        stash.search(stored.reference, "text", mode="graph")
    stash.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_search_results_are_scrubbed_by_default(tmp_path: Path, backend: str) -> None:
    # PII scrubbing is opt-in; this test exercises the scrubbing surface.
    stash = _stash_for_backend(tmp_path, backend, extra={"pii": {"enabled": True}})
    namespace = f"ops_{uuid.uuid4().hex}"
    stored = stash.store(
        "Contact alice@example.com about the ClickHouse migration.",
        namespace=namespace,
    )

    hits = stash.search(stored.reference, "ClickHouse migration")

    assert "alice@example.com" not in hits[0].text
    assert "[EMAIL_1]" in hits[0].text
    stash.close()
