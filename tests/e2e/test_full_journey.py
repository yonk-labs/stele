"""Public-API end-to-end journey, per backend. No internals touched.

store -> indexing_status -> vector search -> hybrid search -> fetch
-> recall(artifact_search). Asserts the Phase 4 invariants on every backend —
this is what finally proves mariadb + clickhouse e2e for real.

Content is intentionally PII-free: chunkshop-backed stores correctly reject
unscrubbed PII at the write boundary (Phase 4 design). Scrub-on-fetch is a
Phase-1 guarantee with its own extensive coverage; the harness's unique value
is the cross-backend index/search/recall path.
"""

from __future__ import annotations

import re

from stele import Stele
from stele.core.memory_record import MemoryScope

_CHUNK_ID = re.compile(r"^[0-9a-f]+:\d+$")


def test_full_journey(stash: Stele) -> None:
    # namespace "default": recall.artifact_search resolves artifact_id against
    # the default namespace; artifact_id (uuid) provides uniqueness and each
    # backend param gets an isolated Stele instance.
    stored = stash.store(
        "The incident root cause was a missing database index on the "
        "orders table; the fix was to rebuild the index overnight.",
        namespace="default",
    )
    assert stored.index_status in {"indexed", "queued"}
    assert stash.indexing_status(stored.artifact_id).status == "indexed"

    vec = stash.search(stored.reference, "database index", mode="vector")
    assert vec, "vector search returned nothing"
    top = vec[0]
    assert top.retrieval_mode == "vector"
    assert top.chunk_id is not None and _CHUNK_ID.match(top.chunk_id)
    assert top.chunk_id.split(":")[0] == stored.artifact_id
    assert type(top).__module__.startswith("stele.")  # no native obj escapes

    hyb = stash.search(stored.reference, "database index", mode="hybrid")
    assert hyb and hyb[0].retrieval_mode == "hybrid"

    fetched = stash.fetch(stored.reference)
    assert "database index" in str(fetched.content)  # exact-evidence round-trip

    result = stash.recall.artifact_search(
        query="root cause",
        scope=MemoryScope(user_id="e2e"),
        artifact_id=stored.artifact_id,
    )
    assert result.strategy_used == "artifact_search"
