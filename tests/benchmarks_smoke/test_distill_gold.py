from __future__ import annotations

from benchmarks.external.memory_modes.distill_gold import GOLD, score_view


def test_gold_has_all_six_modes() -> None:
    assert set(GOLD) == {"facts", "precedents", "state", "skills", "best_practices", "rules"}
    # rules include the gpt-4o -> gpt-5-mini pair, in-family
    assert any(
        r["dont"] == "use gpt-4o" and r["do_instead"] == "use gpt-5-mini"
        for r in GOLD["rules"]
    )


def test_scorer_returns_precision_recall_and_hit_at_1() -> None:
    s = score_view("facts", predicted_ids=["pg-raggraph", "lede"])
    assert 0.0 <= s["recall"] <= 1.0
    assert 0.0 <= s["precision"] <= 1.0
    assert s["hit_at_1"] in (0.0, 1.0)

    perfect = score_view("facts", predicted_ids=[g["id"] for g in GOLD["facts"]])
    assert perfect["recall"] == 1.0
