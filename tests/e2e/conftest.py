"""E2E harness fixtures.

Backends: memory + sqlite always; postgres/mariadb/clickhouse when their
STELE_*_DSN is set. If a DSN is set but the server is unreachable, FAIL
LOUD (no silent half-up runs — that is the whole point of the harness).
Every test here is auto-marked `e2e` (deselected by default; CI opts in).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from stele import Stele

_DSN = {
    "postgres": os.environ.get("STELE_PG_DSN"),
    "mariadb": os.environ.get("STELE_MARIADB_DSN"),
    "clickhouse": os.environ.get("STELE_CLICKHOUSE_DSN"),
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply the `e2e` marker ONLY to items under tests/e2e/.

    A conftest hook receives the WHOLE session's items, not just this
    directory's — filter by nodeid or the global suite gets marked e2e.
    """
    for item in items:
        if item.nodeid.startswith("tests/e2e/"):
            item.add_marker(pytest.mark.e2e)


def _backends() -> list[str]:
    bk = ["memory", "sqlite"]
    bk += [name for name, dsn in _DSN.items() if dsn]
    return bk


@pytest.fixture(params=_backends())
def backend(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def stash(backend: str, tmp_path: Path) -> Iterator[Stele]:
    cfg: dict[str, object] = {"indexing": {"mode": "sync"}}
    if backend == "memory":
        cfg["backend"] = {"type": "memory"}
    elif backend == "sqlite":
        cfg["backend"] = {"type": "sqlite", "path": str(tmp_path / "e2e.db")}
    else:
        cfg["backend"] = {"type": backend, "dsn": _DSN[backend]}
    try:
        s = Stele.from_config(cfg)
    except Exception as exc:  # noqa: BLE001 - fail loud, never skip a set DSN
        pytest.fail(
            f"{backend}: DSN is set but Stele could not connect "
            f"({type(exc).__name__}: {exc}). The harness must run against a "
            f"live server — bring it up with `make -C deploy up`."
        )
    try:
        yield s
    finally:
        s.close()
