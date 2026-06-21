"""Evolving-world agent simulation benchmark (Phase 1: headline 3-arm scale run).

Simulates a long-running agent over many sessions while the world changes
underneath it (value changes, deprecations the agent did not cause). Holds the
agent policy CONSTANT across arms and varies only the memory subsystem, so any
delta is attributable to memory, not to a smarter agent.

Arms (this slice): no-memory | naive-append | stele-full.
Oracle (this slice): value-recall, scored against `knowable_truth` (the latest
value whose evidence appeared on or before the query day) so we never fault the
agent for a change nothing has revealed yet.

Design: docs/specs/evolving-world-simulation-benchmark-design.md
Deferred to later slices: stele-no-registry / stele-no-supersession attribution
arms, the stale-injection control, the action-outcome oracle, the real-LLM lane,
and the (gated) bento confirmation pass.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from benchmarks._versions import version_info, versions_md_line
from stele import Stele
from stele.core.artifact import estimate_tokens
from stele.core.config import StashConfig
from stele.core.memory_record import MemoryQuery, MemoryScope

Arm = Literal["no-memory", "naive-append", "stele-full"]
ARMS: tuple[Arm, ...] = ("no-memory", "naive-append", "stele-full")

# How many extra "turns" a forced re-exploration costs (re-running the tool /
# re-opening the source because memory could not answer). One verification round.
REEXPLORE_TURNS = 1


@dataclass(frozen=True)
class Entity:
    """A real-world entity whose fact evolves on a timeline the agent cannot see."""

    name: str
    aspect: str
    # (day, value) changes in ascending day order; first entry is the initial value.
    changes: tuple[tuple[int, str], ...]
    deprecate_day: int | None = None  # after this day the correct answer is RETIRED

    def truth_at(self, day: int) -> str:
        """Absolute world truth as of `day` (ignores what the agent could know)."""
        if self.deprecate_day is not None and day >= self.deprecate_day:
            return "RETIRED"
        value = self.changes[0][1]
        for change_day, change_value in self.changes:
            if change_day <= day:
                value = change_value
        return value


# Surface-label variants that all normalize to the SAME registry key (case +
# punctuation only), so cross-session supersession fires on label noise. Semantic
# variance ("postgres" vs "production") needs aliases/extra_subjects and is the
# attribution-suite scenario, deferred to a later slice.
def _variant(base: str, i: int) -> str:
    forms = [base, base.capitalize(), base.upper(), f"{base}."]
    return forms[i % len(forms)]


@dataclass
class SessionStep:
    day: int
    entity: int
    role: Literal["evidence", "stale", "query"]  # what this session reveals
    label: str
    value: str  # the value this session asserts (for evidence/stale); "" for query


def default_entities() -> list[Entity]:
    """A small, deterministic evolving world. Each entity changes value at least
    once; some get deprecated; one keeps a value stable as a control."""
    return [
        Entity("postgres", "version", ((0, "14"), (10, "16"), (30, "18"))),
        Entity("python", "pinned", ((0, "3.11"), (15, "3.12"))),
        Entity("endpoint", "url", ((0, "api/v1"), (8, "api/v2"), (24, "api/v3"))),
        Entity("redis", "version", ((0, "6"), (20, "7"))),
        Entity("legacytool", "status", ((0, "active"),), deprecate_day=18),
        Entity("region", "value", ((0, "us-east"),)),  # stable control
    ]


def build_plan(entities: list[Entity], n_sessions: int) -> list[SessionStep]:
    """Deterministic session stream. Each entity's value changes are revealed on
    their change day; in between, query sessions force the agent to answer from
    memory. After a value changes we sometimes resurface the OLD value as a
    'stale' session (an outdated doc/tool the agent did not control re-appearing)
    to test whether the memory layer trusts effective-order over write-order."""
    steps: list[SessionStep] = []
    day = 0
    i = 0
    while len(steps) < n_sessions:
        ent_idx = i % len(entities)
        ent = entities[ent_idx]
        # Reveal the value that is current as of this day.
        cur = ent.truth_at(day)
        # Is a change effective exactly today? then this is an evidence session.
        change_today = any(d == day for d, _ in ent.changes) or ent.deprecate_day == day
        if change_today:
            role: Literal["evidence", "stale", "query"] = "evidence"
            value = cur
        elif i % 7 == 5 and day > 0:
            # Periodically resurface an OLD value out-of-order (the adversarial trap).
            old = ent.changes[0][1]
            role, value = ("stale", old) if old != cur else ("query", "")
        elif i % 3 == 0:
            role, value = "evidence", cur  # fresh confirmation of current truth
        else:
            role, value = "query", ""
        steps.append(SessionStep(day=day, entity=ent_idx, role=role,
                                 label=_variant(ent.name, i), value=value))
        i += 1
        if i % len(entities) == 0:
            day += 1  # advance virtual time once per full round-robin
    return steps


def _artifact(step: SessionStep, ent: Entity) -> str:
    """A small noisy artifact embedding the asserted fact (the only thing the
    agent observes)."""
    if step.role == "query":
        return (f"[ci day {step.day}] checking status of {step.label}; "
                f"no new {ent.aspect} information in this run.\n"
                f"... build logs ... 0 errors ... cache hit ...")
    verb = "DEPRECATED" if step.value == "RETIRED" else f"{ent.aspect} = {step.value}"
    tag = "stale-doc" if step.role == "stale" else "release-note"
    return (f"[{tag} day {step.day}] {step.label} {verb}\n"
            f"... changelog ... reviewed-by: bot ... checksum ok ...\n"
            f"context: {step.label} pipeline run for {ent.name}")


@dataclass
class ArmMetrics:
    arm: str
    sessions: int = 0
    correct: int = 0
    stale_actions: int = 0
    staleness_lag: int = 0  # sessions behind a KNOWABLE change
    turns: int = 0
    tokens: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        n = self.sessions or 1
        denom = self.tokens + self.turns
        return {
            "arm": self.arm,
            "sessions": self.sessions,
            "accuracy": round(self.correct / n, 4),
            "stale_action_rate": round(self.stale_actions / n, 4),
            "staleness_lag": self.staleness_lag,
            "turns": self.turns,
            "tokens": self.tokens,
            "latency_p50_ms": round(_pct(self.latencies_ms, 0.50), 3),
            "latency_p95_ms": round(_pct(self.latencies_ms, 0.95), 3),
            # efficiency = successes / (tokens + turns)
            "efficiency": round(self.correct / denom, 6) if denom else 0.0,
        }


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


def _value_from_text(text: str) -> str:
    if " = " in text:  # naive-append metadata path may store "aspect = value"
        return text.rsplit(" = ", 1)[-1].strip().rstrip(".")
    return text.rsplit(" is ", 1)[-1].strip().rstrip(".")


def _fact_text(ent: Entity, label: str, value: str) -> str:
    return f"{label} {ent.aspect} is {value}"


def _const_llm(payload: str) -> Callable[[str], str]:
    """A deterministic stand-in for the extraction LLM: returns a fixed memory
    JSON regardless of the prompt, so from_session exercises the REAL registry +
    supersession path without a live model."""
    def _llm(_prompt: str) -> str:
        return payload
    return _llm


def run_arm(arm: Arm, steps: list[SessionStep], entities: list[Entity],
            backend: dict[str, object]) -> ArmMetrics:
    cfg = StashConfig.model_validate({"backend": backend, "extraction": {"enabled": True}})
    stele = Stele(cfg)
    ns = f"ew_{arm.replace('-', '_')}"
    m = ArmMetrics(arm=arm)

    # knowable_truth bookkeeping: the latest value whose evidence has appeared so far.
    knowable: dict[int, str] = {}
    last_evidence_text: dict[int, str] = {}

    for sidx, step in enumerate(steps):
        ent = entities[step.entity]
        scope = MemoryScope(namespace=ns, session_id=f"s{sidx}")
        art = _artifact(step, ent)

        # Update the agent-knowable truth as evidence arrives (fresh current value
        # only; a 'stale' resurfacing of an old value does NOT change what is
        # knowably-current, it only tries to mislead write-order memory).
        if step.role == "evidence":
            knowable[step.entity] = step.value
            last_evidence_text[step.entity] = art

        t0 = time.perf_counter()
        # --- Ingest (arm-specific) ---
        if arm == "no-memory":
            pass
        elif arm == "naive-append":
            if step.role in ("evidence", "stale"):
                ref = str(stele.store(art, namespace=ns).reference)
                stele.memory.add(
                    text=_fact_text(ent, step.label, step.value), kind="fact",
                    source_refs=[ref], scope=scope,
                    metadata={"widx": sidx, "value": step.value},
                )
        else:  # stele-full: real registry + cross-session supersession via from_session
            if step.role in ("evidence", "stale"):
                fact = _fact_text(ent, step.label, step.value)
                payload = json.dumps([{
                    "kind": "fact", "summary": fact,
                    "subject_label": step.label, "aspect": ent.aspect,
                    "subject_type": "entity",
                }])
                stele.extract.from_session(
                    transcript=[{"role": "user", "content": art}],
                    scope=scope, llm=_const_llm(payload), max_windows=1,
                )

        # --- Recall + decide (FIXED policy across arms; trust recall's latest) ---
        answer, recall_tokens, extra_turns = _decide(
            arm, stele, ns, step, ent, last_evidence_text.get(step.entity, art)
        )
        m.latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        # --- Score against knowable truth ---
        known = knowable.get(step.entity)
        if known is not None:
            if answer == known:
                m.correct += 1
            else:
                # A change was knowable but the agent answered something else.
                if answer in {v for _, v in ent.changes} or answer == "RETIRED":
                    m.stale_actions += 1
                m.staleness_lag += 1
        else:
            # Nothing knowable yet (no evidence seen); answering anything but the
            # current artifact is unfair to score, so only count explicit correct.
            if answer == ent.truth_at(step.day):
                m.correct += 1
        m.sessions += 1
        m.turns += 1 + extra_turns
        m.tokens += recall_tokens

    return m


def _decide(arm: Arm, stele: Stele, ns: str, step: SessionStep, ent: Entity,
            reexplore_src: str) -> tuple[str, int, int]:
    """Returns (answer, recall_tokens, extra_turns). Fixed across arms; only the
    candidate set differs."""
    art = _artifact(step, ent)
    if arm == "no-memory":
        # Can only answer from THIS session's artifact. Evidence/stale sessions
        # carry a value; query sessions force a re-exploration (re-run the tool).
        if step.role in ("evidence", "stale"):
            return step.value, estimate_tokens(art), 0
        # Re-explore: re-read the latest evidence source for this entity.
        return _reexplore_value(ent, reexplore_src), estimate_tokens(reexplore_src), REEXPLORE_TURNS

    # memory-backed arms share one search call; only what is stored differs.
    hits = stele.memory.search(MemoryQuery(query=ent.name, scope=MemoryScope(namespace=ns),
                                           limit=25))
    payload = "\n".join(h.text for h in hits)
    tokens = estimate_tokens(payload) if payload else estimate_tokens(art)
    if not hits:
        # No memory yet: fall back to the current artifact (or re-explore).
        if step.role in ("evidence", "stale"):
            return step.value, tokens, 0
        return _reexplore_value(ent, reexplore_src), estimate_tokens(reexplore_src), REEXPLORE_TURNS
    # Trust the latest-written hit (recency tiebreak). For stele-full only the
    # active chain head survives, so "latest" == current truth. For naive-append
    # every value is still active, so a late stale re-mention can win and mislead.
    latest = max(hits, key=lambda h: (h.metadata.get("widx", 0), h.created_at))
    return _value_from_text(latest.text), tokens, 0


def _reexplore_value(ent: Entity, src: str) -> str:
    """A re-exploration re-reads the source and returns its asserted value."""
    head = src.split("\n", 1)[0]
    if "DEPRECATED" in head:
        return "RETIRED"
    return _value_from_text(head)


def run(n_sessions: int, backend: dict[str, object]) -> dict[str, object]:
    entities = default_entities()
    steps = build_plan(entities, n_sessions)
    results = [run_arm(arm, steps, entities, backend).summary() for arm in ARMS]
    return {
        "benchmark": "evolving_world",
        "sessions": len(steps),
        "backend": backend.get("type"),
        "arms": results,
        "versions": version_info(),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _markdown(report: dict[str, object]) -> str:
    arms = cast(list[dict[str, object]], report["arms"])
    cols = ["arm", "accuracy", "stale_action_rate", "staleness_lag", "turns",
            "tokens", "latency_p50_ms", "latency_p95_ms", "efficiency"]
    lines = [
        "# Evolving-World Agent Simulation (Phase 1: headline 3-arm)",
        "",
        f"Sessions: {report['sessions']} · Backend: {report['backend']} · "
        f"{report['generated_at']}",
        versions_md_line(),
        "",
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for a in arms:
        lines.append("| " + " | ".join(str(a[c]) for c in cols) + " |")
    lines += [
        "",
        "Lower is better: stale_action_rate, staleness_lag, turns, tokens, latency. "
        "Higher is better: accuracy, efficiency.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=300)
    ap.add_argument("--backend", choices=["postgres", "sqlite"], default="postgres")
    ap.add_argument("--dsn", default=None, help="postgres DSN (or env STELE_PG_DSN)")
    ap.add_argument("--sqlite-path", default="/tmp/stele_evolving_world.db")
    ap.add_argument("--out", default=None, help="output dir (default benchmarks/runs/<date>)")
    args = ap.parse_args()

    if args.backend == "postgres":
        import os
        dsn = args.dsn or os.environ.get("STELE_PG_DSN")
        if not dsn:
            raise SystemExit("postgres backend needs --dsn or STELE_PG_DSN")
        backend: dict[str, object] = {"type": "postgres", "dsn": dsn}
    else:
        backend = {"type": "sqlite", "path": args.sqlite_path}

    report = run(args.sessions, backend)
    default_dir = Path("benchmarks/runs") / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir = Path(args.out) if args.out else default_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "EvolvingWorld.json").write_text(json.dumps(report, indent=2))
    (out_dir / "EvolvingWorld.md").write_text(_markdown(report))
    print(_markdown(report))
    print(f"wrote {out_dir}/EvolvingWorld.{{md,json}}")


if __name__ == "__main__":
    main()
