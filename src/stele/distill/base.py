from __future__ import annotations

from typing import Protocol, runtime_checkable

from stele.core.memory_record import MemoryRecord, MemoryScope


@runtime_checkable
class LLMSynthesizer(Protocol):
    """Optional, injected. The distill package imports no LLM client at module
    top (enforced by test_architecture). When None, distillation runs
    deterministically."""

    def __call__(self, prompt: str) -> str: ...


def active_memories(memory: object, scope: MemoryScope, limit: int = 1000) -> list[MemoryRecord]:
    """All ACTIVE (newest-valid) memories in scope, via the public Memory facade.

    `memory` is a stele.core.memory.Memory; typed as object to avoid a heavy
    import here. Passes status_filter=["active"] so superseded/retracted records
    are excluded -- callers that name themselves "active_memories" should only
    return current truth."""
    result = memory.list(scope, ["active"], limit=limit)  # type: ignore[attr-defined]
    return list(result)
