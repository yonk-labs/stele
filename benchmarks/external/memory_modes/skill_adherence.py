# ruff: noqa: E501 -- benchmark helper.
"""Mode: skill-adherence. Enforcement, positive polarity ("always do this").

A thin twin of guardrail_adherence: same store-backed, domain-selected rule
machinery, opposite scoring direction. A skill is a learned positive habit; the
detector measures APPLICATION (did the output do the thing) rather than
violation. Deterministic, no LLM judge (Qwen is the agent under test).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from benchmarks.external.memory_modes.base import Case, CaseResult, Condition, RunCtx
from benchmarks.external.memory_modes.guardrail_adherence import (
    Rule,
    WriteTask,
    populate_rules,
    select_by_domain,
)
from stele.core.stash import Stele


def _word(pat: str) -> Callable[[str], int]:
    rx = re.compile(pat, re.IGNORECASE)
    return lambda out: len(rx.findall(out))


def _pnpm(out: str) -> int:
    # applied iff it uses pnpm and not npm/yarn for an install
    return 1 if re.search(r"\bpnpm\b", out, re.I) and not re.search(r"\b(npm|yarn)\s+(i|install|add)\b", out, re.I) else 0


def _typehint(out: str) -> int:
    return 1 if re.search(r"def\s+\w+\([^)]*:\s*\w", out) and "->" in out else 0


# Positive skills (detect == application present). domain governs selection.
SKILLS: tuple[Rule, ...] = (
    Rule("S-PNPM", "instruction", "Always use pnpm for package installs",
         "use `pnpm add` / `pnpm install`, never npm or yarn", _pnpm, "shell"),
    Rule("S-CITE", "instruction", "Always cite a stele:// source when stating a stored fact",
         "include the stele:// reference inline", _word(r"stele://"), "prose"),
    Rule("S-TYPEHINT", "instruction", "Always put type hints on Python function signatures",
         "annotate every parameter and the return type", _typehint, "python"),
)

DISTRACTORS: tuple[Rule, ...] = tuple(
    Rule(f"SD-{dom[:2].upper()}{i}", "instruction", f"{dom} skill #{i}",
         f"apply {dom} habit #{i}", lambda _o: 0, dom)
    for dom in ("sql", "markdown", "yaml")
    for i in range(1, 4)
)
ALL_SKILLS = SKILLS + DISTRACTORS

_TASKS: tuple[WriteTask, ...] = (
    WriteTask("s-install", "Give the one shell command to add the 'zod' dependency to a JS project.",
              "shell", ("S-PNPM",)),
    WriteTask("s-fact", "State that prod runs in us-east-1, and back the claim with its source.",
              "prose", ("S-CITE",)),
    WriteTask("s-func", "Write a one-line Python function that adds two integers.",
              "python", ("S-TYPEHINT",)),
)


def _active(source: str) -> tuple[Rule, ...]:
    return SKILLS


def _populate_set(source: str) -> tuple[Rule, ...]:
    return ALL_SKILLS


class SkillAdherence:
    name = "skill_adherence"
    conditions: tuple[Condition, ...] = ("no_memory", "prompt_stuffed", "memory_driven")
    deterministic = True
    measured = (
        "Whether a stored 'always do X' skill, selected by domain and injected, "
        "raises a deterministic application rate vs no memory and vs stuffing the "
        "whole skillbook, at a fraction of the tokens."
    )
    not_measured = (
        "Skills whose application a regex cannot detect; whether the applied habit "
        "was actually the better choice for the task."
    )

    def corpus(self, source: str, n: int, seed: int) -> list[Case]:
        cases = [
            Case(case_id=f"{t.task_id}-{source}", question=t.prompt, gold="skill applied",
                 source=source, payload={"task_id": t.task_id, "domain": t.domain, "relevant": t.relevant})
            for t in _TASKS
        ]
        return cases[:n] if n else cases

    def populate(self, store: Stele, cases: list[Case]) -> None:
        if not cases:
            return
        ns = f"memmode-{self.name}-{cases[0].source}"
        populate_rules(store, ns, _populate_set(cases[0].source), agent_id="coder")

    def run_case(self, store: Stele, case: Case, condition: Condition, ctx: RunCtx) -> CaseResult:
        ns = f"memmode-{self.name}-{case.source}"
        domain = case.payload["domain"]
        if condition == "no_memory":
            guard, carried = "", 0
        elif condition == "prompt_stuffed":
            guard = "\n".join(f"- {r.summary}: {r.action}" for r in _populate_set(case.source))
            carried = len(_populate_set(case.source))
        else:
            pairs = select_by_domain(store, ns, domain, agent_id="coder")
            guard = "\n".join(f"- {s}: {a}" for s, a in pairs)
            carried = len(pairs)
        prompt = (
            "Do the task. Follow every habit listed under SKILLS.\n\n"
            f"SKILLS:\n{guard or '(none)'}\n\nTASK: {case.question}"
        )
        out = ctx.complete(prompt)
        by_id = {r.rule_id: r for r in _active(case.source)}
        applied = {rid: by_id[rid].detect(out) for rid in case.payload["relevant"] if rid in by_id}
        return CaseResult(
            output=out,
            metric={"applied": float(sum(1 for v in applied.values() if v > 0))},
            tokens_in=ctx.count_tokens(guard),
            tokens_out=ctx.count_tokens(out),
            deterministic=True,
            extra={"rules_carried": carried},
        )

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        rel = len(case.payload["relevant"])
        return {"application_rate": round(result.metric["applied"] / rel, 4) if rel else 0.0}
