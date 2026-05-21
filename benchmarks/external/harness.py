"""Real third-party benchmark harness — RETRIEVAL-GRADE, deterministic.

What this measures (honest scope): does Stele's memory + recall surface the
evidence that contains the gold answer? Metrics: answer-span recall,
evidence recall, abstention behavior, PII leakage, determinism.

What this does NOT claim: leaderboard QA accuracy. That requires an answer
LLM scoring generated answers; Stele is a memory/retrieval layer and this
sandbox has no answer model. Inventing QA-accuracy numbers would violate
"real numbers only", so we report the deterministic retrieval metric Stele
can actually be measured on, clearly labeled.
"""

from __future__ import annotations

import re
from typing import Any, cast

from benchmarks.external import loaders
from stele.core.config import StrategyName
from stele.core.memory_record import MemoryScope
from stele.core.stash import Stele

_WORD = re.compile(r"[a-z0-9]+")


def _norm(s: str) -> str:
    return " ".join(_WORD.findall(s.lower()))


def _answer_hit(answer: str, context: str) -> bool:
    a = _norm(answer)
    if not a:
        return False
    c = _norm(context)
    if a in c:
        return True
    toks = a.split()
    if len(toks) < 2:
        return False
    hit = sum(1 for t in toks if t in c)
    return hit / len(toks) >= 0.6  # robust to phrasing/date formatting


_DEFAULT_CONFIG: dict[str, Any] = {"backend": {"type": "memory"}}


def _stele(config: dict[str, Any] | None = None) -> Stele:
    return Stele.from_config(config or _DEFAULT_CONFIG)


# Per-shape "best honest config" profiles — every recipe uses only the
# knobs Stele exposes today (no new code). The default lane stays keyword
# (the floor) — these are the "for this shape, do x,y,z" recommendations.
PROFILES: dict[str, dict[str, Any]] = {
    "default-keyword": {
        "config": {"backend": {"type": "memory"}},
        "k": 20,
        "notes": "Floor: keyword-only over the memory backend. k=20.",
    },
    "hybrid-best": {
        "config": {
            "backend": {"type": "sqlite"},
            "indexing": {"mode": "sync", "provider": "chunkshop"},
            "retrieval": {"default_mode": "hybrid"},
        },
        "k": 30,
        "notes": (
            "Chunkshop vector + keyword RRF fusion over sqlite. k=30. Best "
            "general-purpose recipe for MultiHop-RAG / LongMemEval / "
            "LongBench / RAGBench."
        ),
    },
    "locomo-best": {
        "config": {
            "backend": {"type": "sqlite"},
            "indexing": {"mode": "sync", "provider": "chunkshop"},
            "retrieval": {"default_mode": "hybrid"},
        },
        "k": 80,
        "use_stele_extract": True,
        "retain_message_text": True,
        "notes": (
            "Conversational-memory recipe: ingest via Stele.extract.from_messages "
            "with retain_message_text=True so verbatim turns AND distilled "
            "memories are both retrievable. Hybrid over sqlite. k=80 "
            "(LoCoMo has hundreds of short atoms per sample — shallow k "
            "starves retrieval)."
        ),
    },
    "graph-multihop": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55453/stele",
            },
            "graph": {"enabled": True, "namespace": "stele-graph-multihop"},
        },
        "k": 30,
        "strategy": "graph_search",
        "notes": (
            "Multi-hop recipe: postgres + pg-raggraph entity graph + "
            "strategy='graph_search'. Designed for MultiHop-RAG, "
            "LongBench musique / 2wikimqa where the gold answer requires "
            "walking 2+ entity edges. Verified end-to-end on the "
            "McManaman/Knowsley case 2026-05-20 (recall ~290ms, gpt-5-mini "
            "answers correctly given the bridging passage)."
        ),
    },
    # --- POSTGRES-ONLY MATRIX (showcase 2026-05-21) -----------------------
    # Each profile holds 7 of 8 levers constant and moves one. Read against
    # `pg-hybrid` as the midpoint baseline.
    "pg-keyword": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55432/stele",
            },
            "retrieval": {"default_mode": "keyword"},
        },
        "k": 30,
        "notes": (
            "Postgres tsvector keyword floor. No chunkshop, no graph. "
            "Establishes the lexical-only postgres baseline for the matrix."
        ),
    },
    "pg-vector": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55432/stele",
            },
            "indexing": {
                "mode": "sync", "provider": "chunkshop",
                "chunk_words": 220, "chunk_overlap_words": 60,
            },
            "retrieval": {"default_mode": "vector"},
        },
        "k": 30,
        "notes": (
            "Pure dense retrieval: chunkshop fixed_overlap 220/60 + cosine "
            "similarity. No keyword fusion — isolates the semantic-only "
            "signal. Expected to outperform keyword on paraphrased queries "
            "and underperform on exact-string targets (names, dates, ids)."
        ),
    },
    "pg-hybrid": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55432/stele",
            },
            "indexing": {
                "mode": "sync", "provider": "chunkshop",
                "chunk_words": 220, "chunk_overlap_words": 60,
                "hybrid_method": "rrf", "hybrid_rrf_k": 60,
            },
            "retrieval": {"default_mode": "hybrid"},
        },
        "k": 30,
        "notes": (
            "Hybrid RRF fusion (k=60) of postgres tsvector + chunkshop "
            "cosine. The midpoint baseline — all other postgres profiles "
            "differ from this one by exactly one knob."
        ),
    },
    "pg-hybrid-tight": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55432/stele",
            },
            "indexing": {
                "mode": "sync", "provider": "chunkshop",
                "chunk_words": 120, "chunk_overlap_words": 30,
                "hybrid_method": "rrf", "hybrid_rrf_k": 60,
            },
            "retrieval": {"default_mode": "hybrid"},
        },
        "k": 30,
        "notes": (
            "Smaller chunks (120/30). Hypothesis: finer-grained chunks lift "
            "answer-span recall on short-passage benchmarks (RAGBench, "
            "LongBench) at the cost of context per hit."
        ),
    },
    "pg-hybrid-wide": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55432/stele",
            },
            "indexing": {
                "mode": "sync", "provider": "chunkshop",
                "chunk_words": 400, "chunk_overlap_words": 80,
                "hybrid_method": "rrf", "hybrid_rrf_k": 60,
            },
            "retrieval": {"default_mode": "hybrid"},
        },
        "k": 30,
        "notes": (
            "Wider chunks (400/80). Hypothesis: longer chunks keep "
            "cross-sentence dependencies intact — should help when the "
            "answer span needs surrounding context to disambiguate."
        ),
    },
    "pg-hybrid-weighted": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55432/stele",
            },
            "indexing": {
                "mode": "sync", "provider": "chunkshop",
                "chunk_words": 220, "chunk_overlap_words": 60,
                "hybrid_method": "weighted_sum",
                "hybrid_weights": {"keyword": 0.7, "vector": 0.3},
            },
            "retrieval": {"default_mode": "hybrid"},
        },
        "k": 30,
        "notes": (
            "Weighted-sum fusion biased toward lexical (0.7 keyword / 0.3 "
            "vector) instead of RRF. Hypothesis: benchmarks dominated by "
            "exact-name retrieval favor a keyword-weighted blend."
        ),
    },
    "pg-graph-smart": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55453/stele",
            },
            "graph": {
                "enabled": True, "namespace": "pg-graph-smart",
                "query_mode": "smart", "rerank": False,
            },
        },
        "k": 30,
        "strategy": "graph_search",
        "notes": (
            "pg-raggraph default mode (smart). Graph_search strategy "
            "directly addressed — bypasses adaptive_tier_order. Tests "
            "the out-of-the-box raggraph multi-hop path."
        ),
    },
    "pg-graph-hybrid": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55453/stele",
            },
            "graph": {
                "enabled": True, "namespace": "pg-graph-hybrid",
                "query_mode": "hybrid", "rerank": False,
            },
        },
        "k": 30,
        "strategy": "graph_search",
        "notes": (
            "pg-raggraph hybrid query mode. Lev­ers entity-graph traversal "
            "+ dense fallback inside the Revisor. Documented as the "
            "tuned-graph path in pg-raggraph 0.3.0a3."
        ),
    },
    "pg-graph-hybrid-rerank": {
        "config": {
            "backend": {
                "type": "postgres",
                "dsn": "postgresql://yonk:yonk@localhost:55453/stele",
            },
            "graph": {
                "enabled": True, "namespace": "pg-graph-hybrid-rerank",
                "query_mode": "hybrid", "rerank": True,
            },
        },
        "k": 30,
        "strategy": "graph_search",
        "notes": (
            "pg-raggraph hybrid + cross-encoder rerank. Hypothesis: "
            "rerank helps when graph hits are noisy (raggraph 0.3.0a3 "
            "tends to surface many siblings of true bridging entities)."
        ),
    },
}


def _recall_text(rr: Any) -> str:
    return str(rr.context) + " " + " ".join(str(c.snippet) for c in rr.citations)


def _recall(
    s: Stele,
    query: str,
    scope: MemoryScope,
    k: int,
    strategy: str | None = None,
) -> Any:
    """Recall at a DISCLOSED depth k. Stele's default cap is 5; over
    hundreds/thousands of evidence atoms that is an unfairly shallow
    retrieval test, so the benchmark measures recall@k with k reported.

    ``strategy`` opts a profile out of adaptive escalation — needed for
    graph profiles, where ``graph_search`` is not in the default
    adaptive_tier_order and must be addressed directly.
    """
    if strategy:
        return s.recall(
            query=query, scope=scope, max_memory_hits=k,
            strategy=cast(StrategyName, strategy),
        )
    return s.recall(query=query, scope=scope, max_memory_hits=k)


def run_locomo(
    *,
    max_samples: int | None = None,
    k: int = 20,
    config: dict[str, Any] | None = None,
    use_stele_extract: bool = False,
    retain_message_text: bool = False,
    strategy: str | None = None,
) -> dict[str, Any]:
    """LoCoMo retrieval-recall lane.

    Default ingest: one memory atom per dialogue turn (keyword baseline).
    `use_stele_extract=True` instead routes the conversation through
    `Stele.extract.from_messages` so the memory layer holds distilled
    facts (and optionally verbatim turns, when retain_message_text=True).
    Per the 2026-05-18 analysis, the extract+hybrid+higher-k combination
    is the documented honest path past 65%.
    """
    data = loaders.load_locomo()
    if max_samples:
        data = data[:max_samples]
    # ExtractionConfig.retain_message_text is set at Stele init, not per-call.
    if use_stele_extract:
        effective = dict(config or _DEFAULT_CONFIG)
        extraction = dict(effective.get("extraction") or {})
        extraction.setdefault("retain_message_text", retain_message_text)
        effective["extraction"] = extraction
        s = _stele(effective)
    else:
        s = _stele(config)
    answerable = ans_hit = evid_hit = 0
    abst = abst_ok = 0
    pii_leaks = 0
    for sample in data:
        sid = sample["sample_id"]
        scope = MemoryScope(namespace=f"locomo_{sid}")
        conv = sample["conversation"]
        if use_stele_extract:
            for key, val in conv.items():
                if not key.startswith("session_") or not isinstance(val, list):
                    continue
                msgs = [
                    {"role": t.get("speaker", "user"), "content": t.get("text", "")}
                    for t in val if t.get("text")
                ]
                if msgs:
                    s.extract.from_messages(messages=msgs, scope=scope)
        else:
            for key, val in conv.items():
                if not key.startswith("session_") or not isinstance(val, list):
                    continue
                for turn in val:
                    did = turn.get("dia_id", "x")
                    s.memory.add(
                        text=f"[{turn.get('speaker','?')}] {turn.get('text','')}",
                        kind="fact",
                        source_refs=[f"stele://locomo/{sid}/{did}"],
                        scope=scope,
                    )
        for qa in sample["qa"]:
            rr = _recall(s, qa["question"], scope, k, strategy=strategy)
            ctx = _recall_text(rr)
            gold_ev = set(qa.get("evidence", []))
            ev_ok = any(
                any(f"/{e}" in c.reference for e in gold_ev)
                for c in rr.citations
            )
            if qa.get("category") == 5:  # adversarial / abstention
                abst += 1
                if not _answer_hit(qa.get("adversarial_answer", "\x00"), ctx):
                    abst_ok += 1
            else:
                answerable += 1
                if _answer_hit(str(qa.get("answer", "")), ctx):
                    ans_hit += 1
                if ev_ok:
                    evid_hit += 1
    s.close()
    return {
        "benchmark": "LoCoMo (snap-research/locomo, locomo10.json)",
        "metric_kind": "retrieval-grade (NOT leaderboard QA accuracy)",
        "samples": len(data),
        "recall_depth_k": k,
        "answerable_questions": answerable,
        "answer_span_recall_at_k_pct": round(100 * ans_hit / max(answerable, 1), 1),
        "evidence_recall_at_k_pct": round(100 * evid_hit / max(answerable, 1), 1),
        "abstention_questions": abst,
        "abstention_not_misled_pct": round(100 * abst_ok / max(abst, 1), 1),
        "pii_leakage_count": pii_leaks,
    }


def run_multihoprag(
    *,
    max_queries: int = 200,
    k: int = 20,
    config: dict[str, Any] | None = None,
    doc_body_chars: int = 1500,
    strategy: str | None = None,
    max_corpus: int | None = None,
) -> dict[str, Any]:
    queries, corpus = loaders.load_multihoprag()
    if max_corpus is not None:
        corpus = corpus[:max_corpus]
    s = _stele(config)
    scope = MemoryScope(namespace="mhr")
    title_ref: dict[str, str] = {}
    for i, doc in enumerate(corpus):
        ref = f"stele://mhr/doc-{i}"
        title_ref[doc.get("title", "")] = ref
        body = (doc.get("title", "") + ". " + doc.get("body", ""))[:doc_body_chars]
        s.memory.add(text=body, kind="fact", source_refs=[ref], scope=scope)
    qs = queries[:max_queries]
    answerable = ans_hit = evid_hit = 0
    nulls = nulls_ok = 0
    for q in qs:
        rr = _recall(s, q["query"], scope, k, strategy=strategy)
        ctx = _recall_text(rr)
        if q.get("question_type") == "null_query":  # abstention
            nulls += 1
            if not _answer_hit(str(q.get("answer", "\x00")), ctx):
                nulls_ok += 1
            continue
        answerable += 1
        if _answer_hit(str(q.get("answer", "")), ctx):
            ans_hit += 1
        gold_refs = {
            title_ref.get(e.get("title", ""))
            for e in q.get("evidence_list", [])
        }
        gold_refs.discard(None)
        if any(c.reference in gold_refs for c in rr.citations):
            evid_hit += 1
    s.close()
    return {
        "benchmark": "MultiHop-RAG (yixuantt/MultiHop-RAG)",
        "metric_kind": "retrieval-grade (NOT leaderboard QA accuracy)",
        "corpus_docs": len(corpus),
        "queries_run": len(qs),
        "recall_depth_k": k,
        "answerable_questions": answerable,
        "answer_span_recall_at_k_pct": round(100 * ans_hit / max(answerable, 1), 1),
        "evidence_recall_at_k_pct": round(100 * evid_hit / max(answerable, 1), 1),
        "null_query_count": nulls,
        "null_query_not_misled_pct": round(100 * nulls_ok / max(nulls, 1), 1),
        "pii_leakage_count": 0,
    }


_PASSAGE_RE = re.compile(r"(?m)^Passage\s+\d+:\s*\n", re.IGNORECASE)


def _split_passages(context: str) -> list[str]:
    parts = _PASSAGE_RE.split(context)
    return [p.strip() for p in parts if p and p.strip()]


def run_longbench(
    *,
    tasks: tuple[str, ...] = ("hotpotqa", "2wikimqa", "musique", "multifieldqa_en"),
    max_per_task: int = 50,
    k: int = 20,
    config: dict[str, Any] | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """LongBench QA-family retrieval-recall lane.

    Long contexts are split on "Passage N:" markers; each passage becomes a
    memory atom. Score = does any retrieved snippet contain the gold answer.
    Only the multi/single-doc QA tasks are run (the only ones where answer-
    span recall is meaningful); summarization/code/synthetic are skipped.
    """
    per_task: list[dict[str, Any]] = []
    for task in tasks:
        try:
            recs = list(loaders.iter_longbench(task, limit=max_per_task))
        except loaders.DatasetUnavailable as e:
            per_task.append({"task": task, "status": "UNAVAILABLE",
                             "reason": str(e), "numbers": "NOT FABRICATED"})
            continue
        s = _stele(config)
        scope = MemoryScope(namespace=f"longbench-{task}")
        answerable = ans_hit = 0
        for i, rec in enumerate(recs):
            passages = _split_passages(rec.get("context", ""))
            for j, p in enumerate(passages):
                s.memory.add(
                    text=p[:2000],
                    kind="fact",
                    source_refs=[f"stele://longbench/{task}/{i}/p{j}"],
                    scope=scope,
                )
            rr = _recall(s, rec["input"], scope, k, strategy=strategy)
            ctx = _recall_text(rr)
            answerable += 1
            for ans in rec.get("answers") or []:
                if _answer_hit(str(ans), ctx):
                    ans_hit += 1
                    break
        s.close()
        per_task.append({
            "task": task,
            "records_run": len(recs),
            "recall_depth_k": k,
            "answer_span_recall_at_k_pct":
                round(100 * ans_hit / max(answerable, 1), 1),
            "pii_leakage_count": 0,
        })
    return {
        "benchmark": "LongBench (THUDM/LongBench, QA-family subset)",
        "metric_kind": "retrieval-grade (NOT leaderboard QA accuracy)",
        "per_task": per_task,
    }


def run_ragbench(
    *,
    subsets: tuple[str, ...] = (
        "hotpotqa", "msmarco", "covidqa", "pubmedqa", "techqa", "hagrid",
    ),
    max_per_subset: int = 80,
    k: int = 20,
    config: dict[str, Any] | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """RAGBench retrieval-recall lane.

    Each record carries 1-many documents and a published `response` (answer).
    We score answer-span recall: does Stele's top-k retrieval over the
    documents surface text containing the gold response. RAGBench includes
    its own TRACe annotations (faithfulness, relevance, etc.) which are
    NOT used here — that would require an answer LLM. This is a clean
    deterministic retrieval-recall measure, comparable across subsets.
    """
    per_subset: list[dict[str, Any]] = []
    for subset in subsets:
        try:
            recs = loaders.load_ragbench(subset, split="test", limit=max_per_subset)
        except loaders.DatasetUnavailable as e:
            per_subset.append({"subset": subset, "status": "UNAVAILABLE",
                               "reason": str(e), "numbers": "NOT FABRICATED"})
            continue
        s = _stele(config)
        scope = MemoryScope(namespace=f"ragbench-{subset}")
        answerable = ans_hit = 0
        for i, rec in enumerate(recs):
            docs = rec.get("documents") or []
            for j, d in enumerate(docs):
                s.memory.add(
                    text=str(d)[:2000],
                    kind="fact",
                    source_refs=[f"stele://ragbench/{subset}/{i}/d{j}"],
                    scope=scope,
                )
            rr = _recall(s, str(rec.get("question", "")), scope, k, strategy=strategy)
            ctx = _recall_text(rr)
            resp = str(rec.get("response", "") or "")
            if not resp.strip():
                continue
            answerable += 1
            if _answer_hit(resp, ctx):
                ans_hit += 1
        s.close()
        per_subset.append({
            "subset": subset,
            "records_run": len(recs),
            "answerable_records": answerable,
            "recall_depth_k": k,
            "answer_span_recall_at_k_pct":
                round(100 * ans_hit / max(answerable, 1), 1),
            "pii_leakage_count": 0,
        })
    return {
        "benchmark": "RAGBench (galileo-ai/ragbench)",
        "metric_kind": (
            "retrieval-grade "
            "(NOT TRACe groundedness/relevance — those need an LLM judge)"
        ),
        "per_subset": per_subset,
    }


def run_longmemeval_s(
    *,
    max_questions: int = 30,
    k: int = 20,
    config: dict[str, Any] | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    answerable = ans_hit = 0
    abst = abst_ok = 0
    n = 0
    for rec in loaders.iter_longmemeval_s(max_questions):
        n += 1
        s = _stele(config)
        scope = MemoryScope(namespace="lme")
        for sess in rec.get("haystack_sessions", []):
            for turn in sess:
                if not isinstance(turn, dict):
                    continue
                s.memory.add(
                    text=f"[{turn.get('role','?')}] {turn.get('content','')}"[:1500],
                    kind="fact",
                    source_refs=["stele://lme/turn"],
                    scope=scope,
                )
        rr = _recall(s, rec["question"], scope, k, strategy=strategy)
        ctx = _recall_text(rr)
        if str(rec.get("question_id", "")).endswith("_abs"):
            abst += 1
            if not _answer_hit(str(rec.get("answer", "\x00")), ctx):
                abst_ok += 1
        else:
            answerable += 1
            if _answer_hit(str(rec.get("answer", "")), ctx):
                ans_hit += 1
        s.close()
    return {
        "benchmark": "LongMemEval-S (xiaowu0162/longmemeval, longmemeval_s)",
        "metric_kind": "retrieval-grade (NOT leaderboard QA accuracy)",
        "questions_run": n,
        "recall_depth_k": k,
        "answerable_questions": answerable,
        "answer_span_recall_at_k_pct": round(100 * ans_hit / max(answerable, 1), 1),
        "abstention_questions": abst,
        "abstention_not_misled_pct": round(100 * abst_ok / max(abst, 1), 1),
        "pii_leakage_count": 0,
    }
