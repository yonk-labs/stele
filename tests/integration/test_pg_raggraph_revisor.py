import os
from datetime import UTC, datetime, timedelta

import pytest

from stele.core.exceptions import OptionalDependencyError, ValidationError
from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

_DSN = os.environ.get("STELE_PG_RAGGRAPH_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="STELE_PG_RAGGRAPH_DSN unset")


def _rev(ns: str) -> PgRaggraphRevisor:
    assert _DSN is not None
    return PgRaggraphRevisor(dsn=_DSN, namespace=ns, evolution_tier="structural")


def test_ingest_then_search_recovers_stele_ref() -> None:
    r = _rev("rev_it1")
    ref = "stele://rev_it1/mem-1"
    t0 = datetime.now(UTC) - timedelta(hours=1)
    r.ingest_evidence(
        stele_ref=ref,
        text="The capital of Atlantis is Poseidonis.",
        namespace="rev_it1",
        effective_from=t0,
    )
    hits = r.search_current(
        "capital of Atlantis",
        namespace="rev_it1",
        limit=5,
        retracted_behavior="surface_both",
        version_filter=None,
    )
    assert any(h.stele_ref == ref for h in hits)
    r.close()


def test_retract_hide_is_absolute_and_naive_rejected() -> None:
    r = _rev("rev_it2")
    ref = "stele://rev_it2/mem-1"
    t0 = datetime.now(UTC) - timedelta(hours=1)
    r.ingest_evidence(
        stele_ref=ref,
        text="Atlantis capital is Poseidonis.",
        namespace="rev_it2",
        effective_from=t0,
    )
    assert r.retract(stele_ref=ref, reason="proof") == 1
    assert r.retract(stele_ref=ref) == 1  # idempotent (still matches the row)
    hide = r.search_current(
        "Atlantis capital",
        namespace="rev_it2",
        limit=5,
        retracted_behavior="hide",
        version_filter=None,
    )
    assert not [h for h in hide if h.stele_ref == ref]
    flag = r.search_current(
        "Atlantis capital",
        namespace="rev_it2",
        limit=5,
        retracted_behavior="flag",
        version_filter=None,
    )
    assert any(h.stele_ref == ref and h.retracted for h in flag)
    with pytest.raises(ValidationError):
        r.retract(stele_ref=ref, retracted_at=datetime(2020, 1, 1))  # naive
    r.close()


def test_search_as_of_requires_tz_aware() -> None:
    r = _rev("rev_it3")
    with pytest.raises(ValidationError):
        r.search_as_of(
            "q",
            namespace="rev_it3",
            limit=5,
            as_of=datetime(2020, 1, 1),
            retracted_behavior="hide",
            version_filter=None,
        )
    r.close()


def test_missing_extra_raises_optional_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stele.revisor.pg_raggraph_revisor as m

    monkeypatch.setattr(m, "find_spec", lambda name: None)
    with pytest.raises(OptionalDependencyError):
        PgRaggraphRevisor(
            dsn="postgresql://x/y", namespace="n", evolution_tier="structural"
        )
