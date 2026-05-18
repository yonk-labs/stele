"""Phase 7 exit bar — the runtime loop proven for real, in-process.

observe tool result -> store artifact -> update WorkGraph -> extract memory
-> recall/pack context -> resume. PII never reaches packed context; every
packed claim carries a stele:// ref.
"""

from __future__ import annotations

from stele.core.stash import Stele
from stele.runtime.demo import SteleAgentSession
from stele.workgraph.store import InProcessWorkGraphStore

_PII_EMAIL = "alice@example.com"
_FACT = "the deploy region is eu-west-1"
_TOOL_OUTPUT = (
    "Build log follows. Contact the owner at " + _PII_EMAIL + " if it fails. "
    "Important: " + _FACT + ". " + ("filler line. " * 400)
)


def _session() -> SteleAgentSession:
    stele = Stele.from_config({"backend": {"type": "memory"}})
    return SteleAgentSession(
        stele=stele, wg_store=InProcessWorkGraphStore(),
        namespace="loop", session_id="sess-1",
    )


def test_runtime_loop_end_to_end() -> None:
    s = _session()
    gid = s.start("debug the failing build")
    assert gid

    node = s.observe_tool("Bash", _TOOL_OUTPUT)
    assert node.kind == "tool_call"
    assert node.source_refs[0].startswith("stele://")

    pack = s.recall_and_pack(query="what is the deploy region")
    # the answer-bearing fact survived capture->memory->recall->pack
    assert "eu-west-1" in pack.dynamic_context
    # every packed dynamic line carries a stele:// ref
    for line in [ln for ln in pack.dynamic_context.splitlines() if ln.strip()]:
        assert "stele://" in line
    assert any(h.startswith("stele://") for h in pack.recovery_handles)
    assert pack.stable_context and "session=sess-1" in pack.stable_context

    # PII never leaks into packed context or the resume view
    assert _PII_EMAIL not in pack.dynamic_context
    assert _PII_EMAIL not in pack.stable_context
    resume = s.resume()
    assert _PII_EMAIL not in resume
    assert "# debug the failing build" in resume
    assert "stele://" in resume  # drill-down refs present

    h = s.health()
    assert h.recall_available is True
    assert h.status in ("healthy", "degraded")  # never silently broken

    assert s.end() == 1
    assert s.end() == 0  # idempotent session-end flush
