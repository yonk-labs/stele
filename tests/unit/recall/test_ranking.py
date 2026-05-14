"""Tests for score normalization and hit merging."""

from __future__ import annotations

from stele.recall.models import Citation
from stele.recall.ranking import merge_hits, normalize_scores


def _cit(kind: str, id: str, ref: str, score: float) -> Citation:
    return Citation(
        kind=kind,  # type: ignore[arg-type]
        id=id,
        reference=ref,
        score=score,
        snippet="x",
    )


def test_normalize_scores_zero_input() -> None:
    out = normalize_scores([])
    assert out == []


def test_normalize_scores_clamps_to_unit_interval() -> None:
    cits = [
        _cit("memory", "m1", "stele://default/a", 5.0),
        _cit("memory", "m2", "stele://default/a", 2.5),
        _cit("memory", "m3", "stele://default/a", 0.0),
    ]
    out = normalize_scores(cits)
    assert max(c.score for c in out) == 1.0
    assert min(c.score for c in out) == 0.0
    assert out[1].score == 0.5  # linear normalization across [min, max]


def test_normalize_scores_single_hit_becomes_one() -> None:
    out = normalize_scores([_cit("memory", "m1", "stele://default/a", 7.0)])
    assert out[0].score == 1.0


def test_normalize_scores_all_equal_becomes_one() -> None:
    cits = [
        _cit("memory", "m1", "stele://default/a", 0.7),
        _cit("memory", "m2", "stele://default/a", 0.7),
    ]
    out = normalize_scores(cits)
    assert all(c.score == 1.0 for c in out)


def test_merge_hits_dedups_by_kind_and_id_keeping_max() -> None:
    a = [
        _cit("memory", "m1", "stele://default/a", 0.3),
        _cit("memory", "m2", "stele://default/a", 0.4),
    ]
    b = [
        _cit("memory", "m1", "stele://default/a", 0.9),  # duplicate of a[0], higher
        _cit("chunk", "c1", "stele://default/a", 0.5),
    ]
    out = merge_hits(a, b)
    by_key = {(c.kind, c.id): c for c in out}
    assert by_key[("memory", "m1")].score == 0.9
    assert by_key[("memory", "m2")].score == 0.4
    assert by_key[("chunk", "c1")].score == 0.5
    assert len(out) == 3


def test_merge_hits_sorts_descending_by_score() -> None:
    out = merge_hits(
        [_cit("memory", "m1", "stele://default/a", 0.2)],
        [_cit("memory", "m2", "stele://default/a", 0.9)],
        [_cit("chunk", "c1", "stele://default/a", 0.5)],
    )
    scores = [c.score for c in out]
    assert scores == sorted(scores, reverse=True)
