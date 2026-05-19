"""RED spec (systematic-debugging Phase 4 / TDD): opting into LLM graph
extraction must make the Revisor build a NON-EMPTY entity graph.

Root cause this pins down (proven 2026-05-18 by direct boundary probing +
reading pg-raggraph 0.3.0a3 source):

  * ``PgRaggraphRevisor._cfg()`` hardcodes ``skip_extraction=True`` and
    ``ingest_evidence`` sends every record with ``"skip_llm": True``.
  * pg-raggraph's only extraction gate is
    ``if not skip_extraction and llm_base_url`` (__init__.py:368,596);
    ``fact_extractor`` is read by no code (phantom config).
  * Result: ``documents``/``chunks`` populate but ``entities`` /
    ``relationships`` / ``facts`` stay at 0, so ``graph_search`` is
    degenerate cold-vector search (42.5% on LoCoMo, below keyword/hybrid).

The fix (Path A — user opted into LLM-for-raggraph, opt-in/non-default):
the Revisor gains an opt-in LLM-extraction path that, when selected,
passes ``skip_extraction=False`` + ``llm_base_url``/``llm_model``/
``llm_api_key`` to pg-raggraph and stops forcing per-record
``skip_llm=True``. This test is the executable spec for that and FAILS
today (no such API; graph stays empty).

Env-gated like the other backend suites (CLAUDE.md: skip silently when
the env vars are unset):

  STELE_PG_RAGGRAPH_DSN   e.g. postgresql://yonk:yonk@localhost:55453/stele
  STELE_GRAPH_LLM_BASE_URL e.g. http://192.168.1.193:8000/v1
  STELE_GRAPH_LLM_MODEL    e.g. Intel/Qwen3-Coder-Next-int4-AutoRound
  STELE_GRAPH_LLM_API_KEY  optional
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

_DSN = os.environ.get("STELE_PG_RAGGRAPH_DSN")
_LLM_URL = os.environ.get("STELE_GRAPH_LLM_BASE_URL")
_LLM_MODEL = os.environ.get("STELE_GRAPH_LLM_MODEL")
_LLM_KEY = os.environ.get("STELE_GRAPH_LLM_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not (_DSN and _LLM_URL and _LLM_MODEL),
    reason="needs STELE_PG_RAGGRAPH_DSN + STELE_GRAPH_LLM_BASE_URL + "
    "STELE_GRAPH_LLM_MODEL",
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


def test_opt_in_llm_extraction_builds_non_empty_graph() -> None:
    """With LLM extraction opted in, ingesting entity-rich evidence must
    project a non-empty entity graph (the whole point of the graph path).

    FAILS today: PgRaggraphRevisor has no opt-in extraction parameter and
    forces skip_extraction=True + per-record skip_llm=True, so entities
    stays 0 and pg-raggraph stores chunks-only (pure vector RAG)."""
    assert _DSN is not None
    ns = f"rev_gx_{uuid.uuid4().hex[:8]}"

    # Wished-for API: opt-in LLM extraction (non-default).
    rev = PgRaggraphRevisor(
        dsn=_DSN,
        namespace=ns,
        evolution_tier="structural",
        fact_extractor="llm",
        llm_base_url=_LLM_URL,
        llm_model=_LLM_MODEL,
        llm_api_key=_LLM_KEY,
    )
    rev.ingest_evidence(
        stele_ref=f"stele://{ns}/mem-1",
        text=_ENTITY_RICH,
        namespace=ns,
        effective_from=datetime.now(UTC),
    )
    assert _entity_count(ns) > 0, (
        "graph is empty after opt-in LLM extraction — the Revisor still "
        "suppresses pg-raggraph entity extraction"
    )
    rev.close()
