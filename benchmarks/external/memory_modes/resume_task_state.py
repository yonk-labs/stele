# ruff: noqa: E501 -- benchmark helper.
"""Mode: resume-task-state. Structured-state lookup, NOT similarity recall.

"Where did we leave off on feature X? Did we finish it? Did we ever build the
widget?" The answer is the CURRENT truth about a named entity: which assertion
won (supersession head) and which subtask is marked done (WorkGraph node status).
There is no relevant passage to retrieve. The headline metric is a closed-vocab
state classification done in pure Python, no LLM. A similarity retriever returns
the nearest feature and invents a status; the entity-keyed head returns nothing
for an absent feature and scores `absent` correctly (the false_state_rate test).

Exercises two subsystems no other mode touches: the supersession head
(add(supersedes=[...]) + list newest-valid view) and the WorkGraph. WorkGraph is
not on the Stele facade, so the lane owns a SQLiteWorkGraphStore directly.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from itertools import cycle
from pathlib import Path
from typing import Any

from benchmarks.external.memory_modes.base import Case, CaseResult, Condition, RunCtx
from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele
from stele.workgraph.models import NodeStatus, TaskNode, WorkGraph
from stele.workgraph.sqlite_store import SQLiteWorkGraphStore

_BASE = datetime(2024, 1, 1, tzinfo=UTC)
_PROJECTS = ("cart-merge", "gift-wrap", "sso-login", "dark-mode", "csv-export",
             "rate-limit", "audit-log", "webhooks", "search-v2", "billing-portal",
             "oauth-scopes", "bulk-import", "pdf-export", "live-chat", "feature-flags",
             "api-keys", "saved-views", "email-digest", "mobile-push", "sla-alerts",
             "tag-editor", "quota-meter", "soft-delete", "csv-import", "role-sync",
             "geo-routing", "cache-warm", "diff-viewer", "retry-queue", "trace-export")
_GOLDS = ("done", "in_progress", "abandoned")
# gold state -> the NodeStatus the WorkGraph node carries (abandoned -> failed,
# a valid NodeStatus; graph-level "abandoned" is a different vocabulary).
_NODE_STATUS: dict[str, NodeStatus] = {"done": "done", "in_progress": "active", "abandoned": "failed"}


def _events(fid: str, gold: str) -> list[str]:
    # Terse, commit-like subjects that do NOT state status in words. Current
    # state is recoverable only from ordering/supersession: a loud early event
    # (a prod deploy, a prototype) is later overturned. This mirrors real git
    # logs (the dog-food lane), where an LLM reading raw history must INFER
    # state and frequently anchors on the loudest stale event. The structured
    # head + WorkGraph node carry the resolved current state directly.
    if gold == "done":
        return [f"spec: {fid}", f"impl {fid} core",
                f"deploy {fid} to prod", f"{fid}: add metrics + docs"]
    if gold == "in_progress":
        # shipped, then rolled back, now being reworked. "deploy to prod" is the
        # loud stale event; the current truth is the reopen.
        return [f"spec: {fid}", f"impl {fid}", f"deploy {fid} to prod",
                f"revert {fid} (incident)", f"reopen {fid}: fix root cause"]
    # abandoned: prototyped, then dropped. "impl prototype" looks like progress.
    return [f"spec: {fid}", f"impl {fid} prototype",
            f"{fid}: pause for review", f"drop {fid} from roadmap"]


def _built() -> list[dict[str, Any]]:
    return [{"fid": p, "gold": g, "events": _events(p, g)}
            for p, g in zip(_PROJECTS, cycle(_GOLDS))]


def _absent() -> list[dict[str, Any]]:
    # queried but never built -> gold "absent"
    return [{"fid": f"{p}-widget", "gold": "absent", "events": []}
            for p in _PROJECTS[:15]]


def _classify_text(answer: str) -> str:
    a = answer.lower()
    if re.search(r"\b(never|no record|don't have|not built|no such|nothing|haven'?t built)\b", a):
        return "absent"
    if re.search(r"\b(decided not|descope|abandon|won'?t build|cancel)\b", a):
        return "abandoned"
    # in-progress (incl. negated-done: "not yet done") is checked BEFORE done,
    # so "not yet done" / "not finished" do not get caught by the done keyword.
    if re.search(r"\b(in progress|underway|still|pending|working|started)\b", a) \
            or re.search(r"not\s+(yet|done|finished|complete|shipped)", a):
        return "in_progress"
    if re.search(r"\b(shipped|done|finished|complete|deployed|merged)\b", a):
        return "done"
    return "absent"


class ResumeTaskState:
    name = "resume_task_state"
    conditions: tuple[Condition, ...] = ("no_memory", "prompt_stuffed", "memory_driven")
    deterministic = True  # memory_driven headline uses no LLM
    measured = (
        "Whether an entity-keyed lookup of the supersession head + WorkGraph node "
        "status returns the correct current completion state (state_accuracy, closed "
        "4-way vocab, no LLM) and does NOT invent a status for an absent feature "
        "(false_state_rate). Token cost vs stuffing the full event log."
    )
    not_measured = (
        "Natural-language resume phrasing quality (optional judged sub-lane); "
        "as_of time-travel to a past session (a sub-lane, not the headline here)."
    )

    def __init__(self) -> None:
        self._wg: SQLiteWorkGraphStore | None = None

    def _wg_path(self, source: str) -> Path:
        return Path("benchmarks/runs/cq-additive") / f"resume-wg-{source}.sqlite"

    def corpus(self, source: str, n: int, seed: int) -> list[Case]:
        if source == "real_trace":
            # THIS session's real project state, mined from git: a feature is
            # "done" iff a commit shipped it, "absent" otherwise (the honest
            # record of what we left unbuilt, e.g. the benchmark-to-blog workflow).
            from benchmarks.external.memory_modes._session_trace import (
                SESSION_FEATURES,
                session_commits,
            )
            subjects = [s for _, s in session_commits()]
            rcases: list[Case] = []
            for fid, kw in SESSION_FEATURES:
                evs = [s for s in subjects if kw.split()[0].lower() in s.lower()]
                gold = "done" if any(kw.lower() in s.lower() for s in subjects) else "absent"
                rfeat = {"fid": fid, "gold": gold, "events": evs or ["(no commit yet)"]}
                q = (f"Did we ever build {fid}?" if gold == "absent"
                     else f"What is the current state of {fid}? Did we finish it, and what is next?")
                rcases.append(Case(case_id=fid, question=q, gold=gold, source=source, payload=rfeat))
            return rcases[:n] if n else rcases
        cases: list[Case] = []
        for feat in _built() + _absent():
            if feat["gold"] == "absent":
                q = f"Did we ever build {feat['fid']}?"
            else:
                q = f"What is the current state of {feat['fid']}? Did we finish it, and what is next?"
            cases.append(Case(case_id=feat["fid"], question=q, gold=feat["gold"],
                              source=source, payload=feat))
        return cases[:n] if n else cases

    def populate(self, store: Stele, cases: list[Case]) -> None:
        if not cases:
            return
        source = cases[0].source
        ns = f"memmode-{self.name}-{source}"
        path = self._wg_path(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()  # fresh graph each run
        wg = SQLiteWorkGraphStore(str(path))
        self._wg = wg
        gid = f"wg-{ns}"
        wg.create_graph(WorkGraph(id=gid, namespace=ns, title="resume benchmark",
                                  created_at=_BASE, updated_at=_BASE))
        scope = MemoryScope(namespace=ns)
        i = 0
        for feat in (c.payload for c in cases):
            if feat["gold"] == "absent":
                continue  # absent features have no memory atom and no node
            prior: str | None = None
            last_ref = ""
            for ev in feat["events"]:
                i += 1
                last_ref = store.store(ev, namespace=ns).reference
                res = store.memory.add(
                    text=ev, kind="decision", source_refs=[last_ref], scope=scope,
                    summary=f"feature {feat['fid']}", detail=ev,
                    action="continue from the last completed step",
                    supersedes=[prior] if prior else None,
                )
                prior = res.record.id
            ts = _BASE + timedelta(minutes=i)
            wg.add_node(TaskNode(
                id=f"node-{feat['fid']}", graph_id=gid, kind="goal",
                label=feat["fid"], summary=f"feature {feat['fid']}",
                status=_NODE_STATUS[feat["gold"]], source_refs=[last_ref],
                created_at=ts, updated_at=ts,
            ))

    def _head(self, store: Stele, ns: str, fid: str) -> str | None:
        """Active supersession head for a feature (newest-valid, entity-keyed)."""
        scope = MemoryScope(namespace=ns)
        for m in store.memory.list(scope, status_filter=["active"], limit=1000):
            if m.summary == f"feature {fid}":
                return m.text
        return None

    def _node_status(self, ns: str, fid: str) -> str | None:
        assert self._wg is not None
        nodes = self._wg.query_graph(namespace=ns, query=fid, active_only=False, limit=50)
        for nd in nodes:
            if nd.label == fid:
                return nd.status
        return None

    def run_case(self, store: Stele, case: Case, condition: Condition, ctx: RunCtx) -> CaseResult:
        ns = f"memmode-{self.name}-{case.source}"
        fid = case.payload["fid"]
        gold = case.gold
        if condition == "memory_driven":
            head = self._head(store, ns, fid)
            node = self._node_status(ns, fid)
            if head is None and node is None:
                pred = "absent"
            elif node == "done":
                pred = "done"
            elif node == "failed":
                pred = "abandoned"
            else:
                pred = "in_progress"
            ctx_tokens = ctx.count_tokens((head or "") + (node or ""))
            answer = f"{pred}"
        else:
            if condition == "no_memory":
                # Knows the feature was proposed (the spec line) but has no
                # memory of its progress — the honest floor. Using the LAST
                # event would leak the resolved state into the prompt.
                ctx_text = (case.payload["events"] or ["(no record)"])[0]
            else:  # prompt_stuffed: the whole event log for this feature
                ctx_text = "\n".join(case.payload["events"]) or "(no record)"
            answer = ctx.answer(ctx_text, case.question)
            pred = _classify_text(answer)
            ctx_tokens = ctx.count_tokens(ctx_text)
        correct = 1.0 if pred == gold else 0.0
        false_state = 1.0 if gold == "absent" and pred != "absent" else 0.0
        return CaseResult(
            output=answer,
            metric={"state_accuracy": correct, "false_state": false_state},
            tokens_in=ctx_tokens, tokens_out=ctx.count_tokens(answer),
            deterministic=(condition == "memory_driven"),
            extra={"pred": pred},
        )

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        return {"state_accuracy": result.metric["state_accuracy"],
                "false_state": result.metric["false_state"]}
