"""Regression for stele#89: the lazy embedding-column guard must be
search_path-aware, not schema-blind.

The bug: ``initialize()`` checked ``information_schema.columns WHERE
table_name='memories'`` — which matches the column in *any* schema on the
catalog. When a decoy ``memories`` (e.g. ``public.memories``) already carries
``embedding`` but the role actually writes to a different schema's
``memories`` that does NOT, the guard saw the decoy's column and skipped the
``ALTER``, so every vector write then hit ``UndefinedColumn``.

Runs only when STELE_PG_DSN is set, in a throwaway database.
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
from stele.storage.memory_store.postgres import PostgresMemoryStore  # noqa: E402

_DIM = 8


class _FakeEmbedder:
    dim = _DIM

    def embed(self, text: str) -> list[float]:
        # Direction doesn't matter here; we only exercise the column/DDL path.
        return [1.0] + [0.0] * (_DIM - 1)


def _new_db() -> str:
    base = os.environ["STELE_PG_DSN"]
    admin = base.rsplit("/", 1)[0] + "/postgres"
    name = f"stele_guard_{uuid.uuid4().hex[:12]}"
    import psycopg

    c = psycopg.connect(admin, autocommit=True)
    with c.cursor() as cur:
        cur.execute(f"CREATE DATABASE {name}")
    c.close()
    return base.rsplit("/", 1)[0] + "/" + name


@pytest.fixture
def cross_schema_dsn() -> Iterator[str]:
    dsn = _new_db()
    import psycopg

    # Stand up a decoy `memories` in a NON-search_path schema that already has
    # an `embedding` column. The connecting role's bare `memories` still
    # resolves to public.memories (decoy is not on search_path), but the old
    # schema-blind information_schema scan would match this decoy.
    c = psycopg.connect(dsn, autocommit=True)
    with c.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("CREATE SCHEMA decoy")
        cur.execute(f"CREATE TABLE decoy.memories (id text, embedding vector({_DIM}))")
    c.close()
    yield dsn
    admin = os.environ["STELE_PG_DSN"].rsplit("/", 1)[0] + "/postgres"
    name = dsn.rsplit("/", 1)[1]
    c = psycopg.connect(admin, autocommit=True)
    with c.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    c.close()


def test_embedding_added_to_target_table_despite_decoy(cross_schema_dsn: str) -> None:
    store = PostgresMemoryStore(cross_schema_dsn, embedder=_FakeEmbedder())
    store.initialize()

    # The guard must have added embedding to the table the role WRITES to
    # (public.memories), not been fooled by decoy.memories.
    with store.conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_attribute "
            "WHERE attrelid = 'public.memories'::regclass "
            "AND attname = 'embedding' AND NOT attisdropped"
        )
        assert cur.fetchone() is not None, "embedding column missing on public.memories"

    # And a real vector write round-trips (the symptom: UndefinedColumn).
    now = datetime.now(UTC)
    rec = MemoryRecord(
        id=uuid.uuid4().hex,
        text="kafka partition reassignment",
        kind="fact",
        scope=MemoryScope(user_id="u1"),
        source_refs=["stele://test/ref"],
        created_at=now,
        updated_at=now,
        effective_from=now,
    )
    store.add(rec, supersedes=[])
    assert store.get(rec.id) is not None
    store.conn.close()
