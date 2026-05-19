"""RED spec (TDD): the Revisor's async->sync bridge ``_run`` must be safe to
call whether or not a running event loop is already present.

Today ``_run`` is ``return asyncio.run(coro)``. ``asyncio.run()`` raises
``RuntimeError: asyncio.run() cannot be called from a running event loop``
when invoked from inside any running loop (FastAPI/Starlette handler, async
agent runtime, Jupyter). Since the graph path is the documented
"living knowledge via recall" surface and agent runtimes are async, this is a
hard correctness failure (deadlock/crash), not a perf issue.

Required: ``_run`` works correctly in BOTH a normal sync context (byte-for-byte
unchanged: still ``asyncio.run``) AND from inside a running loop. Exceptions
raised in the coroutine must propagate unchanged in both contexts.

Pure unit test — construction does not connect, so no DSN/LLM/Postgres needed.
``_run`` itself performs no DB I/O.
"""

from __future__ import annotations

import asyncio

import pytest

from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

_DSN = "postgresql://user:pw@localhost:5432/db"


def _revisor() -> PgRaggraphRevisor:
    return PgRaggraphRevisor(dsn=_DSN, namespace="n", evolution_tier="structural")


async def _aval(x: int) -> int:
    return x


async def _aboom() -> int:
    raise ValueError("boom")


def test_run_sync_context_back_compat() -> None:
    """No running loop: behavior unchanged (still resolves the coro)."""
    r = _revisor()
    assert r._run(_aval(42)) == 42


def test_run_inside_running_loop() -> None:
    """Inside a running loop: must NOT raise the asyncio.run() RuntimeError.

    Pre-fix this fails with:
        RuntimeError: asyncio.run() cannot be called from a running event loop
    """
    r = _revisor()

    async def test_body() -> int:
        return r._run(_aval(7))

    assert asyncio.run(test_body()) == 7


def test_run_exception_propagation_sync() -> None:
    """Coroutine exception propagates unchanged in a sync context."""
    r = _revisor()
    with pytest.raises(ValueError, match="boom"):
        r._run(_aboom())


def test_run_exception_propagation_inside_loop() -> None:
    """Coroutine exception propagates unchanged from inside a running loop."""
    r = _revisor()

    async def test_body() -> None:
        r._run(_aboom())

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(test_body())
