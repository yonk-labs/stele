# ruff: noqa: E501 -- benchmark helper.
"""Mode: fact-recall. Similarity recall over stored facts.

"When did X happen? Do I already know this?" RAG-over-memory done the way the
first attempts did not: the transcript is NEVER handed to the answerer, recall is
session-aware (scoped, growing store), and the primary metric is deterministic.
It measures the regime the honest findings left open: when history has scrolled
out of context, recall over stored facts is the only path.

real_trace source = LoCoMo, parsed at TURN grain (each turn is one memory tagged
with its dia_id, the join key back to the question's evidence list, so recall@K
needs no LLM). synthetic source = a small first-person dated fixture for CI.
"""

from __future__ import annotations

import ast
import re
from functools import lru_cache
from typing import Any

from benchmarks.external.memory_modes.base import Case, CaseResult, Condition, RunCtx
from stele.core.memory_record import AddRequest, MemoryScope
from stele.core.stash import Stele


@lru_cache(maxsize=1)
def _samples_by_id() -> dict[str, dict[str, Any]]:
    from benchmarks.external import loaders
    return {s["sample_id"]: s for s in loaders.load_locomo()}


def _session_keys(conv: dict[str, Any]) -> list[str]:
    keys = [k for k in conv if re.fullmatch(r"session_\d+", k)]
    return sorted(keys, key=lambda k: int(k.split("_")[1]))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _evidence(qa: dict[str, Any]) -> list[str]:
    raw = qa.get("evidence")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        val = ast.literal_eval(str(raw))
        return [str(x) for x in val] if isinstance(val, list) else [str(val)]
    except (ValueError, SyntaxError):
        return []


# Small first-person dated fixture (synthetic). Each fact has a stable id used
# as its own evidence join key.
_SYNTH: tuple[tuple[str, str, str, str], ...] = (
    ("f1", "I painted a sunrise on 8 May 2023.", "When did I paint a sunrise?", "8 May 2023"),
    ("f2", "I switched my editor to Helix on 2 March 2024.", "When did I switch to Helix?", "2 March 2024"),
    ("f3", "My flight to Tokyo was on 14 June 2023.", "When was my flight to Tokyo?", "14 June 2023"),
    ("f4", "I adopted a cat named Pixel in September 2022.", "What is my cat's name?", "Pixel"),
    ("f5", "I ran the Boston marathon in 4 hours 12 minutes.", "What was my marathon time?", "4 hours 12 minutes"),
    ("f6", "Our prod database moved to us-west-2 on 1 April 2024.", "Where did prod move?", "us-west-2"),
)


class FactRecall:
    name = "fact_recall"
    conditions: tuple[Condition, ...] = ("no_memory", "prompt_stuffed", "memory_driven")
    deterministic = True  # recall@K is judge-free
    measured = (
        "Whether session-aware similarity recall over stored facts surfaces the "
        "evidence turn (recall@K, judge-free dia_id join) and lets the agent answer "
        "(exact_match), WITHOUT the transcript in context, and at what token cost "
        "vs stuffing the whole conversation."
    )
    not_measured = (
        "Multi-hop (cat-3) and open-ended (cat-4) questions; whether memory beats "
        "RAG when the document IS present (it does not, by design, ~0.10 vs ~0.65)."
    )

    def corpus(self, source: str, n: int, seed: int) -> list[Case]:
        cases: list[Case] = []
        if source == "synthetic":
            for fid, _fact, q, gold in _SYNTH:
                cases.append(Case(case_id=fid, question=q, gold=gold, source=source,
                                  payload={"evidence": [fid], "sample_id": "synth"}))
            return cases[:n] if n else cases
        # real_trace: LoCoMo, single-hop (cat 1) + temporal (cat 2), short golds.
        for sid, sample in _samples_by_id().items():
            for i, qa in enumerate(sample.get("qa", [])):
                if str(qa.get("category")) not in ("1", "2"):
                    continue
                gold = str(qa.get("answer", "")).strip()
                ev = _evidence(qa)
                if not gold or len(gold) > 60 or not ev:
                    continue
                cases.append(Case(case_id=f"{sid}-q{i}", question=str(qa["question"]),
                                  gold=gold, source=source,
                                  payload={"evidence": ev, "sample_id": sid}))
                if n and len(cases) >= n:
                    return cases
        return cases

    def populate(self, store: Stele, cases: list[Case]) -> None:
        if not cases:
            return
        source = cases[0].source
        ns = f"memmode-{self.name}-{source}"
        if source == "synthetic":
            for fid, fact, _q, _gold in _SYNTH:
                ref = store.store(fact, namespace=ns).reference
                store.memory.add(text=fact, kind="fact", source_refs=[ref],
                                 scope=MemoryScope(namespace=ns, user_id="synth"),
                                 summary=fact, metadata={"dia_id": fid})
            return
        for sid in {c.payload["sample_id"] for c in cases}:
            conv = _samples_by_id()[sid]["conversation"]
            for sk in _session_keys(conv):
                turns = conv[sk]
                dt = conv.get(f"{sk}_date_time", "")
                ref = store.store(
                    "\n".join(f"[{t['speaker']}] {t['text']}" for t in turns),
                    namespace=ns,
                ).reference
                scope = MemoryScope(namespace=ns, user_id=sid, session_id=sk)
                store.memory.add_many([
                    AddRequest(text=f"[{t['speaker']}] {t['text']}", kind="fact",
                               source_refs=[ref], scope=scope,
                               summary=f"{t['speaker']} on {dt}", detail=str(t["text"]),
                               metadata={"dia_id": t["dia_id"], "session": sk})
                    for t in turns
                ])

    def _full_text(self, sid: str) -> str:
        if sid == "synth":
            return "\n".join(f[1] for f in _SYNTH)
        conv = _samples_by_id()[sid]["conversation"]
        return "\n".join(f"[{t['speaker']}] {t['text']}"
                         for sk in _session_keys(conv) for t in conv[sk])

    def run_case(self, store: Stele, case: Case, condition: Condition, ctx: RunCtx) -> CaseResult:
        ns = f"memmode-{self.name}-{case.source}"
        sid = case.payload["sample_id"]
        scope = MemoryScope(namespace=ns, user_id=sid)
        recall_at_k: float | None = None
        if condition == "no_memory":
            ctx_text = ""
        elif condition == "prompt_stuffed":
            ctx_text = self._full_text(sid)
        else:  # memory_driven
            hits = store.memory.search_with_score(case.question, scope, limit=10)
            got = [str(h.record.metadata.get("dia_id")) for h in hits]
            evidence = set(case.payload["evidence"])
            recall_at_k = 1.0 if evidence & set(got) else 0.0
            ctx_text = "\n".join(h.record.summary or h.record.text for h in hits)
        answer = ctx.answer(ctx_text or "(no memory)", case.question)
        gold_n = _norm(case.gold)
        exact = 1.0 if gold_n and gold_n in _norm(answer) else 0.0
        metric: dict[str, float] = {"exact_match": exact}
        if recall_at_k is not None:
            metric["recall_at_k"] = recall_at_k
        return CaseResult(
            output=answer, metric=metric,
            tokens_in=ctx.count_tokens(ctx_text), tokens_out=ctx.count_tokens(answer),
            deterministic=True,
        )

    def score(self, case: Case, result: CaseResult) -> dict[str, float]:
        return result.metric
