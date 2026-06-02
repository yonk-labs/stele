# ruff: noqa: E501 -- benchmark helper.
"""Mode: precedent-recall. Similarity recall over prior task EPISODES.

"Have I done something like this before? What tool, what result, where did I
leave it?" The unit is a whole prior episode, not a sentence. The win is
retrieving the right past episode and reading its tripartite fields: summary =
what it was, detail = how it went / tools, action = the precomputed next step.
RAG cannot do this: there is no source document in context; the episodes exist
only because they were written to memory at the end of prior sessions.

Primary metrics are deterministic: precedent_hit@k (did the right episode rank
top-k, by an ep_id we control) and triple_recall (does the answer contain the
three distinctive gold tokens, by regex). The LLM judge is never the headline.
"""

from __future__ import annotations

import re

from benchmarks.external.memory_modes.base import Case, CaseResult, Condition, RunCtx
from stele.core.memory_record import AddRequest, MemoryScope
from stele.core.stash import Stele

# 8 recurring task types; 5 quarterly variants each -> 40 semantically-adjacent
# episodes (distractors share a type, differ by quarter), all deterministic.
_TYPES: tuple[tuple[str, str], ...] = (
    ("market-trends", "review the market trends"),
    ("dep-upgrade", "upgrade the dependencies"),
    ("incident-review", "run the incident post-mortem"),
    ("perf-tuning", "tune the query performance"),
    ("schema-migration", "migrate the database schema"),
    ("security-audit", "run the security audit"),
    ("doc-refresh", "refresh the public docs"),
    ("release-cut", "cut the release"),
)
_END_STATES = ("draft", "published", "blocked", "shipped", "abandoned")


def _episodes() -> list[dict[str, str]]:
    eps: list[dict[str, str]] = []
    for ttype, verb in _TYPES:
        for q in range(1, 6):
            eps.append({
                "ep_id": f"{ttype}-q{q}",
                "task_type": ttype,
                "verb": verb,
                "tool": f"{ttype}-tool-q{q}",       # distinctive checkable token
                "result": f"{ttype}-finding-q{q}",  # distinctive checkable token
                "end_state": _END_STATES[(q - 1) % len(_END_STATES)],
                "quarter": f"Q{q}",
            })
    return eps


class PrecedentRecall:
    name = "precedent_recall"
    conditions: tuple[Condition, ...] = ("no_memory", "prompt_stuffed", "memory_driven")
    deterministic = True  # headline metrics are judge-free
    measured = (
        "Whether recall retrieves the RIGHT prior task episode (precedent_hit@k, "
        "deterministic) and whether the answer recovers its tool/result/end-state "
        "(triple_recall, regex), and at what token cost vs stuffing every episode."
    )
    not_measured = (
        "Open-ended reasoning over episodes; episodes mined from real session "
        "traces (synthetic-only for now; real_trace returns none until a trace "
        "miner derives honest gold)."
    )

    def corpus(self, source: str, n: int, seed: int) -> list[Case]:
        if source == "real_trace":
            # THIS session's real git commits as task episodes. The sha is an
            # exact join key (hit@1); no gold is invented.
            from benchmarks.external.memory_modes._session_trace import session_commits
            rcases: list[Case] = []
            for sha, subj in session_commits():
                ep = {"ep_id": sha, "task_type": "commit", "verb": subj, "quarter": "",
                      "tool": f"commit-{sha}", "result": subj[:48], "end_state": "committed"}
                q = (f"Have I already committed work like: {subj}? Name the commit, "
                     "what it changed, and its state.")
                rcases.append(Case(case_id=sha, question=q,
                                   gold=f"commit-{sha}; {subj[:48]}; committed",
                                   source=source, payload=ep))
            return rcases[:n] if n else rcases
        cases: list[Case] = []
        for ep in _episodes():
            q = (f"I am about to {ep['verb']} again for the {ep['quarter']} cycle. "
                 "Have I done this before? Name the tool I used, what I found, and "
                 "the state I left it in.")
            gold = f"{ep['tool']}; {ep['result']}; {ep['end_state']}"
            cases.append(Case(case_id=ep["ep_id"], question=q, gold=gold, source=source,
                              payload=ep))
        return cases[:n] if n else cases

    def populate(self, store: Stele, cases: list[Case]) -> None:
        if not cases:
            return
        ns = f"memmode-{self.name}-{cases[0].source}"
        scope = MemoryScope(namespace=ns)
        items: list[AddRequest] = []
        for ep in (c.payload for c in cases):
            ref = store.store(
                f"{ep['task_type']} {ep['quarter']}: tool={ep['tool']} "
                f"result={ep['result']} end_state={ep['end_state']}", namespace=ns,
            ).reference
            items.append(AddRequest(
                text=f"{ep['verb']} ({ep['quarter']})", kind="decision",
                source_refs=[ref], scope=scope,
                summary=f"{ep['verb']} ({ep['quarter']})",
                detail=f"used {ep['tool']}; found {ep['result']}",
                action=f"left in state '{ep['end_state']}'; next: continue from there",
                metadata={"ep_id": ep["ep_id"], "task_type": ep["task_type"],
                          "tool": ep["tool"], "result": ep["result"], "end_state": ep["end_state"]},
            ))
        store.memory.add_many(items)

    def run_case(self, store: Stele, case: Case, condition: Condition, ctx: RunCtx) -> CaseResult:
        ns = f"memmode-{self.name}-{case.source}"
        scope = MemoryScope(namespace=ns)
        ep = case.payload
        hit1 = hit5 = 0.0
        if condition == "no_memory":
            packed = ""
        elif condition == "prompt_stuffed":
            mems = store.memory.list(scope, limit=1000)
            packed = "\n".join(f"- {m.summary}: {m.detail}; {m.action}" for m in mems)
        else:  # memory_driven: recall by the task descriptor the agent holds
            # (not the chatty question: plainto_tsquery ANDs terms, so a long
            # NL question never matches a short episode under keyword recall.
            # The vector leg relaxes this; measured separately with --memory-vector.)
            recall_q = f"{ep['verb']} {ep['quarter']}"
            hits = store.memory.search_with_score(recall_q, scope, limit=5)
            ids = [str(h.record.metadata.get("ep_id")) for h in hits]
            hit1 = 1.0 if ids[:1] == [ep["ep_id"]] else 0.0
            hit5 = 1.0 if ep["ep_id"] in ids else 0.0
            packed = "\n".join(
                f"- {h.record.summary}: {h.record.detail}; {h.record.action}" for h in hits
            )
        answer = ctx.answer(packed, case.question) if packed else ctx.answer("(no memory)", case.question)
        triple = 1.0 if all(re.search(re.escape(tok), answer)
                            for tok in (ep["tool"], ep["result"], ep["end_state"])) else 0.0
        return CaseResult(
            output=answer,
            metric={"triple_recall": triple, "hit_at_1": hit1, "hit_at_5": hit5},
            tokens_in=ctx.count_tokens(packed),
            tokens_out=ctx.count_tokens(answer),
            deterministic=True,
        )

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        return result.metric
