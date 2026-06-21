"""Positive-proof experiment: process-memory (decisions/dead-ends) saves turns.

The argument FOR stele. Where return_format.py showed storing volatile readings is
a trap, this shows the high-value case: a prior session DECIDED or TRIED-AND-FAILED
something the environment cannot tell you. A real agent under efficiency pressure
faces a task that this history settles; we measure, with vs without the memory:

- rework_rate  : did it pick the already-REJECTED / already-FAILED option? (epistemic amnesia)
- investigate_rate : did it re-evaluate a settled question? (wasted turns)
- consistency_rate : did it land on the answer consistent with the prior decision?

Thesis: with-memory -> high consistency, ~0 rework, low investigate; no-memory ->
re-litigation and re-done dead-ends. This is non-re-derivable knowledge: the world
has no idea "we already rejected Kafka."

Network-gated. Defaults target the gemma endpoint from debator/abe.yaml.
Run: .venv/bin/python -m benchmarks.process_memory
"""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from benchmarks.evolving_world_llm import DEFAULT_BASE_URL, DEFAULT_MODEL, openai_llm

ARMS = ("with-memory", "no-memory")


@dataclass(frozen=True)
class Scenario:
    history: str        # the prior decision / dead-end (only the env cannot provide)
    question: str       # a task this history settles
    bad_kw: str         # the rejected/failed option that must NOT be chosen
    good_kw: str = ""   # the consistent choice that should appear (decisions)
    options: tuple[str, ...] = ()  # forced-choice menu (includes the rejected option)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "We evaluated message queues and DECIDED on Redis Streams, explicitly "
        "REJECTING Kafka (operational overhead for our scale).",
        "We need a message queue for the new feature. Which technology should we use?",
        bad_kw="kafka", good_kw="redis",
        options=("Redis Streams", "Kafka", "RabbitMQ")),
    Scenario(
        "We DECIDED to standardize testing on pytest and migrate away from unittest.",
        "Which test framework should the new module use?",
        bad_kw="unittest", good_kw="pytest",
        options=("pytest", "unittest", "nose2")),
    Scenario(
        "We chose Postgres as the primary datastore and REJECTED MongoDB "
        "(we need multi-row transactions).",
        "Which database should the new service store its data in?",
        bad_kw="mongo", good_kw="postgres",
        options=("Postgres", "MongoDB", "DynamoDB")),
    Scenario(
        "We TRIED a single global lock to fix the throughput contention and it "
        "FAILED: it deadlocked under load.",
        "How should we fix the throughput contention?",
        bad_kw="global lock",
        options=("a single global lock", "per-account locks", "a lock-free queue")),
)


def _prompt(arm: str, sc: Scenario) -> str:
    mem = (f"Relevant prior decision/outcome from earlier sessions: {sc.history}\n"
           if arm == "with-memory" else
           "No prior context from earlier sessions is available.\n")
    return (
        "You are an agent optimizing for correctness AND efficiency: re-evaluating "
        "a question that prior context has already settled wastes effort. If prior "
        "context settles this, decide directly.\n"
        f"{mem}"
        f"Task: {sc.question}\n"
        "Reply EXACTLY one line: `DECIDE: <short choice>` to commit now, or "
        "`INVESTIGATE` to re-evaluate the options first (costs effort)."
    )


@dataclass
class Outcome:
    investigated: bool
    choice: str
    rework: bool       # picked the rejected/failed option
    consistent: bool


def _parse(reply: str) -> tuple[str, str]:
    m = re.search(r"DECIDE:\s*(.+)", reply, re.IGNORECASE)
    if m:
        return "DECIDE", m.group(1).strip().splitlines()[0].strip()
    if re.search(r"\bINVESTIGATE\b", reply, re.IGNORECASE):
        return "INVESTIGATE", ""
    return "DECIDE", reply.strip().splitlines()[0].strip()


def _forced_prompt(arm: str, sc: Scenario) -> str:
    mem = (f"Relevant prior decision/outcome from earlier sessions: {sc.history}\n"
           if arm == "with-memory" else
           "No prior context from earlier sessions is available.\n")
    return (
        "You are an agent. Pick the best option for the task. You MUST choose "
        "exactly one from the menu (no clarifying questions).\n"
        f"{mem}"
        f"Task: {sc.question}\n"
        f"Options: {', '.join(sc.options)}.\n"
        "Reply EXACTLY one line: `DECIDE: <one option from the menu>`."
    )


def run_case(llm: Callable[[str], str], arm: str, sc: Scenario,
             forced: bool = False) -> Outcome:
    if forced:
        # Forced-choice exposes re-litigation directly: with the rejected option ON
        # the menu, a no-memory agent can re-pick what was already rejected.
        _, choice = _parse(llm(_forced_prompt(arm, sc)))
        investigated = False
    else:
        action, choice = _parse(llm(_prompt(arm, sc)))
        investigated = action == "INVESTIGATE"
        if investigated:
            _, choice = _parse(llm("After re-evaluating the options, reply EXACTLY "
                                   "one line `DECIDE: <short choice>`."))
    low = choice.lower()
    rework = sc.bad_kw.lower() in low
    consistent = (not rework) and (not sc.good_kw or sc.good_kw.lower() in low)
    return Outcome(investigated=investigated, choice=choice, rework=rework,
                   consistent=consistent)


def run(llm: Callable[[str], str], forced: bool = False) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for arm in ARMS:
        outs = [run_case(llm, arm, sc, forced=forced) for sc in SCENARIOS]
        n = len(outs)
        rows.append({
            "arm": arm,
            "consistency_rate": round(sum(o.consistent for o in outs) / n, 3),
            "rework_rate": round(sum(o.rework for o in outs) / n, 3),
            "investigate_rate": round(sum(o.investigated for o in outs) / n, 3),
            "choices": [o.choice for o in outs],
        })
    return {"benchmark": "process_memory", "mode": "forced-choice" if forced else "open",
            "n_scenarios": len(SCENARIOS), "arms": rows}


def _print(report: dict[str, object]) -> None:
    print(f"# Process-memory experiment [{report.get('mode', 'open')}] "
          f"({report['n_scenarios']} decision/dead-end scenarios)\n")
    print(f"{'arm':<13} {'consistency':>12} {'rework':>8} {'investigate':>12}   choices")
    for r in report["arms"]:  # type: ignore[attr-defined]
        print(f"{r['arm']:<13} {r['consistency_rate']:>12} {r['rework_rate']:>8} "
              f"{r['investigate_rate']:>12}   {r['choices']}")
    print("\nThesis: with-memory should beat no-memory on consistency and avoid rework "
          "(re-doing rejected/failed work) with fewer investigate turns. This is "
          "knowledge the environment cannot provide.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Process-memory positive-proof experiment")
    ap.add_argument("--base-url", default=os.environ.get("STELE_EW_LLM_URL", DEFAULT_BASE_URL))
    ap.add_argument("--model", default=os.environ.get("STELE_EW_LLM_MODEL", DEFAULT_MODEL))
    ap.add_argument("--api-key", default=os.environ.get("STELE_EW_LLM_KEY", ""))
    args = ap.parse_args()
    llm = openai_llm(args.model, args.base_url, args.api_key)
    for forced in (False, True):
        _print(run(llm, forced=forced))
        print()


if __name__ == "__main__":
    main()
