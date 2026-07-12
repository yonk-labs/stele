"""SERVICE tier -- the bento-stele-shim FastAPI contract.

`bento-stele-shim` is an internal-only container (FastAPI on :8000, not
published to the host) that fronts stele for bento. Every call here goes
through ``docker exec bento-stele-shim curl`` via the shared
:mod:`tests.service._shim_client` helper -- see that module for why (no
`sh -c` string interpolation, so request bodies never need shell quoting).

All writes are isolated to a `test_stele_<timestamp>_<random>` namespace
(see ``_ns()``) and cleaned up via retraction in a fixture teardown. The
shim exposes NO delete route for artifacts or memories (only retract and a
global, unscoped ``purge_superseded``) -- see the docstring on
``test_purge_superseded_is_contract_safe_on_shared_backend`` for why this
suite deliberately does not exercise real deletion through that endpoint
against the shared backend.

Skips cleanly (not errors) when the shim/docker isn't reachable, so this
suite is safe to leave in the normal test run on a machine without the
bento stack up.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Iterator

import pytest

from tests.service._shim_client import shim_available, shim_request

pytestmark = pytest.mark.skipif(
    not shim_available(),
    reason="bento-stele-shim not reachable via `docker exec` -- "
    "start the bento stack to run this tier",
)


def _ns(tag: str) -> str:
    return f"test_stele_{tag}_{int(time.time())}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def cleanup() -> Iterator[list[str]]:
    """Collects memory_ids created during a test; retracts them all on
    teardown (best-effort -- the shim has no hard-delete route to fall back
    to, and retract is the documented cleanup path for throwaway data)."""
    created: list[str] = []
    yield created
    for mid in created:
        with contextlib.suppress(Exception):
            shim_request(
                "POST", f"/v1/memories/{mid}/retract",
                {"reason": "test_stele cleanup"},
            )


def _store_artifact(ns: str, text: str) -> str:
    resp = shim_request("POST", "/v1/artifacts", {"content": text, "namespace": ns})
    ref = resp["reference"]
    assert isinstance(ref, str) and ref.startswith("stele://")
    return ref


def _add_memory(ns: str, text: str, ref: str, *, supersedes: list[str] | None = None) -> str:
    body: dict[str, object] = {
        "text": text, "kind": "fact", "source_refs": [ref],
        "scope": {"namespace": ns},
    }
    if supersedes:
        body["supersedes"] = supersedes
    resp = shim_request("POST", "/v1/memories", body)
    return str(resp["memory_id"])


def test_health_reports_ok() -> None:
    health = shim_request("GET", "/health")
    assert health["status"] == "ok"
    assert "library_version" in health


def test_store_artifact_and_add_memory(cleanup: list[str]) -> None:
    ns = _ns("crud")
    ref = _store_artifact(ns, "the on-call rotation runs Monday through Friday")
    mid = _add_memory(ns, "the on-call rotation runs Monday through Friday", ref)
    cleanup.append(mid)

    fetched = shim_request("GET", f"/v1/artifacts/{ref.rsplit('/', 1)[-1]}?namespace={ns}")
    assert "rotation" in str(fetched.get("content", fetched.get("summary", "")))

    listed = shim_request("GET", f"/v1/memories?namespace={ns}")
    assert any(m["memory_id"] == mid for m in listed["memories"]), listed


def test_recall_hides_retracted(cleanup: list[str]) -> None:
    """The required behavior test: create a memory, confirm it's recalled,
    retract it, and confirm /v1/recall then hides it -- through the live
    shim HTTP contract, not just the in-process Python API."""
    ns = _ns("retract")
    ref = _store_artifact(ns, "the deploy window is Friday at 5pm")
    mid = _add_memory(ns, "the deploy window is Friday at 5pm", ref)
    cleanup.append(mid)

    before = shim_request(
        "POST", "/v1/recall",
        {"query": "deploy window", "scope": {"namespace": ns}, "strategy": "memory_search"},
    )
    assert any(c["id"] == mid for c in before["citations"]), (
        f"expected the new memory recalled before retraction: {before}"
    )

    retracted = shim_request(
        "POST", f"/v1/memories/{mid}/retract", {"reason": "test_stele cleanup: superseded"},
    )
    assert retracted["retracted"] is True

    after = shim_request(
        "POST", "/v1/recall",
        {"query": "deploy window", "scope": {"namespace": ns}, "strategy": "memory_search"},
    )
    assert not any(c["id"] == mid for c in after["citations"]), (
        f"retracted memory must be hidden from recall: {after}"
    )


def test_purge_superseded_is_contract_safe_on_shared_backend(cleanup: list[str]) -> None:
    """`/v1/memories/purge_superseded` takes only `before` -- NO namespace or
    scope filter (confirmed via the shim's openapi.json: MemoryPurgeSupersededRequest
    has a single `before` field). Its predicate is global: status='superseded'
    AND effective_until < before, across every namespace in the shared
    `bento` postgres this shim writes to. Manual verification against the
    live shim during test development confirmed the destructive path truly
    works (a same-namespace v1/v2 supersede + purge with a future cutoff
    correctly hard-deleted exactly the superseded row) -- but that is NOT
    safe to leave as a repeatable automated test: any cutoff that is recent
    enough to catch OUR throwaway superseded row is, by construction, also
    recent enough to catch every real superseded memory ever written to this
    shared database (supersession always stamps effective_until in the past
    relative to "now"). There is no `before` value that catches ours without
    also being eligible to catch theirs.

    So this test exercises the CONTRACT ONLY: a `before` far enough in the
    past (year 2000) cannot structurally match any real row, proving the
    endpoint responds with the documented shape and does not error -- while
    our own superseded row (created moments ago) is verified to survive.
    Real deletion semantics are covered at the BASE (Python API) tier against
    isolated in-process/sqlite backends -- see
    tests/contract/test_recall_contract.py::test_purge_superseded_removes_expired_rows_but_keeps_recent.
    """
    ns = _ns("purge")
    ref = _store_artifact(ns, "the API rate limit is 100/min")
    old_mid = _add_memory(ns, "the API rate limit is 100/min", ref)
    new_mid = _add_memory(
        ns, "the API rate limit is 500/min", ref, supersedes=[old_mid],
    )
    # Memory.retract has no status precondition, so a 'superseded' row can
    # still be retracted -- moves it out of 'superseded' entirely, leaving
    # nothing for the shared backend's unscoped purge_superseded to matter
    # for. Cleaner than leaving a dangling superseded row behind.
    cleanup.append(new_mid)
    cleanup.append(old_mid)

    result = shim_request(
        "POST", "/v1/memories/purge_superseded", {"before": "2000-01-01T00:00:00Z"},
    )
    assert "purged" in result and isinstance(result["purged"], int)

    listed = shim_request("GET", f"/v1/memories?namespace={ns}&status_filter=superseded")
    statuses = {m["memory_id"]: m["status"] for m in listed["memories"]}
    assert statuses.get(old_mid) == "superseded", (
        "a past-dated cutoff must not touch our just-superseded row"
    )


def test_distill_consolidate_contract_on_empty_scope() -> None:
    """distill/consolidate IS namespace-scoped (ConsolidateRequestModel.scope
    -> Memory.list(scope, ...) inside stele.distill.base.consolidate), so --
    unlike purge_superseded -- it's safe to call for real. Exercised here on a
    throwaway, guaranteed-empty namespace: asserts the response shape and
    that an empty scope is a no-op (0 clusters, 0 retracted)."""
    ns = _ns("consolidate-empty")
    result = shim_request("POST", "/v1/distill/consolidate", {"scope": {"namespace": ns}})
    assert result == {"clusters": 0, "retracted": 0}
