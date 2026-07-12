"""3RD-PARTY / E2E tier -- through bento-api (http://localhost:8000), the
one real consumer of stele reachable from outside the docker network.

Discovery (reading /Users/matt.yonkovit/yonk-tools/bento/backend and
hitting the live API) found the stele-backed routes: `POST/GET
/v1/memories`, `POST /v1/memories/{id}/retract`, `POST /v1/recall`, `GET
/v1/artifacts/{id}` -- all thin proxies to bento-stele-shim
(backend/api/routes/{memories,recall,artifacts}.py). `POST /v1/ask` (chat)
does NOT touch stele -- its citations come from a separate pg-raggraph
chunk store, so it's out of scope here.

Namespace wrinkle (backend/api/routes/recall.py, security/kb_access.py):
- `POST /v1/memories` (write) takes the namespace VERBATIM, no ownership
  check.
- `POST /v1/recall` and `GET /v1/memories` (read) run every caller-supplied
  namespace through `resolve_accessible_namespace`: only "default"/None or
  an owned `kb-{kb_id}` passes; anything else is a 404 (existence-hiding
  against cross-tenant IDOR). `_memory_namespace` then strips the `kb-`
  prefix before forwarding to stele, so memories written under the bare
  kb_id (matching the write side) are exactly what a `kb-{kb_id}` recall
  finds.

So: write with `scope.namespace = <kb_id>`, read/recall with
`scope.namespace = f"kb-{kb_id}"`. A throwaway KB (`test_stele_<ts>` name)
is created per test and deleted in a fixture teardown via `DELETE
/v1/me/kbs/{kb_id}` -- the KB *is* the isolation/cleanup unit for this tier,
since neither memories nor artifacts have their own delete route here.

Skips cleanly when bento-api or the configured admin key isn't available.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Iterator

import pytest

from tests.e2e_bento._bento_client import bento_api_available, bento_request

pytestmark = pytest.mark.skipif(
    not bento_api_available(),
    reason="bento-api not reachable at :8000 (or the configured admin key doesn't "
    "authenticate) -- start the bento stack to run this tier",
)


def _ns(tag: str) -> str:
    return f"test_stele_{tag}_{int(time.time())}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def kb_cleanup() -> Iterator[list[str]]:
    """Collects (kb_id, memory_ids) work created during a test; retracts
    every memory THEN deletes every KB on teardown. Deleting a KB does not
    cascade to its stele memories (bento's KB row and stele's memory rows
    are separate systems) -- retraction is the only cleanup path for those,
    so it must happen before/independent of the KB delete, not instead of it."""
    kb_ids: list[str] = []
    memory_ids: list[str] = []
    yield _Throwaway(kb_ids, memory_ids)
    for mid in memory_ids:
        with contextlib.suppress(Exception):
            bento_request("POST", f"/v1/memories/{mid}/retract", {"reason": "test_stele cleanup"})
    for kb_id in kb_ids:
        with contextlib.suppress(Exception):
            bento_request("DELETE", f"/v1/me/kbs/{kb_id}")


class _Throwaway:
    """Tracks this test's throwaway kb_ids + memory_ids for the cleanup fixture."""

    def __init__(self, kb_ids: list[str], memory_ids: list[str]) -> None:
        self.kb_ids = kb_ids
        self.memory_ids = memory_ids


def _create_kb(cleanup: _Throwaway, name: str) -> str:
    status, body = bento_request(
        "POST", "/v1/me/kbs", {"name": name, "kb_model": "memory"}
    )
    assert status == 201, (status, body)
    kb_id = str(body["id"])
    cleanup.kb_ids.append(kb_id)
    return kb_id


def _add_memory(cleanup: _Throwaway, kb_id: str, text: str) -> str:
    status, body = bento_request(
        "POST", "/v1/memories",
        {
            "text": text, "kind": "fact",
            "source_refs": [f"stele://{kb_id}/e2e-probe"],
            "scope": {"namespace": kb_id},
        },
    )
    assert status == 200, (status, body)
    mid = str(body["memory_id"])
    cleanup.memory_ids.append(mid)
    return mid


def test_recall_hides_retracted(kb_cleanup: _Throwaway) -> None:
    """The required behavior test, threaded through the real E2E entry
    point: bento-api create-memory -> recall (hit) -> retract -> recall
    (miss), with a real Bearer-authenticated caller and KB-scoped namespace
    resolution -- not just the shim directly."""
    kb_id = _create_kb(kb_cleanup, _ns("e2e-retract"))
    mid = _add_memory(kb_cleanup, kb_id, "the deploy window is Friday at 5pm")

    status, before = bento_request(
        "POST", "/v1/recall",
        {
            "query": "deploy window",
            "scope": {"namespace": f"kb-{kb_id}"},
            "strategy": "memory_search",
        },
    )
    assert status == 200, before
    assert any(c["id"] == mid for c in before["citations"]), (
        f"expected the new memory recalled before retraction: {before}"
    )

    status, retracted = bento_request(
        "POST", f"/v1/memories/{mid}/retract", {"reason": "test_stele cleanup: e2e"}
    )
    assert status == 200 and retracted["retracted"] is True, retracted

    status, after = bento_request(
        "POST", "/v1/recall",
        {
            "query": "deploy window",
            "scope": {"namespace": f"kb-{kb_id}"},
            "strategy": "memory_search",
        },
    )
    assert status == 200, after
    assert not any(c["id"] == mid for c in after["citations"]), (
        f"retracted memory must be hidden from recall: {after}"
    )


def test_memory_list_rejects_unowned_namespace(kb_cleanup: _Throwaway) -> None:
    """GET /v1/memories access-checks the namespace (security/kb_access.py):
    a namespace naming a KB that doesn't exist/isn't owned 404s rather than
    confirming or denying it (existence-hiding against cross-tenant IDOR)."""
    kb_id = _create_kb(kb_cleanup, _ns("e2e-list"))
    _add_memory(kb_cleanup, kb_id, "the API rate limit is 100/min")

    bogus_kb = uuid.uuid4().hex
    status, denied = bento_request("GET", f"/v1/memories?namespace=kb-{bogus_kb}")
    assert status == 404, (
        f"a namespace naming a non-existent/non-owned KB must 404, got {status}: {denied}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "bento-api bug found during this suite's development, not fixed here: "
        "GET /v1/memories forwards the access-checked 'kb-{id}' namespace to the "
        "stele shim VERBATIM (backend/api/routes/memories.py:149, `params["
        "'namespace'] = resolved_namespace`), unlike POST /v1/recall, which strips "
        "the 'kb-' prefix via `_memory_namespace()` before forwarding "
        "(backend/api/routes/recall.py:90-101). Memories are stored under the bare "
        "kb_id (no prefix) by POST /v1/memories, so a KB-scoped GET /v1/memories "
        "list always comes back empty even though the SAME memory is correctly "
        "found by POST /v1/recall (see test_recall_hides_retracted above, which "
        "passes). This test documents the discrepancy; it should start passing "
        "(and the xfail should be removed) once routes/memories.py's list handler "
        "strips the 'kb-' prefix the same way recall.py does."
    ),
)
def test_memory_list_finds_kb_scoped_memory_bug(kb_cleanup: _Throwaway) -> None:
    kb_id = _create_kb(kb_cleanup, _ns("e2e-listbug"))
    mid = _add_memory(kb_cleanup, kb_id, "the API rate limit is 100/min")

    status, listed = bento_request("GET", f"/v1/memories?namespace=kb-{kb_id}")
    assert status == 200, listed
    assert any(m["memory_id"] == mid for m in listed["memories"]), listed
