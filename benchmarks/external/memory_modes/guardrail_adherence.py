# ruff: noqa: E501 -- benchmark helper.
"""Mode: guardrail-adherence. Enforcement, negative polarity ("never do this").

Stored memories are rules to obey, not facts to recall. The metric is a
deterministic regex violation rate (no LLM judge). The agent-under-test is Qwen;
the judge endpoint is never called. The mode is a family of `RuleChecker`s;
adding a rule is one dataclass instance plus one pure detector.

This file also exports the shared rule machinery (`Rule`, `RULES`, the recall +
guarded-write helpers) so the positive `skill_adherence` and suggested
`best_practice` twins reuse it without copy-paste.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from benchmarks.external.memory_modes.base import Case, CaseResult, Condition, RunCtx
from stele.core.memory_record import AddRequest, MemoryKind, MemoryScope
from stele.core.stash import Stele


@dataclass(frozen=True)
class Rule:
    rule_id: str
    kind: MemoryKind  # instruction | pitfall | workaround
    summary: str  # one-line rule
    action: str  # the injected enforcement payload ("what to DO")
    detect: Callable[[str], int]  # -> count of violations in the text (0 == clean)


def _emdash(text: str) -> int:
    return len(re.findall(r"[—–]", text)) + len(re.findall(r" -- ", text))


def _word(pat: str) -> Callable[[str], int]:
    rx = re.compile(pat, re.IGNORECASE)
    return lambda out: len(rx.findall(out))


# The deterministically-checkable negative rulebook (synthetic source).
RULES: tuple[Rule, ...] = (
    Rule("G-EMDASH", "instruction", "Never use em-dashes or en-dashes in prose",
         "Use a period, colon, comma, or parentheses instead of a dash", _emdash),
    Rule("G-LEVERAGE", "pitfall", "Never use 'leverage' as a verb",
         "Write 'use' instead of 'leverage'", _word(r"\bleverage\b")),
    Rule("G-UTILIZE", "pitfall", "Never use 'utilize'",
         "Write 'use' instead of 'utilize'", _word(r"\butiliz\w*")),
    Rule("G-DELVE", "pitfall", "Never use 'delve'",
         "Write 'dig into' or 'look at' instead of 'delve'", _word(r"\bdelv\w*")),
    Rule("G-TODO", "pitfall", "No TODO or FIXME markers in delivered text",
         "Resolve or remove TODO/FIXME before delivering", _word(r"\b(?:TODO|FIXME)\b")),
)

# A handful of real corrections this project actually enforces, used as the
# real_trace source for the guardrail mode (the em-dash rule is the canonical
# one; it is a genuine standing rule for this user, not invented for the test).
REAL_RULES: tuple[Rule, ...] = (
    RULES[0],  # G-EMDASH is a real, standing rule
    RULES[1],  # G-LEVERAGE
    RULES[2],  # G-UTILIZE
)


# Writing micro-tasks engineered to give the base model a real chance to
# violate (em-dashes especially). `relevant` is for scoring only, never shown.
@dataclass(frozen=True)
class WriteTask:
    task_id: str
    prompt: str
    relevant: tuple[str, ...]  # rule_ids this task can plausibly violate


_TASKS: tuple[WriteTask, ...] = (
    WriteTask("t-aside", "Write two sentences about why benchmarks matter, using a dramatic aside in the middle.",
              ("G-EMDASH",)),
    WriteTask("t-corp", "Write one sentence of corporate-sounding praise for a data platform.",
              ("G-LEVERAGE", "G-UTILIZE")),
    WriteTask("t-explain", "Write one sentence that says you will explore a topic in depth.",
              ("G-DELVE",)),
    WriteTask("t-code", "Write a short code comment marking work left to do later.",
              ("G-TODO",)),
    WriteTask("t-range", "Write one sentence giving a numeric range and a parenthetical clarification.",
              ("G-EMDASH",)),
)


def _rules_for(source: str) -> tuple[Rule, ...]:
    return REAL_RULES if source == "real_trace" else RULES


def populate_rules(store: Stele, ns: str, rules: tuple[Rule, ...]) -> None:
    """Store each rule as one memory citing a shared rulebook artifact."""
    scope = MemoryScope(namespace=ns, agent_id="writer")
    ref = store.store("RULEBOOK\n" + "\n".join(r.summary for r in rules), namespace=ns).reference
    store.memory.add_many([
        AddRequest(text=r.summary, kind=r.kind, source_refs=[ref], scope=scope,
                   summary=r.summary, action=r.action)
        for r in rules
    ])


def guarded_write(store: Stele, ns: str, task: WriteTask, condition: Condition,
                  ctx: RunCtx, rules: tuple[Rule, ...]) -> tuple[str, int, int]:
    """Run one writing task under one condition. Returns (output, guard_tokens, n_rules_carried)."""
    scope = MemoryScope(namespace=ns, agent_id="writer")
    if condition == "no_memory":
        guard, carried = "", 0
    elif condition == "prompt_stuffed":
        guard = "\n".join(f"- {r.summary}: {r.action}" for r in rules)
        carried = len(rules)
    else:  # memory_driven
        hits = store.memory.search_with_score(task.prompt, scope, limit=4)
        guard = "\n".join(
            f"- {h.record.summary}: {h.record.action or ''}" for h in hits
        )
        carried = len(hits)
    prompt = (
        "Do the following writing task. Obey every rule listed under RULES exactly.\n\n"
        f"RULES:\n{guard or '(none)'}\n\nTASK: {task.prompt}"
    )
    out = ctx.complete(prompt)
    return out, ctx.count_tokens(guard), carried


class GuardrailAdherence:
    name = "guardrail_adherence"
    conditions: tuple[Condition, ...] = ("no_memory", "prompt_stuffed", "memory_driven")
    deterministic = True
    measured = (
        "Whether stored 'never do X' rules, recalled and injected, lower a "
        "deterministic regex violation rate vs no memory and vs stuffing every "
        "rule in the prompt, and at what guard-token cost."
    )
    not_measured = (
        "Semantic style rules a regex cannot judge; cross-session persistence of "
        "a one-correction fix (a follow-up sub-protocol); end-to-end task quality "
        "beyond rule compliance."
    )

    def corpus(self, source: str, n: int, seed: int) -> list[Case]:
        rules = _rules_for(source)
        active = {r.rule_id for r in rules}
        cases: list[Case] = []
        for t in _TASKS:
            rel = tuple(r for r in t.relevant if r in active)
            if not rel:
                continue
            cases.append(Case(
                case_id=f"{t.task_id}-{source}", question=t.prompt, gold="0 violations",
                source=source, payload={"task_id": t.task_id, "relevant": rel},
            ))
        return cases[:n] if n else cases

    def populate(self, store: Stele, cases: list[Case]) -> None:
        if not cases:
            return
        source = cases[0].source
        ns = f"memmode-{self.name}-{source}"
        populate_rules(store, ns, _rules_for(source))

    def run_case(self, store: Stele, case: Case, condition: Condition, ctx: RunCtx) -> CaseResult:
        ns = f"memmode-{self.name}-{case.source}"
        rules = _rules_for(case.source)
        task = WriteTask(case.payload["task_id"], case.question, tuple(case.payload["relevant"]))
        out, guard_tokens, carried = guarded_write(store, ns, task, condition, ctx, rules)
        by_id = {r.rule_id: r for r in rules}
        viols = {rid: by_id[rid].detect(out) for rid in case.payload["relevant"] if rid in by_id}
        total = sum(viols.values())
        return CaseResult(
            output=out,
            metric={"violations": float(total)},
            tokens_in=guard_tokens,
            tokens_out=ctx.count_tokens(out),
            deterministic=True,
            extra={"rules_carried": carried, "per_rule": viols},
        )

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        # violation = 1 if any relevant rule fired, else 0 (aggregate -> rate)
        return {"violation": 1.0 if result.metric["violations"] > 0 else 0.0,
                "violations": result.metric["violations"]}
