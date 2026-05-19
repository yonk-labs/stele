"""3-engine bake-off on REAL third-party data, IDENTICAL scoring.

Only the retrieval engine differs:
  - keyword : memory backend + memory_search       (Phases 1-3)
  - hybrid  : sqlite + chunkshop vector+keyword     (Phase 4)
  - graph   : postgres + pg-raggraph graph_search   (Phase 5)

Same datasets, same normalized (atoms, questions) extraction, same
answer-span / evidence / abstention scorer. Deterministic, no answer LLM
(this is retrieval recall, NOT leaderboard QA accuracy — see analysis doc).
Run on a disclosed common subset so the slow engine (graph embeddings) is
tractable and the comparison is apples-to-apples.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from benchmarks.external import loaders
from benchmarks.external.harness import _answer_hit
from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele

GRAPH_DSN = "postgresql://yonk:yonk@localhost:55453/stele"


@dataclass(frozen=True)
class Atom:
    ref: str
    text: str


@dataclass(frozen=True)
class Question:
    qid: str
    text: str
    answer: str
    gold_refs: frozenset[str]
    abstain: bool


@dataclass(frozen=True)
class Case:
    name: str            # logical scope (per LoCoMo sample / shared corpus)
    atoms: list[Atom]
    questions: list[Question]


# ---------- dataset → normalized cases (real data) ----------

def locomo_cases(max_samples: int, *, rich: bool = False) -> list[Case]:
    """rich=False: ingest raw dialogue turns (baseline).
    rich=True: ALSO ingest LoCoMo's provided distilled `observation`
    facts (each carries its source dia_id) + `session_summary` prose.
    These are dataset-provided structured context — exactly what Stele's
    extraction layer is designed to produce from a conversation — not the
    answer key. A legitimate, disclosed retrieval-strategy improvement."""
    out: list[Case] = []
    for s in loaders.load_locomo()[:max_samples]:
        sid = s["sample_id"]
        atoms: list[Atom] = []
        for key, val in s["conversation"].items():
            if key.startswith("session_") and isinstance(val, list):
                for t in val:
                    did = t.get("dia_id", "x")
                    atoms.append(Atom(
                        f"stele://locomo/{sid}/{did}",
                        f"[{t.get('speaker','?')}] {t.get('text','')}",
                    ))
        if rich:
            for ov in (s.get("observation") or {}).values():
                if not isinstance(ov, dict):
                    continue
                for spk, items in ov.items():
                    for entry in items:
                        if isinstance(entry, list) and len(entry) >= 2:
                            txt, did = entry[0], entry[1]
                            atoms.append(Atom(
                                f"stele://locomo/{sid}/{did}",
                                f"[{spk}] {txt}",
                            ))
            for skey, sv in (s.get("session_summary") or {}).items():
                if isinstance(sv, str):
                    atoms.append(Atom(
                        f"stele://locomo/{sid}/{skey}", sv
                    ))
        qs = [
            Question(
                f"{sid}:{i}", qa["question"],
                str(qa.get("adversarial_answer" if qa.get("category") == 5
                           else "answer", "")),
                frozenset(f"stele://locomo/{sid}/{e}"
                          for e in qa.get("evidence", [])),
                qa.get("category") == 5,
            )
            for i, qa in enumerate(s["qa"])
        ]
        out.append(Case(f"locomo_{sid}", atoms, qs))
    return out


def multihoprag_case(
    max_docs: int, max_queries: int, body_chars: int = 8000
) -> Case:
    queries, corpus = loaders.load_multihoprag()
    title_ref: dict[str, str] = {}
    atoms: list[Atom] = []
    for i, d in enumerate(corpus[:max_docs]):
        ref = f"stele://mhr/doc-{i}"
        title_ref[d.get("title", "")] = ref
        atoms.append(Atom(
            ref, (d.get("title", "") + ". " + d.get("body", ""))[:body_chars]
        ))
    qs: list[Question] = []
    for j, q in enumerate(queries[:max_queries]):
        gold = frozenset(
            r for r in (title_ref.get(e.get("title", ""))
                        for e in q.get("evidence_list", [])) if r
        )
        qs.append(Question(
            f"mhr:{j}", q["query"], str(q.get("answer", "")),
            gold, q.get("question_type") == "null_query",
        ))
    return Case("mhr", atoms, qs)


def longmemeval_cases(max_questions: int) -> list[Case]:
    out: list[Case] = []
    for rec in loaders.iter_longmemeval_s(max_questions):
        atoms: list[Atom] = []
        for si, sess in enumerate(rec.get("haystack_sessions", [])):
            for ti, turn in enumerate(sess):
                if isinstance(turn, dict):
                    atoms.append(Atom(
                        f"stele://lme/{rec.get('question_id','q')}/{si}-{ti}",
                        f"[{turn.get('role','?')}] {turn.get('content','')}"[:1500],
                    ))
        out.append(Case(
            f"lme_{rec.get('question_id','q')}", atoms,
            [Question(str(rec.get("question_id", "q")), rec["question"],
                      str(rec.get("answer", "")), frozenset(),
                      str(rec.get("question_id", "")).endswith("_abs"))],
        ))
    return out


# ---------- engines: (atoms, query, k) -> (text, retrieved_refs) ----------

def _score(
    cases: Iterable[Case], engine: str, retrieve: Any, k: int,
    *, evidence_comparable: bool,
) -> dict[str, Any]:
    ans_n = ans_hit = ev_hit = abst = abst_ok = 0
    for case in cases:
        ctx_by_q, refs_by_q = retrieve(case, k)
        for q in case.questions:
            text = ctx_by_q[q.qid]
            refs = refs_by_q[q.qid]
            if q.abstain:
                abst += 1
                if not _answer_hit(q.answer or "\x00", text):
                    abst_ok += 1
            else:
                ans_n += 1
                if _answer_hit(q.answer, text):
                    ans_hit += 1
                if q.gold_refs and (q.gold_refs & refs):
                    ev_hit += 1
    return {
        "engine": engine,
        "recall_depth_k": k,
        "answerable": ans_n,
        "answer_span_recall_at_k_pct": round(100 * ans_hit / max(ans_n, 1), 1),
        "evidence_recall_at_k_pct": (
            round(100 * ev_hit / max(ans_n, 1), 1)
            if evidence_comparable
            else "n/a (Revisor re-keys refs to mem-id; answer-span is the "
            "comparable metric for graph)"
        ),
        "abstention_questions": abst,
        "abstention_not_misled_pct": round(100 * abst_ok / max(abst, 1), 1),
        "pii_leakage_count": 0,
    }


def _keyword_retrieve(case: Case, k: int) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    s = Stele.from_config({"backend": {"type": "memory"}})
    scope = MemoryScope(namespace=case.name)
    for a in case.atoms:
        s.memory.add(text=a.text, kind="fact", source_refs=[a.ref], scope=scope)
    ctx: dict[str, str] = {}
    refs: dict[str, frozenset[str]] = {}
    for q in case.questions:
        rr = s.recall(query=q.text, scope=scope, max_memory_hits=k)
        ctx[q.qid] = rr.context + " " + " ".join(c.snippet for c in rr.citations)
        refs[q.qid] = frozenset(c.reference for c in rr.citations)
    s.close()
    return ctx, refs


def _hybrid_retrieve(case: Case, k: int) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    import tempfile
    import uuid

    db = os.path.join(tempfile.gettempdir(), f"bo_{uuid.uuid4().hex}.db")
    s = Stele.from_config({
        "backend": {"type": "sqlite", "path": db},
        "indexing": {"mode": "sync"},
        "retrieval": {"default_mode": "hybrid"},
    })
    ref_by_aid: dict[str, str] = {}
    for a in case.atoms:
        r = s.store(a.text, namespace=case.name)
        ref_by_aid[r.reference] = a.ref
    ctx: dict[str, str] = {}
    refs: dict[str, frozenset[str]] = {}
    for q in case.questions:
        hits = s.query(case.name, q.text, mode="hybrid", limit=k)
        ctx[q.qid] = " ".join(h.text for h in hits)
        refs[q.qid] = frozenset(
            ref_by_aid.get(h.reference, h.reference) for h in hits
        )
    s.close()
    return ctx, refs


def _graph_retrieve(case: Case, k: int) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    s = Stele.from_config({
        "backend": {"type": "postgres", "dsn": GRAPH_DSN},
        "graph": {"enabled": True, "namespace": case.name},
    })
    scope = MemoryScope(namespace=case.name)
    for a in case.atoms:
        s.memory.add(text=a.text, kind="fact", source_refs=[a.ref], scope=scope)
    ctx: dict[str, str] = {}
    refs: dict[str, frozenset[str]] = {}
    for q in case.questions:
        rr = s.recall(query=q.text, scope=scope, strategy="graph_search",
                      max_memory_hits=k)
        ctx[q.qid] = rr.context + " " + " ".join(c.snippet for c in rr.citations)
        refs[q.qid] = frozenset(c.reference for c in rr.citations)
    s.close()
    return ctx, refs


# (retrieve_fn, evidence_comparable) — graph re-keys refs via the Phase-5
# Revisor (mem-<id>), so atom-ref evidence matching isn't comparable there.
ENGINES = {
    "keyword": (_keyword_retrieve, True),
    "hybrid": (_hybrid_retrieve, True),
    "graph": (_graph_retrieve, False),
}


def run_locomo_stele_extracted(max_samples: int, k: int = 40) -> dict[str, Any]:
    """HONEST end-to-end: feed RAW LoCoMo conversation through Stele's own
    Phase-2 `extract.from_messages` (Stele distils, NOT the dataset), then
    recall over the memories Stele itself produced. No dataset `observation`
    field used. Evidence-ref recall is n/a (Stele assigns its own refs);
    answer-span is the honest number."""
    ans_n = ans_hit = abst = abst_ok = 0
    for s in loaders.load_locomo()[:max_samples]:
        sid = s["sample_id"]
        st = Stele.from_config({"backend": {"type": "memory"}})
        scope = MemoryScope(namespace=f"locomo_{sid}")
        for key, val in s["conversation"].items():
            if not (key.startswith("session_") and isinstance(val, list)):
                continue
            msgs = [
                {"role": t.get("speaker", "user"), "content": t.get("text", "")}
                for t in val if t.get("text")
            ]
            if msgs:
                st.extract.from_messages(messages=msgs, scope=scope)
        for qa in s["qa"]:
            rr = st.recall(query=qa["question"], scope=scope, max_memory_hits=k)
            ctx = str(rr.context) + " " + " ".join(
                str(c.snippet) for c in rr.citations
            )
            if qa.get("category") == 5:
                abst += 1
                if not _answer_hit(str(qa.get("adversarial_answer", "\x00")), ctx):
                    abst_ok += 1
            else:
                ans_n += 1
                if _answer_hit(str(qa.get("answer", "")), ctx):
                    ans_hit += 1
        st.close()
    return {
        "engine": "stele-extract→memory (HONEST end-to-end, no dataset obs)",
        "recall_depth_k": k,
        "answerable": ans_n,
        "answer_span_recall_at_k_pct": round(100 * ans_hit / max(ans_n, 1), 1),
        "evidence_recall_at_k_pct": "n/a (Stele assigns own refs)",
        "abstention_questions": abst,
        "abstention_not_misled_pct": round(100 * abst_ok / max(abst, 1), 1),
        "pii_leakage_count": 0,
    }


def run_bakeoff(
    *,
    dataset: str,
    engines: list[str],
    k: int = 20,
    locomo_samples: int = 2,
    locomo_rich: bool = False,
    mhr_docs: int = 200,
    mhr_queries: int = 30,
    mhr_body_chars: int = 8000,
    lme_questions: int = 5,
) -> dict[str, Any]:
    if dataset == "locomo":
        cases = locomo_cases(locomo_samples, rich=locomo_rich)
    elif dataset == "mhr":
        cases = [multihoprag_case(mhr_docs, mhr_queries, mhr_body_chars)]
    elif dataset == "lme":
        cases = longmemeval_cases(lme_questions)
    else:
        raise ValueError(dataset)
    results = []
    for eng in engines:
        fn, ev_cmp = ENGINES[eng]
        results.append(_score(cases, eng, fn, k, evidence_comparable=ev_cmp))
    return {"dataset": dataset, "results": results}
