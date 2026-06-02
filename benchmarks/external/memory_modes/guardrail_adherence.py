# ruff: noqa: E501 -- benchmark helper.
"""Mode: guardrail-adherence. Enforcement, negative polarity ("never do this").

Stored memories are rules to obey, not facts to recall. The metric is a
deterministic regex violation rate (no LLM judge). The agent-under-test is Qwen;
the judge endpoint is never called.

Selection is by APPLICABILITY DOMAIN, not query similarity. The first smoke
proved that recalling a guardrail by `search_with_score(task_prompt)` whiffs
(the task never shares vocabulary with the rule). So a rule declares the output
domain it governs (prose / markdown / python / sql), a task declares its domain,
and `memory_driven` carries the domain-matching rules pulled from the store via
`memory.list`. `prompt_stuffed` carries every rule (all domains + inert
distractors); the token-saving and adherence story is the difference.

This file also exports the shared rule machinery so the positive
`skill_adherence` and suggested `best_practice` twins reuse it.
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
    detect: Callable[[str], int]  # -> count of violations (0 == clean)
    domain: str = "prose"  # applicability: prose | markdown | python | sql


def _emdash(text: str) -> int:
    return len(re.findall(r"[—–]", text)) + len(re.findall(r" -- ", text))


def _word(pat: str) -> Callable[[str], int]:
    rx = re.compile(pat, re.IGNORECASE)
    return lambda out: len(rx.findall(out))


def _noop(_out: str) -> int:
    return 0


# Real, deterministically-checkable rules (these are scored).
RULES: tuple[Rule, ...] = (
    Rule("G-EMDASH", "instruction", "Never use em-dashes or en-dashes in prose",
         "Use a period, colon, comma, or parentheses instead of a dash", _emdash, "prose"),
    Rule("G-LEVERAGE", "pitfall", "Never use 'leverage' as a verb",
         "Write 'use' instead of 'leverage'", _word(r"\bleverage\b"), "prose"),
    Rule("G-UTILIZE", "pitfall", "Never use 'utilize'",
         "Write 'use' instead of 'utilize'", _word(r"\butiliz\w*"), "prose"),
    Rule("G-DELVE", "pitfall", "Never use 'delve'",
         "Write 'dig into' or 'look at' instead of 'delve'", _word(r"\bdelv\w*"), "prose"),
    Rule("G-TODO", "pitfall", "No TODO or FIXME markers in delivered code",
         "Resolve or remove TODO/FIXME before delivering", _word(r"\b(?:TODO|FIXME)\b"), "python"),
)

# Inert distractor rules in OTHER domains: never scored, exist so prompt_stuffed
# carries a big rulebook while domain-selected memory_driven carries only a few.
DISTRACTORS: tuple[Rule, ...] = tuple(
    Rule(f"D-{dom[:2].upper()}{i}", "instruction", f"{dom} house rule #{i}",
         f"follow {dom} convention #{i}", _noop, dom)
    for dom in ("sql", "markdown", "python", "yaml", "json")
    for i in range(1, 4)
)  # 15 inert distractors across 5 non-prose-only domains

ALL_RULES: tuple[Rule, ...] = RULES + DISTRACTORS

# Real corrections this project actually enforces (real_trace source). The
# em-dash rule is a genuine standing rule for this user, not invented for the test.
REAL_RULES: tuple[Rule, ...] = (RULES[0], RULES[1], RULES[2])


@dataclass(frozen=True)
class WriteTask:
    task_id: str
    prompt: str
    domain: str
    relevant: tuple[str, ...]  # real rule_ids this task can violate (scoring only)


_TASKS: tuple[WriteTask, ...] = (
    WriteTask("t-aside", "Write two sentences about why benchmarks matter, using a dramatic aside in the middle.",
              "prose", ("G-EMDASH",)),
    WriteTask("t-corp", "Write one sentence of corporate-sounding praise for a data platform.",
              "prose", ("G-LEVERAGE", "G-UTILIZE")),
    WriteTask("t-explain", "Write one sentence promising to examine a topic in great depth.",
              "prose", ("G-DELVE",)),
    WriteTask("t-range", "Write one sentence giving a numeric range with a parenthetical clarification.",
              "prose", ("G-EMDASH",)),
    WriteTask("t-code", "Write a short Python function stub with a comment marking work left to do later.",
              "python", ("G-TODO",)),
)


def _rules_for(source: str) -> tuple[Rule, ...]:
    """The REAL (scored) rules active for a source."""
    return REAL_RULES if source == "real_trace" else RULES


def _populate_set(source: str) -> tuple[Rule, ...]:
    """Everything stored (real + distractors) so selection is non-trivial."""
    return REAL_RULES if source == "real_trace" else ALL_RULES


def populate_rules(store: Stele, ns: str, rules: tuple[Rule, ...], *, agent_id: str = "writer") -> None:
    """Store each rule as one memory citing a shared rulebook artifact; domain in metadata."""
    scope = MemoryScope(namespace=ns, agent_id=agent_id)
    ref = store.store("RULEBOOK\n" + "\n".join(r.summary for r in rules), namespace=ns).reference
    store.memory.add_many([
        AddRequest(text=r.summary, kind=r.kind, source_refs=[ref], scope=scope,
                   summary=r.summary, action=r.action,
                   metadata={"rule_id": r.rule_id, "domain": r.domain})
        for r in rules
    ])


def select_by_domain(store: Stele, ns: str, domain: str, *, agent_id: str = "writer") -> list[tuple[str, str]]:
    """Memory-driven selection: pull all stored rules, keep the ones whose
    domain matches the task. Returns (summary, action) pairs. This is the fix
    for similarity-recall whiffing on guardrails."""
    scope = MemoryScope(namespace=ns, agent_id=agent_id)
    out: list[tuple[str, str]] = []
    for m in store.memory.list(scope, limit=1000):
        if m.metadata.get("domain") == domain:
            out.append((m.summary or m.text, m.action or ""))
    return out


def guarded_write(store: Stele, ns: str, task: WriteTask, condition: Condition,
                  ctx: RunCtx, populate_set: tuple[Rule, ...]) -> tuple[str, int, int]:
    """One writing task under one condition. Returns (output, guard_tokens, n_rules_carried)."""
    if condition == "no_memory":
        guard, carried = "", 0
    elif condition == "prompt_stuffed":
        guard = "\n".join(f"- {r.summary}: {r.action}" for r in populate_set)
        carried = len(populate_set)
    else:  # memory_driven: applicability selection from the store
        pairs = select_by_domain(store, ns, task.domain)
        guard = "\n".join(f"- {s}: {a}" for s, a in pairs)
        carried = len(pairs)
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
        "Whether stored 'never do X' rules, selected by applicability domain and "
        "injected, lower a deterministic regex violation rate vs no memory and vs "
        "stuffing the whole rulebook, and at what guard-token cost as the rulebook grows."
    )
    not_measured = (
        "Semantic style rules a regex cannot judge; cross-session persistence of a "
        "one-correction fix (a follow-up sub-protocol); task quality beyond compliance."
    )

    def corpus(self, source: str, n: int, seed: int) -> list[Case]:
        active = {r.rule_id for r in _rules_for(source)}
        cases: list[Case] = []
        for t in _TASKS:
            rel = tuple(r for r in t.relevant if r in active)
            if not rel:
                continue
            cases.append(Case(
                case_id=f"{t.task_id}-{source}", question=t.prompt, gold="0 violations",
                source=source, payload={"task_id": t.task_id, "domain": t.domain, "relevant": rel},
            ))
        return cases[:n] if n else cases

    def populate(self, store: Stele, cases: list[Case]) -> None:
        if not cases:
            return
        source = cases[0].source
        ns = f"memmode-{self.name}-{source}"
        populate_rules(store, ns, _populate_set(source))

    def run_case(self, store: Stele, case: Case, condition: Condition, ctx: RunCtx) -> CaseResult:
        ns = f"memmode-{self.name}-{case.source}"
        task = WriteTask(case.payload["task_id"], case.question, case.payload["domain"], tuple(case.payload["relevant"]))
        out, guard_tokens, carried = guarded_write(store, ns, task, condition, ctx, _populate_set(case.source))
        by_id = {r.rule_id: r for r in _rules_for(case.source)}
        viols = {rid: by_id[rid].detect(out) for rid in case.payload["relevant"] if rid in by_id}
        total = sum(viols.values())
        return CaseResult(
            output=out,
            metric={"violations": float(total)},
            tokens_in=guard_tokens,
            tokens_out=ctx.count_tokens(out),
            deterministic=True,
            extra={"rules_carried": carried},
        )

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        return {"violation": 1.0 if result.metric["violations"] > 0 else 0.0,
                "violations": result.metric["violations"]}
