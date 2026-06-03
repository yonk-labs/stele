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


# (practice_id, domain, summary, action/advice, task_query that should surface it)
# Several practices share a domain, so domain selection alone is NOT enough:
# the right practice must be discriminated from same-domain siblings by recall.
_PRACTICES: tuple[tuple[str, str, str, str, str], ...] = (
    ("BP-CHUNK", "rag", "Sentence-aware chunking beat fixed-overlap in 5 of the last 5 runs",
     "default to sentence-aware chunking for retrieval over prose",
     "how should I split documents into chunks for retrieval over prose"),
    ("BP-DIGEST", "rag", "Digest+facts packing won on temporal questions repeatedly",
     "consider digest+facts packing when the query is temporal",
     "how should I pack context for a date or timeline question"),
    ("BP-RERANK", "rag", "Cross-encoder rerank lifted hit@1 on near-duplicate passages",
     "rerank the top-k with a cross-encoder when passages are near-duplicates",
     "the top results are near-duplicates, how do I get the right one to rank first"),
    ("BP-DETERM", "bench", "Deterministic checks beat LLM judges (judge flapped 0.80 vs 0.22)",
     "prefer a regex/programmatic metric over an LLM judge for the headline",
     "what kind of metric should the benchmark headline use"),
    ("BP-SEED", "bench", "Fixed seeds + recorded n made runs comparable across sessions",
     "pin the seed and record n so two runs are comparable",
     "how do I make benchmark runs reproducible across sessions"),
    ("BP-THROWAWAY", "bench", "Benchmarks on a throwaway DB avoided clobbering the live store",
     "point benchmarks at a throwaway database, never the live store",
     "which database should the benchmark write to"),
)
# inert cross-domain distractors so the domain filter has noise to reject too.
_DISTRACTORS: tuple[tuple[str, str, str, str, str], ...] = tuple(
    (f"BPD-{dom[:2].upper()}{i}", dom, f"{dom} note #{i}", f"consider {dom} tip #{i}",
     f"{dom} task variant {i}")
    for dom in ("ui", "ops", "docs")
    for i in range(1, 4)
)
_ALL = _PRACTICES + _DISTRACTORS

# tasks: (task_id, domain, relevant_practice_id, task_query)
_TASKS: tuple[tuple[str, str, str, str], ...] = tuple(
    (f"bp-{pid.split('-')[1].lower()}", dom, pid, query)
    for (pid, dom, _summary, _advice, query) in _PRACTICES
)

# Genuinely different phrasings per task. Recall must match on meaning (shared
# domain nouns) rather than echoing the practice's own words, and the variants
# triple n so the hit@1 number is more than anecdote.
_PARAPHRASES: dict[str, tuple[str, ...]] = {
    "how should I split documents into chunks for retrieval over prose": (
        "how should I split documents into chunks for retrieval over prose",
        "what chunking strategy works best when retrieving over prose",
        "best way to chunk long prose documents for retrieval",
    ),
    "how should I pack context for a date or timeline question": (
        "how should I pack context for a temporal or timeline question",
        "what packing works best for date and temporal queries",
        "the question is about timing, how do I pack the context",
    ),
    "the top results are near-duplicates, how do I get the right one to rank first": (
        "the top passages are near-duplicates, how do I rank the right one first",
        "how do I rerank when retrieved passages look near-duplicate",
        "near-duplicate passages, what reranking helps the right one win",
    ),
    "what kind of metric should the benchmark headline use": (
        "what kind of metric should the benchmark headline use",
        "should the benchmark headline metric be an LLM judge or programmatic",
        "how do I pick the headline metric for a benchmark",
    ),
    "how do I make benchmark runs reproducible across sessions": (
        "how do I make benchmark runs reproducible across sessions",
        "how do I make two benchmark runs comparable",
        "what makes benchmark runs reproducible and comparable",
    ),
    "which database should the benchmark write to": (
        "which database should the benchmark write to",
        "where should benchmarks store data, the live store or a throwaway",
        "what database do I point the benchmark at",
    ),
}


def _paraphrases(query: str) -> tuple[str, ...]:
    return _PARAPHRASES.get(query, (query,))


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
        # Each practice yields one task (the natural query) plus paraphrase
        # variants, so recall must discriminate by meaning, not by exact-word
        # echo, and n is large enough to be more than anecdote.
        cases: list[Case] = []
        for (tid, dom, rel, query) in _TASKS:
            for vi, q in enumerate(_paraphrases(query)):
                cases.append(Case(case_id=f"{tid}-v{vi}-{source}", question=q, gold=rel,
                                  source=source, payload={"domain": dom, "relevant": rel}))
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
            for (pid, dom, summary, advice, _query) in _ALL
        ])

    def run_case(self, store: Stele, case: Case, condition: Condition, ctx: RunCtx) -> CaseResult:
        ns = f"memmode-{self.name}-{case.source}"
        scope = MemoryScope(namespace=ns, agent_id=_AGENT)
        domain = case.payload["domain"]
        relevant = case.payload["relevant"]
        if condition == "no_memory":
            surfaced_ids: list[str] = []
            tokens = 0
        else:  # memory_driven: domain gate (applicability), then rank WITHIN
            # domain by recall on the task query. Same-domain siblings compete,
            # so surfacing the right one is no longer guaranteed by the gate.
            scored = store.memory.search_with_score(case.question, scope, limit=20)
            in_domain = [h for h in scored if h.record.metadata.get("domain") == domain]
            top = in_domain[:3]
            surfaced_ids = [str(h.record.metadata.get("practice_id")) for h in top]
            tokens = ctx.count_tokens("\n".join(h.record.action or "" for h in top))
        hit1 = 1.0 if surfaced_ids[:1] == [relevant] else 0.0
        recall_k = 1.0 if relevant in surfaced_ids else 0.0
        return CaseResult(
            output=", ".join(surfaced_ids),
            metric={"hit_at_1": hit1, "surfaced_recall": recall_k},
            tokens_in=tokens,
            tokens_out=0,
            deterministic=True,
            extra={"surfaced_count": len(surfaced_ids)},
        )

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        return {"hit_at_1": result.metric["hit_at_1"],
                "surfaced_recall": result.metric["surfaced_recall"]}
