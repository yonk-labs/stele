"""RED spec (TDD): the Revisor exposes an opt-in graph-query tuning knob
(mode + rerank) whose DEFAULT preserves today's behavior.

Rationale: with a real LLM-built graph, the documented retrieval lever is
``query(mode="hybrid", rerank=True)`` instead of the default
``mode="smart", rerank=False``. This must be opt-in and default-safe so
the LLM-free / untuned default path is unchanged.

Pure unit test — construction does not connect, so no DSN/LLM needed.
Fails today: PgRaggraphRevisor has no query_mode/rerank parameters.
"""

from __future__ import annotations

from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

_DSN = "postgresql://user:pw@localhost:5432/db"


def test_query_tuning_defaults_preserve_current_behavior() -> None:
    rev = PgRaggraphRevisor(
        dsn=_DSN, namespace="n", evolution_tier="structural"
    )
    assert rev._query_mode == "smart"
    assert rev._rerank is False


def test_query_tuning_is_opt_in() -> None:
    rev = PgRaggraphRevisor(
        dsn=_DSN,
        namespace="n",
        evolution_tier="structural",
        query_mode="hybrid",
        rerank=True,
    )
    assert rev._query_mode == "hybrid"
    assert rev._rerank is True
