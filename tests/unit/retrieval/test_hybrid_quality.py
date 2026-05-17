"""Load-bearing hybrid-quality gate (SC-014, DC-003).

Runs for real against SQLiteChunkStore + real fastembed embeddings (model
cached). Asserts ``hybrid_recall@5 >= max(vector, keyword) - FLOOR`` over a
held-out set. FLOOR defaults to 0.05, overridable via STELE_HYBRID_FLOOR.
A drop beyond the floor is a regression — do NOT lower the floor in code.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from stele.core.artifact import ArtifactRecord
from stele.core.config import IndexingConfig
from stele.retrieval.hybrid import hybrid_search
from stele.retrieval.vector import vector_search
from stele.storage.chunk_store.sqlite import SQLiteChunkStore

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "recall" / "hybrid_held_out_set.json"
_FLOOR = float(os.environ.get("STELE_HYBRID_FLOOR", "0.05"))
_K = 5


def _artifact(aid: str, text: str) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=aid,
        reference=f"stele://default/{aid}",
        namespace="default",
        session_id=None,
        content=text,
        content_encoding="utf-8",
        content_type="text",
        byte_size=len(text),
        token_estimate=len(text.split()),
        summary=text[:120],
        digest_sha256="x" * 64,
        metadata={},
        created_at=datetime.now(UTC),
    )


def _recall_at_k(retrieved_ids: list[str], relevant: set[str]) -> float:
    top = set(retrieved_ids[:_K])
    return len(top & relevant) / len(relevant)


def test_hybrid_recall_within_floor_of_best_component(tmp_path: Path) -> None:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    queries = data["queries"]
    assert len(queries) >= 20, "held-out set must have >= 20 query/relevant pairs"

    store = SQLiteChunkStore(IndexingConfig(), db_path=str(tmp_path / "hq.db"))
    for doc in data["corpus"]:
        store.write(_artifact(doc["id"], doc["text"]))

    kw_total = vec_total = hyb_total = 0.0
    for q in queries:
        relevant = set(q["relevant"])
        kw = store.keyword_search(q["query"], limit=_K)
        vec = vector_search(store, q["query"], limit=_K)
        hyb = hybrid_search(store, q["query"], limit=_K)
        kw_total += _recall_at_k([h.artifact_id for h in kw], relevant)
        vec_total += _recall_at_k([h.artifact_id for h in vec], relevant)
        hyb_total += _recall_at_k([h.artifact_id for h in hyb], relevant)

    n = len(queries)
    kw_recall, vec_recall, hyb_recall = kw_total / n, vec_total / n, hyb_total / n
    best = max(kw_recall, vec_recall)
    store.close()

    assert hyb_recall >= best - _FLOOR, (
        f"hybrid_recall@5={hyb_recall:.3f} fell more than FLOOR={_FLOOR} below "
        f"max(keyword={kw_recall:.3f}, vector={vec_recall:.3f})={best:.3f} — "
        f"regression, not a floor adjustment"
    )
