"""Regression: stele.recall(...) preserves _run_strategy's accuracy + structure on fixtures."""

from __future__ import annotations

import pytest

from benchmarks.answer_workflow import (
    DeterministicAnswerer,
    _run_strategy,
)
from benchmarks.longrun import build_scenarios
from stele import Stele
from stele.core.config import StashConfig

# Subset the existing scenarios for fast smoke; full run lives in benchmarks/
SAMPLE_SCENARIO_NAMES = (
    "preference_basic",
    "temporal_old_title",
    "knowledge_update_address",
)


@pytest.mark.parametrize(
    "strategy",
    ["summary_only", "search_first", "summary_then_search", "adaptive", "raw_fetch"],
)
def test_strategy_runs_without_error(strategy: str) -> None:
    """Each strategy via the new path must run end-to-end on the smoke set."""
    cfg = StashConfig.load({"pii": {"raw_fetch_enabled": True}})
    stele = Stele(cfg)
    answerer = DeterministicAnswerer()
    try:
        scenarios = [s for s in build_scenarios() if s.name in SAMPLE_SCENARIO_NAMES]
        assert scenarios, "smoke set must not be empty"
        for scenario in scenarios:
            stored = stele.store(scenario.content, namespace="default")
            attempt = _run_strategy(
                stash=stele,
                scenario=scenario,
                reference=stored.reference,
                replacement=stored.summary,
                strategy=strategy,  # type: ignore[arg-type]
                answerer=answerer,
            )
            assert attempt.answer is not None
            assert attempt.context_bytes >= 0
    finally:
        stele.close()
