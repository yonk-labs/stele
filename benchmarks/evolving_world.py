"""Evolving-world agent simulation benchmark.

EXPERIMENTAL / parked: this measures cross-session currency of atomic re-derivable
facts, which the memory-value thesis found to be the low-value corner (storing the
volatile value is a trap; see docs/benchmarks/findings/memory-value-thesis-2026-06-21.md
and return_format.py). Isolated behind ExtractionConfig.experimental_evolving_facts;
the high-value direction is durable process memory (decisions/dead-ends/procedure). Kept
for the #69/#72 record and for whenever the atomic-fact machinery is reworked.

Simulates a long-running agent over many sessions while the world changes
underneath it (value changes, deprecations the agent did not cause). Holds the
agent policy CONSTANT across arms and varies only the memory subsystem, so any
delta is attributable to memory, not to a smarter agent.

Arms (this slice): no-memory | naive-append | stele-full (+ optional stele-role via
--fix, and stele-ledger via --ledger: the memory-value thesis arm that stores the
verification METHOD, not the value, and re-derives on read).

Two oracles:
- Agent-side (value-recall): does the agent's answer match `knowable_truth` (the
  latest value whose evidence appeared on or before the query day)?
- Store-side (#72): after the run, is a SUPERSEDED value still ACTIVE in the
  store (cross-session staleness), and did two genuinely-distinct entities get
  wrongly merged (over-merge / corruption)? These are the #72 gates.

Scenario classes (issue #72):
- `stable`  — subject label persists across sessions; the registry resolves it
  and supersession fires. The class the registry already passes.
- `value`   — "entity-named-by-its-value": the LLM labels the subject AFTER the
  value it carries (Postgres -> MySQL), so each session mints a different
  subject_id and the slot never collides. The dominant real-world failure.
- `coexist` — two distinct entities sharing an aspect that must NOT merge
  (staging-db vs production-db). The over-merge guard: must stay 0%.

Design: docs/specs/evolving-world-simulation-benchmark-design.md
Deferred to later slices: the action-outcome oracle, the real-LLM lane, and the
(gated) bento confirmation pass.
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
from stele.extraction.identity import canonical_subject

Arm = Literal["no-memory", "naive-append", "stele-full", "stele-role", "stele-ledger",
              "stele-ledger-ttl"]
ARMS: tuple[Arm, ...] = ("no-memory", "naive-append", "stele-full")
LabelMode = Literal["stable", "value"]

# A forced re-exploration (re-running the tool because memory could not answer)
# costs one extra turn.
REEXPLORE_TURNS = 1


@dataclass(frozen=True)
class Entity:
    """A real-world entity whose fact evolves on a timeline the agent cannot see.

    `label_mode` decides how the subject is named in each session: `stable` keeps
    one label across the value change (registry resolves it), `value` names the
    subject after its current value (the #72 failure: each value mints a new id).
    `coexist_group` marks entities that must stay distinct (the over-merge guard).
    """

    name: str  # stable role id; the recall query term and the scenario key
    aspect: str
    changes: tuple[tuple[int, str], ...]  # (day, value), ascending; [0] is initial
    label_mode: LabelMode = "stable"
    deprecate_day: int | None = None
    coexist_group: str | None = None
    silent: bool = False  # value changes are NOT announced (no evidence step); only
    #                       re-derivation catches them - the real staleness-trap domain

    @property
    def scenario(self) -> str:
        if self.coexist_group is not None:
            return "coexist"
        if self.silent:
            return "silent"
        return self.label_mode  # "stable" | "value"

    def truth_at(self, day: int) -> str:
        if self.deprecate_day is not None and day >= self.deprecate_day:
            return "RETIRED"
        value = self.changes[0][1]
        for change_day, change_value in self.changes:
            if change_day <= day:
                value = change_value
        return value


def _variant(base: str, i: int) -> str:
    """Case/punctuation variants that all normalize to ONE registry key, so a
    stable subject resolves across sessions despite label noise."""
    forms = [base, base.capitalize(), base.upper(), f"{base}."]
    return forms[i % len(forms)]


def default_entities(include_silent: bool = False) -> list[Entity]:
    entities = [
        # stable-subject evolving facts (registry should keep these clean)
        Entity("deployregion", "value", ((0, "useast"), (15, "uswest"))),
        Entity("pyversion", "pinned", ((0, "3.11"), (15, "3.12"))),
        Entity("cachettl", "seconds", ((0, "60"), (20, "120"))),
        # entity-named-by-its-value (the #72 dominant failure)
        Entity("dbengine", "primary", ((0, "Postgres"), (20, "MySQL")), label_mode="value"),
        Entity("cisystem", "primary", ((0, "Jenkins"), (20, "GitHubActions")), label_mode="value"),
        Entity("jobqueue", "primary", ((0, "RabbitMQ"), (20, "Kafka")), label_mode="value"),
        # deprecation (an external retirement the agent did not cause)
        Entity("legacytool", "status", ((0, "active"),), deprecate_day=18),
        # over-merge guard: distinct entities sharing an aspect, must coexist
        Entity("stagingdb", "version", ((0, "14"),), coexist_group="dbs"),
        Entity("productiondb", "version", ((0, "16"),), coexist_group="dbs"),
        Entity("authsvc", "port", ((0, "9001"),), coexist_group="svcs"),
        Entity("billingsvc", "port", ((0, "9002"),), coexist_group="svcs"),
    ]
    if include_silent:
        # Silent changes: the value flips with NO evidence event, so a value-caching
        # memory can never learn it and only re-derivation catches it. This is the
        # case the verification-method (and a freshness-bounded reuse) exists for.
        entities += [
            Entity("featureflag", "state", ((0, "off"), (22, "on")), silent=True),
            Entity("tlscert", "fingerprint", ((0, "aa11"), (22, "bb22")), silent=True),
        ]
    return entities


@dataclass
class SessionStep:
    day: int
    entity: int
    role: Literal["evidence", "stale", "query"]
    value: str  # asserted value for evidence/stale; "" for query
    i: int  # round-robin index, for label variant rotation


def build_plan(entities: list[Entity], n_sessions: int) -> list[SessionStep]:
    """Deterministic session stream. Coexisting entities are asserted once (they
    do not evolve). Evolving entities reveal each change on its day; between
    changes, query sessions force the agent to answer from memory, and we
    periodically resurface an OLD value out-of-order (a stale doc the agent did
    not control) to test write-order vs effective-order memory."""
    steps: list[SessionStep] = []
    day = 0
    i = 0
    while len(steps) < n_sessions:
        ent_idx = i % len(entities)
        ent = entities[ent_idx]
        cur = ent.truth_at(day)
        role: Literal["evidence", "stale", "query"]
        if ent.scenario == "coexist":
            role, value = "evidence", cur  # assert the distinct fact, no evolution
        elif ent.silent and day > 0:
            # Silent entity past day 0: the world may change but the agent is never
            # told (no evidence, ever). Only re-derivation can recover the truth.
            role, value = "query", ""
        else:
            change_today = any(d == day for d, _ in ent.changes) or ent.deprecate_day == day
            if change_today:
                role, value = "evidence", cur
            elif i % 7 == 5 and day > 0 and ent.changes[0][1] != cur:
                role, value = "stale", ent.changes[0][1]  # old value resurfaces
            elif i % 3 == 0:
                role, value = "evidence", cur
            else:
                role, value = "query", ""
        steps.append(SessionStep(day=day, entity=ent_idx, role=role, value=value, i=i))
        i += 1
        if i % len(entities) == 0:
            day += 1
    return steps


def _fact(ent: Entity, step: SessionStep, value: str) -> tuple[str, str, str]:
    """Returns (fact_text, subject_label, aspect). For `value` mode the subject
    is named by its value (so the registry mints a new id per value); for
    `stable`/`coexist` the subject label persists. Text always ends with the
    value, so one parser recovers it for every arm."""
    if ent.label_mode == "value":
        return f"the {ent.name} is {value}", value, ent.name
    label = _variant(ent.name, step.i)
    return f"{label} {ent.aspect} is {value}", label, ent.aspect


def _artifact(ent: Entity, step: SessionStep) -> str:
    if step.role == "query":
        return (f"[ci day {step.day}] checking {ent.name}; no new {ent.aspect} "
                f"info this run.\n... build logs ... 0 errors ... cache hit ...")
    fact_text, _, _ = _fact(ent, step, step.value)
    verb = "DEPRECATED" if step.value == "RETIRED" else fact_text
    tag = "stale-doc" if step.role == "stale" else "release-note"
    return (f"[{tag} day {step.day}] {verb}\n"
            f"... changelog ... reviewed-by: bot ... checksum ok ...\n"
            f"context: {ent.name} pipeline run")


def _const_llm(payload: str) -> Callable[[str], str]:
    """Deterministic stand-in for the extraction LLM: returns a fixed memory JSON
    regardless of prompt, so from_session exercises the REAL registry +
    supersession path without a live model."""
    def _llm(_prompt: str) -> str:
        return payload
    return _llm


def _value_from_text(text: str) -> str:
    return text.rsplit(" is ", 1)[-1].strip().rstrip(".")


def _rederive(ent: Entity, step: SessionStep) -> str:
    """Re-running the verification (consulting live reality) always yields the
    current truth, including changes the agent never witnessed (silent). This is
    what makes a stored verification_method strictly stronger than a cached value."""
    return ent.truth_at(step.day)


@dataclass
class ArmMetrics:
    arm: str
    sessions: int = 0
    correct: int = 0
    stale_actions: int = 0
    staleness_lag: int = 0
    turns: int = 0
    tokens: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    # store-side (#72), filled by probe_store:
    active_staleness_rate: float = 0.0
    stale_by_class: dict[str, float] = field(default_factory=dict)
    over_merge_rate: float = 0.0

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
            "active_staleness_rate": round(self.active_staleness_rate, 4),
            "stale_by_class": {k: round(v, 4) for k, v in self.stale_by_class.items()},
            "over_merge_rate": round(self.over_merge_rate, 4),
        }


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


def _ingest(arm: Arm, stele: Stele, ns: str, scope: MemoryScope, ent: Entity,
            step: SessionStep, real_llm: Callable[[str], str] | None = None) -> None:
    if arm == "no-memory" or step.role == "query":
        return
    art = _artifact(ent, step)
    if arm in ("stele-ledger", "stele-ledger-ttl"):
        # Thesis arm: store HOW to re-derive (a value-free verification_method),
        # never the volatile value. Recorded only from the authoritative evidence
        # source; a resurfaced stale doc adds no method and no value to go stale.
        # The staleness-trap fix (return_format.py) inside the multi-session sim.
        if step.role != "evidence":
            return
        ref = str(stele.store(art, namespace=ns).reference)
        method = (f"to verify {ent.name}: re-check the {ent.aspect} in the latest "
                  f"{ent.name} release-note (do not trust a cached value)")
        stele.memory.add(text=method, kind="verification_method", source_refs=[ref],
                         scope=scope, metadata={"widx": step.i, "subject": ent.name,
                                                "method": "re-check source"})
        if arm == "stele-ledger-ttl":
            # Also record the WITNESSED value as a process-bound observation, so the
            # agent can reuse it within the freshness window before re-deriving.
            stele.memory.add(text=f"observed {ent.name} = {step.value}", kind="observation",
                             source_refs=[ref], scope=scope,
                             metadata={"widx": step.i, "subject": ent.name,
                                       "value": step.value, "day": step.day})
        return
    fact_text, subj_label, aspect = _fact(ent, step, step.value)
    if arm == "naive-append":
        ref = str(stele.store(art, namespace=ns).reference)
        stele.memory.add(text=fact_text, kind="fact", source_refs=[ref], scope=scope,
                         metadata={"widx": step.i, "value": step.value})
    else:  # stele-full: real registry + cross-session supersession
        # Deterministic stub forces the worst-case label per scenario class; the
        # real-LLM lane (real_llm) instead reads the noisy artifact and extracts
        # with genuine label/aspect drift (catches the extraction-instability
        # staleness class the deterministic core cannot see).
        payload = json.dumps([{
            "kind": "fact", "summary": fact_text, "subject_label": subj_label,
            "aspect": aspect, "subject_type": "entity",
        }])
        stele.extract.from_session(
            transcript=[{"role": "user", "content": art}], scope=scope,
            llm=real_llm or _const_llm(payload), max_windows=1,
        )


def _decide(arm: Arm, stele: Stele, ns: str, ent: Entity, step: SessionStep,
            reexplore_src: str, scope: MemoryScope,
            ttl: int | None = None) -> tuple[str, int, int]:
    """Returns (answer, recall_tokens, extra_turns). Policy is FIXED across the
    value-storing arms (trust the latest-written hit); only the candidate set
    differs. stele-ledger is the deliberate exception: it stores no value, so it
    re-derives from the canonical source instead of trusting a stored hit."""
    art = _artifact(ent, step)
    if arm == "no-memory":
        if step.role in ("evidence", "stale"):
            return step.value, estimate_tokens(art), 0
        # Re-explore the live source (no memory to consult): always current truth,
        # including silent changes. Charged the full re-exploration cost.
        return _rederive(ent, step), estimate_tokens(reexplore_src), REEXPLORE_TURNS

    if arm == "stele-ledger":
        # Fresh evidence in hand needs no re-derivation.
        if step.role == "evidence":
            return step.value, estimate_tokens(art), 0
        # Recall the method (cheap), then re-derive the CURRENT value from the
        # canonical source head: targeted (cheaper than a blind re-explore) and it
        # ignores any resurfaced stale doc. Always current -> 0 staleness, paid for
        # in one re-derivation turn (more turns than no-memory, which trusts the
        # stale doc for free).
        hits = stele.memory.search(MemoryQuery(query=ent.name,
                                               scope=MemoryScope(namespace=ns), limit=25))
        # The agent reads ONE method (they are the same value-free instruction),
        # not the whole append-only pile - it never accumulates values to sift.
        method_tokens = estimate_tokens(hits[0].text) if hits else 0
        head = reexplore_src.split("\n", 1)[0]
        return _rederive(ent, step), method_tokens + estimate_tokens(head), REEXPLORE_TURNS

    if arm == "stele-ledger-ttl":
        # Freshness-bounded reuse: trust a witnessed observation for `ttl` days,
        # then fall back to re-running the method (live truth) and re-cache. ttl=None
        # means trust forever (pure cache; goes permanently stale on silent changes).
        if step.role == "evidence":
            return step.value, estimate_tokens(art), 0
        # Recall is cross-session: the observation/method were written in earlier
        # sessions, so search namespace-wide (the per-step session scope sees nothing).
        hits = stele.memory.search(MemoryQuery(query=ent.name,
                                               scope=MemoryScope(namespace=ns), limit=50))
        observations = [h for h in hits if h.metadata.get("value") is not None]
        freshest = (max(observations, key=lambda h: int(str(h.metadata.get("day", 0))))
                    if observations else None)
        if freshest is not None:
            age = step.day - int(str(freshest.metadata.get("day", 0)))
            if ttl is None or age <= ttl:
                # Within the freshness window: trust the cached observation, no re-derive.
                return str(freshest.metadata.get("value", "")), estimate_tokens(freshest.text), 0
        # Stale window (or never observed): re-run the method (live truth) and refresh
        # the observation so the window resets - the honest re-derivation cost is paid.
        method_hit = next((h for h in hits if h.metadata.get("method") is not None), None)
        method_tokens = estimate_tokens(method_hit.text) if method_hit else 0
        head = reexplore_src.split("\n", 1)[0]
        truth = _rederive(ent, step)
        refs = list(method_hit.source_refs) if method_hit else []
        if refs:
            stele.memory.add(text=f"observed {ent.name} = {truth}", kind="observation",
                             source_refs=refs, scope=scope,
                             metadata={"subject": ent.name, "value": truth, "day": step.day})
        return truth, method_tokens + estimate_tokens(head), REEXPLORE_TURNS

    hits = stele.memory.search(MemoryQuery(query=ent.name, scope=MemoryScope(namespace=ns),
                                           limit=25))
    payload = "\n".join(h.text for h in hits)
    tokens = estimate_tokens(payload) if payload else estimate_tokens(art)
    if not hits:
        if step.role in ("evidence", "stale"):
            return step.value, tokens, 0
        head = reexplore_src.split("\n", 1)[0]
        val = "RETIRED" if "DEPRECATED" in head else _value_from_text(head)
        return val, estimate_tokens(reexplore_src), REEXPLORE_TURNS
    latest = max(hits, key=lambda h: (h.metadata.get("widx", 0), h.created_at))
    return _value_from_text(latest.text), tokens, 0


def probe_store(arm: Arm, stele: Stele, ns: str, entities: list[Entity],
                last_day: int) -> tuple[float, dict[str, float], float]:
    """Store-side #72 gates: cross-session active-staleness (a superseded value
    still active) and over-merge (a coexisting entity wrongly dropped). Computed
    by querying the arm's live store, independent of the agent's policy."""
    if arm == "no-memory":
        return 0.0, {}, 0.0

    if arm == "stele-ledger":
        # Methods carry no asserted value, so by the metric's own definition (a
        # superseded value still active) staleness is 0 by construction: the cost
        # is re-derivation (visible in turns/tokens), not staleness. The integrity
        # check that remains is over-merge: every coexisting entity must keep a
        # retrievable verification_method (methods keyed by name never collapse a
        # value-named slot).
        led_scope = MemoryScope(namespace=ns)

        def has_method(name: str) -> bool:
            hits = stele.memory.search(MemoryQuery(query=name, scope=led_scope, limit=50))
            return any(name.lower() in h.text.lower() for h in hits)

        groups_l: dict[str, list[Entity]] = {}
        for e in entities:
            if e.coexist_group is not None:
                groups_l.setdefault(e.coexist_group, []).append(e)
        dropped_l = total_l = 0
        for members in groups_l.values():
            for member in members:
                total_l += 1
                if not has_method(member.name):
                    dropped_l += 1
        over_merge_l = dropped_l / total_l if total_l else 0.0
        # Method-only re-derives every read, so it is 0-stale on every class,
        # including silent (unannounced) changes.
        return 0.0, {"stable": 0.0, "value": 0.0, "silent": 0.0}, over_merge_l

    if arm == "stele-ledger-ttl":
        # This arm DOES store observation values, so staleness is measured HONESTLY,
        # not 0 by construction: the agent's effective belief is the most-recent
        # observation, and it is stale if that differs from truth. A silent change
        # the freshness window has not yet forced a re-derive on shows up here.
        ttl_scope = MemoryScope(namespace=ns)

        def latest_obs(name: str) -> str | None:
            hits = stele.memory.search(MemoryQuery(query=name, scope=ttl_scope, limit=50))
            obs = [h for h in hits if h.metadata.get("value") is not None
                   and name.lower() in h.text.lower()]
            if not obs:
                return None
            freshest = max(obs, key=lambda h: int(str(h.metadata.get("day", 0))))
            return str(freshest.metadata.get("value", ""))

        evolving_t = [e for e in entities if e.scenario in ("stable", "value", "silent")]
        by_class_t: dict[str, list[int]] = {"stable": [], "value": [], "silent": []}
        for ent in evolving_t:
            belief = latest_obs(ent.name)
            stale = 1 if (belief is not None and belief != ent.truth_at(last_day)) else 0
            by_class_t[ent.scenario].append(stale)
        flat_t = [x for xs in by_class_t.values() for x in xs]
        active_t = sum(flat_t) / len(flat_t) if flat_t else 0.0
        sbc_t = {k: (sum(v) / len(v) if v else 0.0) for k, v in by_class_t.items()}
        groups_t: dict[str, list[Entity]] = {}
        for e in entities:
            if e.coexist_group is not None:
                groups_t.setdefault(e.coexist_group, []).append(e)
        dropped_t = total_t = 0
        for members in groups_t.values():
            for member in members:
                total_t += 1
                if latest_obs(member.name) is None:
                    dropped_t += 1
        over_t = dropped_t / total_t if total_t else 0.0
        return active_t, sbc_t, over_t

    scope = MemoryScope(namespace=ns)

    def active_values(query: str) -> set[str]:
        hits = stele.memory.search(MemoryQuery(query=query, scope=scope, limit=50))
        return {_value_from_text(h.text) for h in hits if query.lower() in h.text.lower()}

    evolving = [e for e in entities if e.scenario in ("stable", "value", "silent")]
    by_class: dict[str, list[int]] = {"stable": [], "value": [], "silent": []}
    for ent in evolving:
        vals = active_values(ent.name)
        current = ent.truth_at(last_day)
        # stale = a non-current value of THIS entity still active alongside it
        lingering = {v for v in vals if v and v != current and v in {x for _, x in ent.changes}}
        by_class[ent.scenario].append(1 if lingering else 0)
    flat = [x for xs in by_class.values() for x in xs]
    active_stale = sum(flat) / len(flat) if flat else 0.0
    stale_by_class = {k: (sum(v) / len(v) if v else 0.0) for k, v in by_class.items()}

    # over-merge: every member of a coexist group must remain retrievable.
    groups: dict[str, list[Entity]] = {}
    for e in entities:
        if e.coexist_group is not None:
            groups.setdefault(e.coexist_group, []).append(e)
    dropped = total = 0
    for members in groups.values():
        for m in members:
            total += 1
            if m.truth_at(last_day) not in active_values(m.name):
                dropped += 1
    over_merge = dropped / total if total else 0.0
    return active_stale, stale_by_class, over_merge


def role_aliases(entities: list[Entity]) -> dict[str, str]:
    """The deterministic role-mapping layer option-1 recommends, modeled with the
    shipped `subject_aliases` config: every value of a value-named entity maps to
    one stable `role:<name>` id, so a value swap (Postgres->MySQL) keys the same
    slot and supersession fires. Coexisting entities get no alias, so distinct
    entities sharing an aspect stay distinct (over-merge guard preserved)."""
    out: dict[str, str] = {}
    for e in entities:
        if e.label_mode == "value":
            for _, v in e.changes:
                out[canonical_subject(v)] = f"role:{e.name}"
    return out


def run_arm(arm: Arm, steps: list[SessionStep], entities: list[Entity],
            backend: dict[str, object],
            real_llm: Callable[[str], str] | None = None,
            aliases: dict[str, str] | None = None,
            ttl: int | None = None) -> ArmMetrics:
    extraction: dict[str, object] = {"enabled": True}
    if aliases:
        extraction["subject_aliases"] = aliases
    cfg = StashConfig.model_validate({"backend": backend, "extraction": extraction})
    stele = Stele(cfg)
    # ttl arms differ only by window, so key the namespace and label on ttl to keep
    # each window hermetic and distinctly reported (ttl=inf is trust-forever cache).
    win = f"{ttl if ttl is not None else 'inf'}"
    suffix = f"_{win}" if arm == "stele-ledger-ttl" else ""
    ns = f"ew_{arm.replace('-', '_')}{suffix}"
    label = f"stele-ledger-ttl{win}" if arm == "stele-ledger-ttl" else arm
    # Hermetic run: clear any rows a prior run left in this namespace on a
    # persistent backend, else append-only arms accumulate across runs and the
    # numbers stop being reproducible.
    stele.purge_namespace(ns, dry_run=False)
    m = ArmMetrics(arm=label)
    knowable: dict[int, str] = {}
    last_evidence_text: dict[int, str] = {}

    for sidx, step in enumerate(steps):
        ent = entities[step.entity]
        scope = MemoryScope(namespace=ns, session_id=f"s{sidx}")
        if step.role == "evidence":
            knowable[step.entity] = step.value
            last_evidence_text[step.entity] = _artifact(ent, step)

        t0 = time.perf_counter()
        _ingest(arm, stele, ns, scope, ent, step, real_llm=real_llm)
        answer, recall_tokens, extra_turns = _decide(
            arm, stele, ns, ent, step,
            last_evidence_text.get(step.entity, _artifact(ent, step)), scope, ttl=ttl,
        )
        m.latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        # Silent entities are scored against live truth (the agent SHOULD have
        # re-derived to catch the unannounced change); witnessed entities against
        # what the agent was last shown.
        target = ent.truth_at(step.day) if ent.silent else knowable.get(step.entity)
        if target is not None:
            if answer == target:
                m.correct += 1
            else:
                if answer in {v for _, v in ent.changes} or answer == "RETIRED":
                    m.stale_actions += 1
                m.staleness_lag += 1
        elif answer == ent.truth_at(step.day):
            m.correct += 1
        m.sessions += 1
        m.turns += 1 + extra_turns
        m.tokens += recall_tokens

    last_day = steps[-1].day if steps else 0
    m.active_staleness_rate, m.stale_by_class, m.over_merge_rate = probe_store(
        arm, stele, ns, entities, last_day
    )
    return m


def run(n_sessions: int, backend: dict[str, object],
        with_role_fix: bool = False, with_ledger: bool = False,
        with_silent: bool = False,
        ttl_sweep: list[int | None] | None = None) -> dict[str, object]:
    entities = default_entities(include_silent=with_silent)
    steps = build_plan(entities, n_sessions)
    if with_silent:
        # Focused freshness-policy comparison on a world with SILENT (unannounced)
        # changes: no-memory (always re-derive, catches everything, dearest) and
        # naive-append (cache forever, goes permanently stale) bracket the frontier;
        # stele-ledger (re-derive every time) is the 0-stale ceiling; the
        # stele-ledger-ttl sweep is the knob trading turns for bounded staleness.
        sweep = ttl_sweep if ttl_sweep is not None else [3, 10, None]
        results = [
            run_arm("no-memory", steps, entities, backend).summary(),
            run_arm("naive-append", steps, entities, backend).summary(),
            run_arm("stele-ledger", steps, entities, backend).summary(),
        ]
        results += [run_arm("stele-ledger-ttl", steps, entities, backend, ttl=t).summary()
                    for t in sweep]
        return {
            "benchmark": "evolving_world",
            "scenario": "silent",
            "sessions": len(steps),
            "backend": backend.get("type"),
            "arms": results,
            "versions": version_info(),
            "generated_at": datetime.now(UTC).isoformat(),
        }
    results = [run_arm(arm, steps, entities, backend).summary() for arm in ARMS]
    if with_role_fix:
        # The recommended #72 fix (schema-backed subject_role), modeled via the
        # shipped subject_aliases layer. Validates the back-half: does keying the
        # slot on a stable role collapse value-named staleness with 0 over-merge?
        results.append(
            run_arm("stele-role", steps, entities, backend,
                    aliases=role_aliases(entities)).summary()
        )
    if with_ledger:
        # The memory-value thesis arm: store the verification METHOD, re-derive on
        # read. Shows value-named staleness collapse to 0 without supersession
        # (return_format.py's staleness-trap fix, in the multi-session sim), paid
        # for in re-derivation turns/tokens rather than stale answers.
        results.append(run_arm("stele-ledger", steps, entities, backend).summary())
    return {
        "benchmark": "evolving_world",
        "sessions": len(steps),
        "backend": backend.get("type"),
        "arms": results,
        "versions": version_info(),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _markdown(report: dict[str, object]) -> str:
    arms = cast("list[dict[str, object]]", report["arms"])
    cols = ["arm", "accuracy", "stale_action_rate", "active_staleness_rate",
            "over_merge_rate", "staleness_lag", "turns", "tokens",
            "latency_p95_ms", "efficiency"]
    lines = [
        "# Evolving-World Agent Simulation",
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
        "Store-side staleness by scenario class:",
        "",
        "| arm | stable | value (#72, named-by-value) | silent (unannounced change) |",
        "| --- | --- | --- | --- |",
    ]
    for a in arms:
        sbc = cast("dict[str, float]", a["stale_by_class"])
        lines.append(f"| {a['arm']} | {sbc.get('stable', '-')} | {sbc.get('value', '-')} "
                     f"| {sbc.get('silent', '-')} |")
    lines += [
        "",
        "Lower is better: stale_action_rate, active_staleness_rate, over_merge_rate, "
        "staleness_lag, turns, tokens, latency. Higher is better: accuracy, efficiency.",
        "`active_staleness_rate` is the #72 cross-session gate (target ≤0.10); "
        "`over_merge_rate` is the precision gate (must stay 0).",
        "`stele-ledger` stores the verification method (no value), so value-named "
        "staleness is 0 by construction (nothing stored can go stale); its cost is "
        "the extra re-derivation turns/tokens, not stale answers.",
        "`stele-ledger-ttl{N}` trusts a witnessed observation for N days then re-derives: "
        "the freshness knob trading turns for bounded staleness. ttl=inf never re-derives "
        "(pure cache) and goes permanently stale on silent (unannounced) changes; "
        "method-only `stele-ledger` re-derives every time, staying 0-stale at the most turns.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Evolving-world agent simulation benchmark")
    ap.add_argument("--sessions", type=int, default=400)
    ap.add_argument("--backend", choices=["postgres", "sqlite"], default="postgres")
    ap.add_argument("--dsn", default=None, help="postgres DSN (or env STELE_PG_DSN)")
    ap.add_argument("--sqlite-path", default="/tmp/stele_evolving_world.db")
    ap.add_argument("--out", default=None, help="output dir (default benchmarks/runs/<date>)")
    ap.add_argument("--fix", action="store_true",
                    help="add the stele-role arm (recommended #72 fix via subject_aliases)")
    ap.add_argument("--ledger", action="store_true",
                    help="add the stele-ledger arm (the thesis: store the verification "
                         "method, re-derive on read; collapses value-named staleness to 0)")
    ap.add_argument("--silent", action="store_true",
                    help="silent-change scenario + the stele-ledger-ttl freshness sweep "
                         "(trust memory N days, then re-derive)")
    ap.add_argument("--ttl-sweep", default="3,10,inf",
                    help="comma-separated TTL windows for --silent (inf = trust forever)")
    args = ap.parse_args()

    if args.backend == "postgres":
        import os
        dsn = args.dsn or os.environ.get("STELE_PG_DSN")
        if not dsn:
            raise SystemExit("postgres backend needs --dsn or STELE_PG_DSN")
        backend: dict[str, object] = {"type": "postgres", "dsn": dsn}
    else:
        backend = {"type": "sqlite", "path": args.sqlite_path}

    sweep: list[int | None] | None = None
    if args.silent:
        sweep = [None if t.strip() == "inf" else int(t) for t in args.ttl_sweep.split(",")]
    report = run(args.sessions, backend, with_role_fix=args.fix, with_ledger=args.ledger,
                 with_silent=args.silent, ttl_sweep=sweep)
    default_dir = Path("benchmarks/runs") / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir = Path(args.out) if args.out else default_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "EvolvingWorld.json").write_text(json.dumps(report, indent=2))
    (out_dir / "EvolvingWorld.md").write_text(_markdown(report))
    print(_markdown(report))
    print(f"wrote {out_dir}/EvolvingWorld.{{md,json}}")


if __name__ == "__main__":
    main()
