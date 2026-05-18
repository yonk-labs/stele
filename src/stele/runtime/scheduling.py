"""Adapter scheduling (T-RAM-008).

Warm-up turns 1/2/4/8, then queue-size / idle-timeout driven. Injectable
clock (fake clock in tests — no real sleeps). Per-session queues; flushing
one session never touches another; session flush is idempotent;
``flush_all`` reports leftovers explicitly (never silent drop).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


class SchedulingPolicy(BaseModel):
    warmup_turns: tuple[int, ...] = (1, 2, 4, 8)
    queue_high_water: int = 20
    idle_seconds: float = 300.0


class SessionScheduler:
    def __init__(
        self,
        *,
        policy: SchedulingPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy or SchedulingPolicy()
        self._clock = clock
        self._turns: dict[str, int] = {}
        self._queues: dict[str, list[Any]] = {}
        self._last_proc: dict[str, float] = {}

    def enqueue(self, session_id: str, item: Any) -> None:
        self._queues.setdefault(session_id, []).append(item)

    def queue_depth(self, session_id: str) -> int:
        return len(self._queues.get(session_id, []))

    def should_process(self, session_id: str) -> bool:
        now = self._clock()
        self._last_proc.setdefault(session_id, now)
        turn = self._turns.get(session_id, 0) + 1
        self._turns[session_id] = turn

        trigger = (
            turn in self.policy.warmup_turns
            or self.queue_depth(session_id) >= self.policy.queue_high_water
            or (now - self._last_proc[session_id]) >= self.policy.idle_seconds
        )
        if trigger:
            self._last_proc[session_id] = now
        return trigger

    def mark_processed(self, session_id: str) -> None:
        self._last_proc[session_id] = self._clock()
        self._queues[session_id] = []

    def flush_session(self, session_id: str) -> list[Any]:
        """Return + clear ONLY this session's queue. Idempotent."""
        items = self._queues.get(session_id, [])
        self._queues[session_id] = []
        return items

    def flush_all(
        self, *, max_items: int | None = None
    ) -> tuple[list[Any], list[Any]]:
        """Bounded flush across sessions (deterministic session order).
        Returns (flushed, leftovers) — leftovers are explicit, never dropped.
        """
        flushed: list[Any] = []
        leftovers: list[Any] = []
        for sid in sorted(self._queues):
            for item in self._queues[sid]:
                if max_items is not None and len(flushed) >= max_items:
                    leftovers.append(item)
                else:
                    flushed.append(item)
            self._queues[sid] = []
        return flushed, leftovers
