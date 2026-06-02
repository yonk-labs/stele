"""Postgres memory vector recall (stele#39, corrected design).

Store-level tests: the embedder is normally synthesized internally, but here we
inject a deterministic fake so we can prove the vector leg WITHOUT downloading a
model and with a controlled dim. Runs only when STELE_PG_DSN is set, in a
throwaway database so the live store is never touched and the vector(dim) is
ours to choose.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("STELE_PG_DSN"), reason="STELE_PG_DSN unset"
)

from stele.core.memory_record import MemoryRecord, MemoryScope  # noqa: E402

# Two concepts with disjoint surface vocabularies. A query worded entirely in
# concept 0's *query* synonyms shares NO tokens with the stored memory's text,
# so only a semantic (vector) leg can retrieve it.
_CONCEPTS = (
    {"assignor", "rebalancing", "consumer", "partition", "reassignment", "kafka"},
    {"vault", "secret", "rotation", "cadence", "rotate", "credential"},
)
_DIM = 8


class _FakeEmbedder:
    """Concept bag-of-words: a unit vector pointing at whichever concept the
    text mentions. Synonyms across the same concept map to the same direction,
    so paraphrases are close even with zero shared tokens."""

    dim = _DIM

    def embed(self, text: str) -> list[float]:
        tokens = {t.strip(".,").lower() for t in text.split()}
        vec = [0.0] * _DIM
        for i, concept in enumerate(_CONCEPTS):
            vec[i] = float(len(tokens & concept))
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec] if norm else vec


def _new_db() -> str:
    base = os.environ["STELE_PG_DSN"]
    admin = base.rsplit("/", 1)[0] + "/postgres"
    name = f"stele_vec_{uuid.uuid4().hex[:12]}"
    import psycopg

    c = psycopg.connect(admin, autocommit=True)
    with c.cursor() as cur:
        cur.execute(f"CREATE DATABASE {name}")
    c.close()
    return base.rsplit("/", 1)[0] + "/" + name


@pytest.fixture
def vector_store() -> Iterator[object]:
    from stele.storage.memory_store.postgres import PostgresMemoryStore

    dsn = _new_db()
    admin = os.environ["STELE_PG_DSN"].rsplit("/", 1)[0] + "/postgres"
    name = dsn.rsplit("/", 1)[1]
    store = PostgresMemoryStore(dsn, embedder=_FakeEmbedder())
    store.initialize()
    try:
        yield store
    finally:
        store.close()
        import psycopg

        c = psycopg.connect(admin, autocommit=True)
        with c.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        c.close()


def _record(text: str, scope: MemoryScope) -> MemoryRecord:
    now = datetime.now(UTC)
    return MemoryRecord(
        id=uuid.uuid4().hex,
        text=text,
        kind="fact",
        scope=scope,
        source_refs=["stele://default/a"],
        created_at=now,
        updated_at=now,
        effective_from=now,
    )


def test_vector_leg_retrieves_paraphrase_with_no_keyword_overlap(
    vector_store: object,
) -> None:
    store = vector_store
    scope = MemoryScope(user_id="u1")
    kafka = _record("cooperative-sticky assignor avoids the rebalancing storm", scope)
    vault = _record("secret rotation cadence is ninety days", scope)
    store.add(kafka, [])  # type: ignore[attr-defined]
    store.add(vault, [])  # type: ignore[attr-defined]

    # Query shares ZERO tokens with the kafka memory's text, but is the same
    # concept ("consumer partition reassignment"). Keyword-only recall would
    # miss it; the vector leg surfaces it and ranks it first.
    hits = store.search_with_score(  # type: ignore[attr-defined]
        "consumer partition reassignment", scope, limit=5
    )
    ids = [h.record.id for h in hits]
    assert kafka.id in ids, "vector leg must surface the semantically-matching memory"
    assert ids[0] == kafka.id, "the on-concept memory should rank first"


def test_embedding_is_persisted(vector_store: object) -> None:
    store = vector_store
    scope = MemoryScope(user_id="u2")
    r = _record("vault credential rotation policy", scope)
    store.add(r, [])  # type: ignore[attr-defined]
    with store.conn.cursor() as cur:  # type: ignore[attr-defined]
        cur.execute("SELECT embedding IS NOT NULL AS has FROM memories WHERE id=%s", (r.id,))
        assert cur.fetchone()["has"] is True
