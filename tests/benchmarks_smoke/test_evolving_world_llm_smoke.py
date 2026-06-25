"""No-network smoke for the evolving-world real-LLM lane.

Exercises only the deterministic `ideal` extraction path (no model endpoint):
forced-stable extraction must supersede cleanly, leaving exactly the current
value active. The real-LLM path is covered by running the module against a live
endpoint, not in CI.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from benchmarks.evolving_world_llm import SCENARIOS, _active_values, _ingest_evolving
from stele import Stele
from stele.core.config import StashConfig


def test_ideal_extraction_supersedes_cleanly() -> None:
    with tempfile.TemporaryDirectory() as d:
        for idx, (canonical, aspect, steps) in enumerate(SCENARIOS):
            cfg = StashConfig.model_validate({
                "backend": {"type": "sqlite", "path": str(Path(d) / f"ew{idx}.db")},
                "extraction": {"enabled": True},
            })
            stele = Stele(cfg)
            ns = f"t{idx}"
            _ingest_evolving(stele, ns, canonical, aspect, steps, real_llm=None)
            active = _active_values(stele, ns, [v for _, v in steps])
            # Only the current (last) value may remain active under perfect extraction.
            assert active == [steps[-1][1]], (canonical, active)
