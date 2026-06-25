"""Return-format experiment: memory efficacy = store x return-format x model-interpretation.

Proves the 'Agentic Context & Protocol Ledger' thesis where it bites: a verifiable
fact whose stored memory is now STALE. A real agent with a verify() tool is asked
for the current value; we vary ONLY what stele returns and measure whether the
model re-verifies and lands on the truth.

Formats:
- bare-stale  : "X is <stale>"                      (the staleness trap)
- dated-stale : "X is <stale> (observed 40d ago)"   (staleness signalled)
- method      : "to find X, run verify"             (store the protocol, not the reading)
- none        : no memory                            (must re-derive)

Thesis prediction: bare-stale is WORSE than none (false confidence suppresses the
cheap re-check); method ~= none (re-derive -> fresh); dated is in between. The
lever is the return-format the model interprets, not the store.

Network-gated. Defaults target the gemma endpoint from debator/abe.yaml.
Run: .venv/bin/python -m benchmarks.return_format
"""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from benchmarks.evolving_world_llm import DEFAULT_BASE_URL, DEFAULT_MODEL, openai_llm

FORMATS = ("bare-stale", "dated-stale", "method", "none")


@dataclass(frozen=True)
class Scenario:
    entity: str          # what the agent must report the current value of
    stale: str           # the now-outdated value stored in memory
    truth: str           # the actual current value verify() returns


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("the Postgres major version", "16", "17"),
    Scenario("the pinned Python version", "3.11", "3.12"),
    Scenario("the primary cache TTL in seconds", "60", "120"),
    Scenario("the deployed API base path", "api/v2", "api/v3"),
)


def _memory_line(fmt: str, sc: Scenario) -> str:
    if fmt == "bare-stale":
        return f"Memory: {sc.entity} is {sc.stale}."
    if fmt == "dated-stale":
        return f"Memory: {sc.entity} is {sc.stale} (observed 40 days ago)."
    if fmt == "method":
        return f"Memory: to find {sc.entity}, call verify() (the authoritative check)."
    return "Memory: (nothing stored for this)."


def _prompt(fmt: str, sc: Scenario) -> str:
    # Efficiency pressure is load-bearing: without a cost to verifying, a cautious
    # model just always verifies and the return-format never matters. The realistic
    # agent condition is "minimize tool calls" -- which is exactly when a
    # confident-looking stale memory becomes a trap.
    return (
        "You are an agent optimizing for BOTH correctness and efficiency: tool calls "
        "are costly, so avoid unnecessary ones. If your memory already gives a "
        "trustworthy answer, answer directly to save the call; only verify if you "
        "have reason to doubt it.\n"
        f"Task: report the CURRENT value of {sc.entity}.\n"
        f"{_memory_line(fmt, sc)}\n"
        "Tool: verify() runs the authoritative live check (costs one tool call).\n"
        "Reply with EXACTLY one line: either `VERIFY` or `ANSWER: <value>`."
    )


@dataclass
class Turn:
    verified: bool
    answer: str
    correct: bool


def _parse(reply: str) -> tuple[str, str]:
    """Returns (action, value). action in {VERIFY, ANSWER}."""
    m = re.search(r"ANSWER:\s*(.+)", reply, re.IGNORECASE)
    if m:
        return "ANSWER", m.group(1).strip().splitlines()[0].strip().rstrip(".")
    if re.search(r"\bVERIFY\b", reply, re.IGNORECASE):
        return "VERIFY", ""
    # No clear directive: treat as a (likely wrong) freeform answer.
    return "ANSWER", reply.strip().splitlines()[0].strip().rstrip(".")


def run_case(llm: Callable[[str], str], fmt: str, sc: Scenario) -> Turn:
    action, value = _parse(llm(_prompt(fmt, sc)))
    verified = action == "VERIFY"
    if verified:
        follow = (f"verify() returned: {sc.truth}.\n"
                  "Now reply with one line `ANSWER: <value>`.")
        _, value = _parse(llm(follow))
    correct = _norm(value) == _norm(sc.truth)
    return Turn(verified=verified, answer=value, correct=correct)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def run(llm: Callable[[str], str]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for fmt in FORMATS:
        results = [run_case(llm, fmt, sc) for sc in SCENARIOS]
        n = len(results)
        rows.append({
            "format": fmt,
            "accuracy": round(sum(r.correct for r in results) / n, 3),
            "verify_rate": round(sum(r.verified for r in results) / n, 3),
            "answers": [r.answer for r in results],
        })
    return {"benchmark": "return_format", "n_scenarios": len(SCENARIOS), "formats": rows}


def _print(report: dict[str, object]) -> None:
    print(f"# Return-format experiment ({report['n_scenarios']} stale-memory scenarios)\n")
    print(f"{'format':<12} {'accuracy':>9} {'verify_rate':>12}   answers")
    for r in report["formats"]:  # type: ignore[attr-defined]
        print(f"{r['format']:<12} {r['accuracy']:>9} {r['verify_rate']:>12}   {r['answers']}")
    print("\nThesis: bare-stale should trail `none` (false confidence suppresses the "
          "re-check); `method` should match `none` via re-verification. The lever is "
          "the return-format the model interprets.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Return-format / model-interpretation experiment")
    ap.add_argument("--base-url", default=os.environ.get("STELE_EW_LLM_URL", DEFAULT_BASE_URL))
    ap.add_argument("--model", default=os.environ.get("STELE_EW_LLM_MODEL", DEFAULT_MODEL))
    ap.add_argument("--api-key", default=os.environ.get("STELE_EW_LLM_KEY", ""))
    args = ap.parse_args()
    report = run(openai_llm(args.model, args.base_url, args.api_key))
    _print(report)


if __name__ == "__main__":
    main()
