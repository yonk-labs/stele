"""Phase-2 improvement: from_messages retains verbatim turn text so exact
answer-bearing literals (dates, names, ids) survive extraction — Stele's
'exact evidence' thesis, and the LoCoMo recall lever."""

from __future__ import annotations

from stele.core.config import ExtractionConfig, StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope
from stele.core.stash import Stele


def test_default_retains_message_text() -> None:
    assert ExtractionConfig().retain_message_text is True


def test_from_messages_preserves_verbatim_literal() -> None:
    stele = Stele.from_config(StashConfig())
    scope = MemoryScope(namespace="rt")
    stele.extract.from_messages(
        messages=[
            {"role": "Alice", "content": "Quick sync about logistics."},
            {"role": "Bob",
             "content": "Confirmed: the migration window is 2026-11-03 at "
                        "0400 UTC, owner is Priya."},
        ],
        scope=scope,
    )
    hits = stele.memory.search(MemoryQuery(query="migration window", scope=scope))
    blob = " ".join(h.text for h in hits)
    assert "2026-11-03" in blob, "verbatim date lost — extraction abstracted it"
    assert "Priya" in blob
    stele.close()


def test_retain_disabled_falls_back_to_lede_only() -> None:
    cfg = StashConfig()
    cfg = cfg.model_copy(
        update={"extraction": cfg.extraction.model_copy(
            update={"retain_message_text": False})}
    )
    stele = Stele(cfg)
    scope = MemoryScope(namespace="rt2")
    report = stele.extract.from_messages(
        messages=[{"role": "u", "content": "The deploy region is eu-west-1."}],
        scope=scope,
    )
    assert report.stats.candidate_count >= 1  # Phase-2 contract still holds
    stele.close()
