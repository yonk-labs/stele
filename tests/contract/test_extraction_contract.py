"""Cross-backend extraction contract — memory + sqlite + postgres."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from stele import Stele
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryScope


def _backend_configs() -> list[tuple[str, dict[str, object]]]:
    configs: list[tuple[str, dict[str, object]]] = [
        ("memory", {"backend": {"type": "memory"}}),
    ]
    tmp = Path(tempfile.mkdtemp())
    configs.append(
        ("sqlite", {"backend": {"type": "sqlite", "path": str(tmp / "stele.db")}}),
    )
    pg_dsn = os.environ.get("STELE_PG_DSN")
    if pg_dsn:
        configs.append(("postgres", {"backend": {"type": "postgres", "dsn": pg_dsn}}))
    return configs


@pytest.mark.parametrize("backend_name,config_dict", _backend_configs())
def test_extraction_contract_basic_flow(
    backend_name: str, config_dict: dict[str, object]
) -> None:
    cfg = StashConfig.load(config_dict)
    stele = Stele(cfg)
    try:
        report = stele.extract.from_text(
            text="I prefer dark mode. Q1 revenue grew 12%.",
            source_refs=["stele://default/abc"],
            scope=MemoryScope(user_id="contract"),
        )
        assert report.stats.candidate_count >= 1
        assert isinstance(report.config_fingerprint, str)
        assert len(report.config_fingerprint) == 64
        for accepted in report.accepted:
            stored = stele.memory.get(accepted.stored_id)
            assert stored is not None
            assert stored.text == accepted.candidate.text
            assert stored.source_refs == ["stele://default/abc"]
    finally:
        stele.close()
