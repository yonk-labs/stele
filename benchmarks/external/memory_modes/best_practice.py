# ruff: noqa: E501 -- benchmark helper.
"""Mode: best-practice. Enforcement, suggested (never auto-forced).

The softest enforcement mode, and suggest-only by construction: there is no
auto-accept path, because a best practice that auto-enforces is just a guardrail.
A practice is an observation earned by watching outcomes, offered as advice. The
deterministic headline is `surfaced_recall`: of the tasks where a relevant
practice exists, how often does recall surface it. No LLM is involved at all.
"""

from __future__ import annotations

from benchmarks.external.memory_modes.base import Case, CaseResult, Condition, RunCtx
from stele.core.memory_record import AddRequest, MemoryScope
from stele.core.stash import Stele

_AGENT = "advisor"


# (practice_id, domain, summary, action/advice)
_PRACTICES: tuple[tuple[str, str, str, str], ...] = (
    ("BP-CHUNK", "rag", "Sentence-aware chunking beat fixed-overlap in 5 of the last 5 runs",
     "default to sentence-aware chunking for retrieval over prose"),
    ("BP-DIGEST", "rag", "Digest+facts packing won on temporal questions repeatedly",
     "consider digest+facts packing when the query is temporal"),
    ("BP-DETERM", "bench", "Deterministic checks beat LLM judges (judge flapped 0.80 vs 0.22)",
     "prefer a regex/programmatic metric over an LLM judge for the headline"),
)
# inert cross-domain distractors so domain selection is non-trivial
_DISTRACTORS: tuple[tuple[str, str, str, str], ...] = tuple(
    (f"BPD-{dom[:2].upper()}{i}", dom, f"{dom} note #{i}", f"consider {dom} tip #{i}")
    for dom in ("ui", "ops", "docs")
    for i in range(1, 4)
)
_ALL = _PRACTICES + _DISTRACTORS

# tasks: (task_id, domain, relevant_practice_id)
_TASKS: tuple[tuple[str, str, str], ...] = (
    ("bp-chunk", "rag", "BP-CHUNK"),
    ("bp-temporal", "rag", "BP-DIGEST"),
    ("bp-metric", "bench", "BP-DETERM"),
)


class BestPractice:
    name = "best_practice"
    conditions: tuple[Condition, ...] = ("no_memory", "memory_driven")  # suggest-only: no prompt_stuffed
    deterministic = True
    measured = (
        "Whether a relevant learned best practice is surfaced (as a suggestion) "
        "when a matching task comes up. Suggest-only by construction; surfacing "
        "quality is the headline, not enforcement."
    )
    not_measured = (
        "Whether the agent then took the suggestion (take-up is out of scope; this "
        "mode never forces); the quality of the practice itself."
    )

    def corpus(self, source: str, n: int, seed: int) -> list[Case]:
        cases = [
            Case(case_id=f"{tid}-{source}", question=f"task in domain {dom}", gold=rel,
                 source=source, payload={"domain": dom, "relevant": rel})
            for (tid, dom, rel) in _TASKS
        ]
        return cases[:n] if n else cases

    def populate(self, store: Stele, cases: list[Case]) -> None:
        if not cases:
            return
        ns = f"memmode-{self.name}-{cases[0].source}"
        scope = MemoryScope(namespace=ns, agent_id=_AGENT)
        ref = store.store("PRACTICES\n" + "\n".join(p[2] for p in _ALL), namespace=ns).reference
        store.memory.add_many([
            AddRequest(text=summary, kind="summary", source_refs=[ref], scope=scope,
                       summary=summary, action=advice,
                       metadata={"practice_id": pid, "domain": dom})
            for (pid, dom, summary, advice) in _ALL
        ])

    def run_case(self, store: Stele, case: Case, condition: Condition, ctx: RunCtx) -> CaseResult:
        ns = f"memmode-{self.name}-{case.source}"
        scope = MemoryScope(namespace=ns, agent_id=_AGENT)
        if condition == "no_memory":
            surfaced_ids: list[str] = []
            tokens = 0
        else:  # memory_driven: surface practices whose domain matches
            mems = [m for m in store.memory.list(scope, limit=1000)
                    if m.metadata.get("domain") == case.payload["domain"]]
            surfaced_ids = [str(m.metadata.get("practice_id")) for m in mems]
            tokens = ctx.count_tokens("\n".join(m.action or "" for m in mems))
        hit = 1.0 if case.payload["relevant"] in surfaced_ids else 0.0
        return CaseResult(
            output=", ".join(surfaced_ids),
            metric={"surfaced": hit},
            tokens_in=tokens,
            tokens_out=0,
            deterministic=True,
            extra={"surfaced_count": len(surfaced_ids)},
        )

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        return {"surfaced_recall": result.metric["surfaced"]}
