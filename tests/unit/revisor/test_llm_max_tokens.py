"""The graph LLM's ``max_tokens`` is an opt-in knob whose default is absence.

Why this exists: pg-raggraph sends ``max_tokens`` on its JSON-mode extraction
calls only when ``llm_max_tokens > 0``. A server with a small completion
default (mlx-lm caps at 512) truncates the extraction JSON mid-object; it then
parses as empty and yields a chunks-only store with ZERO entities — the same
silent-empty-graph failure as #91, arriving from the server side rather than
the config side. Operators need to be able to raise the cap.

The default must OMIT the key entirely (not send 0, not send a stele-chosen
number), so the request stays byte-identical to before the knob existed and
the server's own default keeps applying.

Pure unit test — construction does not connect, so no DSN/LLM needed.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from stele.core.config import GraphConfig
from stele.revisor.pg_raggraph_revisor import PgRaggraphRevisor

_DSN = "postgresql://user:pw@localhost:5432/db"
_LLM: dict[str, Any] = {
    "fact_extractor": "llm",
    "llm_base_url": "http://localhost:8000/v1",
}


def _cfg(**kwargs: Any) -> dict[str, Any]:
    rev = PgRaggraphRevisor(
        dsn=_DSN, namespace="n", evolution_tier="structural", **kwargs
    )
    return rev._cfg("surface_both", "prefer_new")


def test_default_omits_max_tokens_entirely() -> None:
    """Not 0, not a default number — the key is absent, so the server decides."""
    assert "llm_max_tokens" not in _cfg(**_LLM)


def test_opt_in_threads_max_tokens_to_the_graph() -> None:
    assert _cfg(**_LLM, llm_max_tokens=4096)["llm_max_tokens"] == 4096


def test_explicit_zero_still_omits() -> None:
    """0 is the documented 'let the server decide' value, not a real cap."""
    assert "llm_max_tokens" not in _cfg(**_LLM, llm_max_tokens=0)


def test_omitted_when_no_llm_is_in_play() -> None:
    """A deterministic extractor calls no LLM, so no LLM keys are threaded --
    setting max_tokens must not smuggle one into the cfg."""
    cfg = _cfg(fact_extractor="lede_prose", llm_max_tokens=4096)
    assert "llm_max_tokens" not in cfg
    assert "llm_base_url" not in cfg


def test_config_default_is_zero_and_negative_is_rejected() -> None:
    assert GraphConfig().llm_max_tokens == 0
    assert GraphConfig(llm_max_tokens=4096).llm_max_tokens == 4096
    with pytest.raises(PydanticValidationError):
        GraphConfig(llm_max_tokens=-1)
