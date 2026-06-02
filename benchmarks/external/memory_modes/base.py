"""The pluggable Mode contract + shared data types.

A Mode owns three things: how its corpus is built (synthetic and/or mined from
real stele traces), how memory gets populated from that corpus, and how one
case runs + scores under a condition. The runner (run.py) owns everything else:
the answerer/judge wiring, the namespace lifecycle, and the JSON write. Modes
never touch the network directly or write files; they call through a RunCtx.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from stele.core.stash import Stele

# Condition labels a mode may use. The runner does not enforce a fixed set; a
# mode declares its own `conditions` tuple and may legitimately use a subset.
# e.g. "no_memory" | "prompt_stuffed" | "memory_driven" | "memory_kw" | "memory_vec"
Condition = str

# Where a case came from. Both are first-class; every result is labeled with it.
Source = str  # "synthetic" | "real_trace"


@dataclass(frozen=True)
class Case:
    """One scored unit of work. `payload` is mode-private (gold metadata,
    event logs, relevant-rule ids, the dia_id join key, etc.)."""

    case_id: str
    question: str
    gold: str
    source: Source = "synthetic"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseResult:
    """What `run_case` produced under one condition, before final scoring."""

    output: str  # the model answer OR the produced artifact text
    metric: dict[str, float]  # mode-defined deterministic numbers
    tokens_in: int  # context/guard tokens charged to this condition
    tokens_out: int
    deterministic: bool  # True if `metric` needed no LLM judge
    extra: dict[str, Any] = field(default_factory=dict)  # mrr, retr_ms, refs, ...


@dataclass
class RunCtx:
    """Everything a mode needs from the outside world, injected by the runner.

    Passing this (instead of importing module-level answerers) keeps modes
    unit-testable with fakes and keeps all network wiring in one place."""

    # (context, question) -> answer string. The QA framing (_answer): "answer
    # using ONLY this memory." For recall modes.
    answer: Callable[[str, str], str]
    # (prompt) -> completion string. A raw single-prompt completion, for modes
    # whose task is "do this" (guardrail/skill writing tasks), not "answer this."
    complete: Callable[[str], str]
    # (question, expected, answer) -> correct bool. None when --no-judge.
    judge: Callable[..., bool] | None
    # text -> token count (tiktoken if available, else chars/4).
    count_tokens: Callable[[str], int]
    # True when the store was built with retrieval.memory_vector on.
    memory_vector: bool = False


@runtime_checkable
class Mode(Protocol):
    """The whole contract: declarative attrs + corpus/populate/run_case/score."""

    name: str  # stamped into results, e.g. "guardrail_adherence"
    conditions: tuple[Condition, ...]
    deterministic: bool  # True if the mode never needs an LLM judge for its headline
    # The honesty box, copied verbatim into the consolidated doc / blog:
    measured: str
    not_measured: str

    def corpus(self, source: Source, n: int, seed: int) -> list[Case]:
        """Build the case list for `source`. Synthetic is seeded + inline;
        real_trace mines actual stele data (LoCoMo, .remember/, WorkGraph logs,
        the memory store). May return [] for a source the mode cannot honestly
        supply gold for."""
        ...

    def populate(self, store: Stele, cases: list[Case]) -> None:
        """Seed durable state ONCE for the whole case list: store artifacts,
        memory.add(...), WorkGraph nodes. Idempotent against a purged namespace."""
        ...

    def run_case(
        self, store: Stele, case: Case, condition: Condition, ctx: RunCtx
    ) -> CaseResult:
        """Exercise ONE case under ONE condition. No scoring, no file writes."""
        ...

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        """Final per-case metric. Deterministic where possible."""
        ...
