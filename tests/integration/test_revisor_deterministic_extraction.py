"""Deterministic graph extraction builds a non-empty entity graph.

The bug this pins (proven 2026-07-13 by direct probing against pg-raggraph
0.9.2): ``PgRaggraphRevisor`` used to send every ingest record with
``skip_llm = not self._llm_extraction``, and for any non-``"llm"`` extractor
that flag was ``True``. pg-raggraph's per-doc ingest gate
(``skip_llm_for_this_doc``) short-circuits ALL extraction — including the
deterministic lede leg — so ``fact_extractor="lede_spacy"`` (and the newly
wired ``"lede_prose"``) silently produced a chunks-only store with zero
entities: degenerate cold-vector search masquerading as a graph.

The fix splits two gates: ``_needs_llm`` (thread the LLM provider into the
graph cfg) from ``_extraction_active`` (any extraction runs). The per-record
``skip_llm`` is now ``not self._extraction_active`` — False for deterministic
extractors — so the lede path runs.

This test needs NO LLM endpoint (the point of deterministic extraction): it
runs whenever ``STELE_PG_RAGGRAPH_DSN`` is set and the lede packages are
importable. It FAILS before the gating fix (entities == 0) and PASSES after.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

_DSN = os.environ.get("STELE_PG_RAGGRAPH_DSN")
pytestmark = pytest.mark.skipif(
    not _DSN,
    reason="STELE_PG_RAGGRAPH_DSN unset",
)

_ENTITY_RICH = (
    "Ada Lovelace collaborated with Charles Babbage on the Analytical "
    "Engine in London. Babbage designed the Difference Engine; Ada wrote "
    "the first algorithm intended for that machine."
)


def _entity_count(ns: str) -> int:
    assert _DSN is not None
    with psycopg.connect(_DSN) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM entities WHERE namespace = %s", (ns,))
        row = cur.fetchone()
        return int(row[0]) if row else 0


@pytest.mark.parametrize("extractor", ["lede_spacy", "lede_prose"])
def test_deterministic_extractor_builds_non_empty_graph(extractor: str) -> None:
    """A deterministic fact_extractor must project a non-empty entity graph.

    Before the fix: skip_llm=True killed the lede leg, so entities stayed 0
    and the graph was empty (pure vector RAG)."""
    assert _DSN is not None
    ns = f"rev_dx_{uuid.uuid4().hex[:8]}"
    rev = PgRaggraphRevisor(
        dsn=_DSN,
        namespace=ns,
        evolution_tier="structural",
        fact_extractor=extractor,
    )
    rev.ingest_evidence(
        stele_ref=f"stele://{ns}/mem-1",
        text=_ENTITY_RICH,
        namespace=ns,
        effective_from=datetime.now(UTC),
    )
    n = _entity_count(ns)
    rev.close()
    assert n > 0, (
        f"fact_extractor={extractor!r} built an empty graph (entities=0) — "
        f"the deterministic lede leg is still suppressed"
    )


def test_none_extractor_stays_pure_vector() -> None:
    """The default ``fact_extractor='none'`` must NOT build a graph — the
    LLM-free invariant for the default path. Guards against the fix
    accidentally enabling extraction when it should be off."""
    assert _DSN is not None
    ns = f"rev_dx_{uuid.uuid4().hex[:8]}"
    rev = PgRaggraphRevisor(
        dsn=_DSN,
        namespace=ns,
        evolution_tier="structural",
        fact_extractor="none",
    )
    rev.ingest_evidence(
        stele_ref=f"stele://{ns}/mem-1",
        text=_ENTITY_RICH,
        namespace=ns,
        effective_from=datetime.now(UTC),
    )
    n = _entity_count(ns)
    rev.close()
    assert n == 0, (
        f"fact_extractor='none' built entities={n} — the default path should "
        f"stay LLM-free / graph-free"
    )
