"""MODE A LoCoMo optimal-pathway sweep — pg-raggraph as DIRECT backend.

Reuses stele's REAL LoCoMo loader + normalized cases + the IDENTICAL
answer-span scorer (benchmarks.external.{loaders,bakeoff,harness}). The
only thing that differs vs the committed `graph` engine in bakeoff.py:
retrieval goes straight to ``pg_raggraph.GraphRAG`` (every mode + the H1
enhancer knobs reachable) instead of through Stele's ``graph_search``
Revisor wrapper. The Revisor-wrapped path is kept as a CONTRAST arm
(it is exactly how stele's production LoCoMo number is produced, and it
has a lede_spacy variant).

Pre-registered hypothesis (H1): a lexical/vector base retrieved FIRST
with the graph applied only as a re-rank/expansion ENHANCER on top
(``mode=naive_boost`` / ``mode=smart``) beats both graph-PRIMARY
(``local``/``global``/``hybrid``) and lexical-only, on LoCoMo
answer-span recall@k. Decision metrics: (L2 - L1) and (L4 - L1) vs the
graph-primary contrast group.

Apples-to-apples: identical disclosed subset / scorer / k / corpus per
cell. Path is deterministic (no RNG); the recorded qid set is the
disclosure. Every cell is persisted raw before the next runs.

Run (from the stele-phase6-7 repo root, with pg-raggraph importable):

    OPENAI_API_KEY=... uv run python -m benchmarks.external.pgrg_sweep \
        --phase stage  --ingest I1_none,I2_lede --samples 2
    uv run python -m benchmarks.external.pgrg_sweep \
        --phase sweep  --ingest I1_none,I2_lede --samples 2 --k 20
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.external import loaders  # noqa: F401  (kept: import-time dataset guard)
from benchmarks.external.bakeoff import (
    locomo_cases,
    longmemeval_cases,
    multihoprag_case,
)
from benchmarks.external.harness import _answer_hit

# pg-raggraph default dev DSN (port 5434). Override with PGRG_SWEEP_DSN.
PGRG_DSN = os.environ.get(
    "PGRG_SWEEP_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
_OUT_DEFAULT = (
    Path(__file__).resolve().parents[3]
    / "pg-raggraph"
    / "benchmarks"
    / "sweep-results"
    / "2026-05-18-locomo-sweep.json"
)
# Override so a second concurrent run doesn't race the shared JSON
# (_persist is read-modify-write, unlocked).
OUT = Path(os.environ.get("PGRG_SWEEP_OUT", str(_OUT_DEFAULT)))

# ---- Ingest matrix: 4 configs, each staged ONCE into its own namespace ----
# llm_api_key is read from env at runtime — NEVER hard-coded. Ollama is
# down in this sandbox, so fact_extractor=llm uses the OpenAI API; OpenAI
# has no distinct "coder" chat model, so I3/I4 are two OpenAI models and
# the coder/instruct split is recorded as unavailable.
INGEST_CONFIGS: dict[str, dict[str, Any]] = {
    "I1_none": {"fact_extractor": "none", "skip_extraction": True},
    "I2_lede": {"fact_extractor": "lede_spacy", "skip_extraction": True},
    "I3_llm_mini": {
        "fact_extractor": "llm",
        "skip_extraction": False,
        "llm_base_url": "https://api.openai.com/v1",
        "llm_model": "gpt-4o-mini",
        "_needs_openai": True,
    },
    "I4_llm_4o": {
        "fact_extractor": "llm",
        "skip_extraction": False,
        "llm_base_url": "https://api.openai.com/v1",
        "llm_model": "gpt-4o",
        "_needs_openai": True,
    },
    # Coder-extractor arm: local vLLM Qwen3-Coder (no API cost/key). Same
    # embedder/DB as I3_llm_mini (bge-small/384, main DB) so I3 vs I6 isolates
    # instruct (gpt-4o-mini) vs coder (Qwen3-Coder) extraction — the
    # coder-vs-instruct axis the original brief wanted.
    "I6_llm_coder": {
        "fact_extractor": "llm",
        "skip_extraction": False,
        "llm_base_url": "http://192.168.1.193:8000/v1",
        "llm_model": "Intel/Qwen3-Coder-Next-int4-AutoRound",
        "llm_api_key": "",
    },
    # Embedding ladder vs the bge-small-384 default (I1_none): 768 (the
    # chunkshop-era pg_raggraph_768 arm) and 1024 (FINAL_RESULTS.md's
    # documented "cheapest upgrade"). fact_extractor=none so ONLY the
    # embedder differs vs I1_none. Each needs its own DB — the pgvector
    # column dim is fixed per-DB at schema bootstrap from embedding_dim
    # (schema.sql `vector({dim})`).
    "I7_emb_base768": {
        "fact_extractor": "none",
        "skip_extraction": True,
        "embedding_model": "BAAI/bge-base-en-v1.5",
        "embedding_dim": 768,
        "_db": "pg_raggraph_e768",
    },
    "I5_emb_large": {
        "fact_extractor": "none",
        "skip_extraction": True,
        "embedding_model": "BAAI/bge-large-en-v1.5",
        "embedding_dim": 1024,
        "_db": "pg_raggraph_e1024",
    },
    # Different-family probe (the 2026-04-19 factorial's non-BGE arm).
    # 768-dim → shares the e768 DB with I7, different namespace.
    "I8_emb_nomic": {
        "fact_extractor": "none",
        "skip_extraction": True,
        # -Q (int8) is the FastEmbed-working variant; plain v1.5 ships a
        # broken onnx path in the FastEmbed snapshot. The 2026-04-19
        # factorial used -Q too (factorial-probe-query.py).
        "embedding_model": "nomic-ai/nomic-embed-text-v1.5-Q",
        "embedding_dim": 768,
        "_db": "pg_raggraph_e768",
    },
    # --- MultiHop-RAG arms: carry the settled embedding win forward
    # (bge-base-768 → e768 DB). The graph-vs-lexical fight LoCoMo could
    # not host: 609-doc corpus, cross-document multi-hop evidence.
    "M_none_768": {
        "fact_extractor": "none", "skip_extraction": True,
        "embedding_model": "BAAI/bge-base-en-v1.5", "embedding_dim": 768,
        "_db": "pg_raggraph_e768",
    },
    "M_lede_768": {
        "fact_extractor": "lede_spacy", "skip_extraction": True,
        "embedding_model": "BAAI/bge-base-en-v1.5", "embedding_dim": 768,
        "_db": "pg_raggraph_e768",
    },
    "M_llm_768": {
        "fact_extractor": "llm", "skip_extraction": False,
        "llm_base_url": "https://api.openai.com/v1",
        "llm_model": "gpt-4o-mini", "_needs_openai": True,
        "embedding_model": "BAAI/bge-base-en-v1.5", "embedding_dim": 768,
        "_db": "pg_raggraph_e768",
    },
}

_PG_HOST = os.environ.get(
    "PGRG_SWEEP_PG", "postgresql://postgres:postgres@localhost:5434"
)


def _dsn_for(ingest_key: str) -> str:
    """Most arms share the default DB. Embedding arms with a non-384 dim
    need their own DB (vector column dim is bootstrap-fixed per DB)."""
    db = INGEST_CONFIGS.get(ingest_key, {}).get("_db")
    return f"{_PG_HOST}/{db}" if db else PGRG_DSN

# ---- Query ladder: (label, level, config-knobs, query-kwargs) ----
# config-knobs need a fresh GraphRAG over the SAME staged namespace
# (no re-ingest). query-kwargs are per-call (mode, rerank).
def _ladder() -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    rows.append(("L1_naive", "L1", {}, {"mode": "naive"}))
    for gbf in (1.2, 1.5, 2.0):
        rows.append((
            f"L2_naive_boost_gbf{gbf}", "L2",
            {"enable_graph_boost": True, "graph_boost_factor": gbf},
            {"mode": "naive_boost"},
        ))
    for bt, et in ((0.7, 0.4), (0.6, 0.3), (0.8, 0.5)):
        rows.append((
            f"L3_smart_b{bt}_e{et}", "L3",
            {"boost_confidence_threshold": bt, "expand_confidence_threshold": et},
            {"mode": "smart"},
        ))
    rows.append((
        "L4_rerank_naive_boost_gbf1.5", "L4",
        {"enable_graph_boost": True, "graph_boost_factor": 1.5},
        {"mode": "naive_boost", "rerank": True},
    ))
    rows.append((
        "L4_rerank_smart_default", "L4",
        {"boost_confidence_threshold": 0.7, "expand_confidence_threshold": 0.4},
        {"mode": "smart", "rerank": True},
    ))
    for m in ("local", "global", "hybrid"):
        for hops in (1, 2):
            rows.append((
                f"GP_{m}_h{hops}", "GP_contrast",
                {"max_hops": hops}, {"mode": m},
            ))
    return rows


def _ns(ingest_key: str, case_name: str) -> str:
    return f"sw_{ingest_key}_{case_name}".replace("-", "_")[:60]


def _qid_digest(cases: list[Any]) -> str:
    qids = sorted(q.qid for c in cases for q in c.questions)
    return hashlib.sha256("|".join(qids).encode()).hexdigest()[:16]


def _base_cfg(ingest_key: str) -> dict[str, Any]:
    cfg = {
        k: v for k, v in INGEST_CONFIGS[ingest_key].items()
        if not k.startswith("_")
    }
    if INGEST_CONFIGS[ingest_key].get("_needs_openai"):
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise SystemExit(
                f"{ingest_key} needs fact_extractor=llm but OPENAI_API_KEY "
                "is unset. Export it (do NOT hard-code) and re-run."
            )
        cfg["llm_api_key"] = key
    cfg.update(embedding_provider="local", evolution_tier="off",
               pool_min=1, pool_max=4)
    return cfg


# ---------------------------- phases ----------------------------

async def stage_one(ingest_key: str, case: Any) -> dict[str, Any]:
    """Ingest a case's atoms ONCE into its namespace. Idempotent: skips
    if the namespace already has chunks (unless PGRG_SWEEP_FORCE=1)."""
    from pg_raggraph import GraphRAG

    ns = _ns(ingest_key, case.name)
    cfg = _base_cfg(ingest_key)
    # skip_llm short-circuits ALL extraction incl. lede_spacy
    # (__init__.py:884: `... or skip_llm_for_this_doc`). So it must be
    # True ONLY for the pure-vector "none" arm; lede_spacy and llm both
    # need skip_llm=False so their extraction path runs.
    skip_llm = INGEST_CONFIGS[ingest_key]["fact_extractor"] == "none"
    t0 = time.time()
    async with GraphRAG(_dsn_for(ingest_key), namespace=ns, **cfg) as rag:
        if os.environ.get("PGRG_SWEEP_FORCE") != "1":
            row = await rag.db.fetch_one(
                "SELECT count(*) AS n FROM chunks c JOIN documents d "
                "ON d.id=c.document_id WHERE d.namespace=%(ns)s", {"ns": ns},
            )
            if row and row["n"] >= len(case.atoms) * 0.5:
                return {"ingest_key": ingest_key, "case": case.name,
                        "ns": ns, "status": "skipped_already_staged",
                        "chunks": row["n"], "atoms": len(case.atoms)}
        records = [
            {"text": a.text, "source_id": a.ref, "skip_llm": skip_llm}
            for a in case.atoms
        ]
        await rag.ingest_records(records, namespace=ns)
        ent = await rag.db.fetch_one(
            "SELECT count(*) AS n FROM entities WHERE namespace=%(ns)s",
            {"ns": ns},
        )
        rel = await rag.db.fetch_one(
            "SELECT count(*) AS n FROM relationships WHERE namespace=%(ns)s",
            {"ns": ns},
        )
    return {
        "ingest_key": ingest_key, "case": case.name, "ns": ns,
        "status": "staged", "atoms": len(case.atoms),
        "entities": (ent or {}).get("n", 0),
        "relationships": (rel or {}).get("n", 0),
        "wall_s": round(time.time() - t0, 2),
    }


def _first_hit_rank(answer: str, ranked_texts: list[str]) -> int | None:
    """Rank (1-based) of the FIRST retrieved chunk that itself contains the
    gold answer span. Per-chunk (not concatenated) — this is what makes the
    metric rank-sensitive. Stricter than answer-span@k: a synthesized answer
    split across two turns hits neither chunk, so MRR/nDCG UNDER-state vs
    the set-membership recall. Internally consistent across all cells."""
    for i, t in enumerate(ranked_texts, 1):
        if _answer_hit(answer, t):
            return i
    return None


class _RankAcc:
    """Accumulates rank-sensitive metrics over answerable questions."""

    __slots__ = ("n", "rr", "ndcg", "h1", "h3", "ranks")

    def __init__(self) -> None:
        self.n = self.h1 = self.h3 = 0
        self.rr = self.ndcg = 0.0
        self.ranks: list[int] = []

    def add(self, fhr: int | None) -> None:
        self.n += 1
        if fhr is None:
            return
        self.rr += 1.0 / fhr
        self.ndcg += 1.0 / math.log2(fhr + 1)
        self.ranks.append(fhr)
        if fhr == 1:
            self.h1 += 1
        if fhr <= 3:
            self.h3 += 1

    def out(self) -> dict[str, Any]:
        d = max(self.n, 1)
        return {
            "mrr_at_k": round(self.rr / d, 4),
            "ndcg_at_k": round(self.ndcg / d, 4),
            "hit_at_1_pct": round(100 * self.h1 / d, 1),
            "hit_at_3_pct": round(100 * self.h3 / d, 1),
            "mean_first_hit_rank": (
                round(sum(self.ranks) / len(self.ranks), 2)
                if self.ranks else None
            ),
            "answer_bearing_chunk_recall_pct": round(
                100 * len(self.ranks) / d, 1
            ),
        }


# --- LLM-as-judge (field-standard scorer alongside deterministic
# answer-span). Free local vLLM judge by default. Single call per Q:
# the model answers from context AND self-grades vs the reference. This
# is the LongMemEval-style grader; self-grading is internally consistent
# across cells (apples-to-apples) but slightly lenient vs a separate
# judge — recorded as a methodology caveat in the report. ---
JUDGE_BASE_URL = os.environ.get("PGRG_JUDGE_URL", "http://192.168.1.193:8000/v1")
JUDGE_MODEL = os.environ.get(
    "PGRG_JUDGE_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound"
)
_JUDGE_SYS = (
    "You grade a memory/retrieval system. Using ONLY the retrieved context, "
    "answer the question, then judge whether the reference answer is fully "
    "supported by that context. Output STRICT JSON, nothing else: "
    '{"answer": "<your answer or CANNOT_ANSWER>", "correct": true|false}. '
    '"correct" is true iff the reference is supported by the context AND '
    "your answer conveys it."
)


async def _judge_one(client: Any, q: str, gold: str, ctx: str) -> bool | None:
    import json as _json

    body = {
        "model": JUDGE_MODEL,
        "temperature": 0,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": _JUDGE_SYS},
            {"role": "user", "content":
                f"QUESTION: {q}\nREFERENCE: {gold}\nCONTEXT:\n{ctx[:6000]}"},
        ],
    }
    try:
        r = await client.post(f"{JUDGE_BASE_URL}/chat/completions", json=body)
        txt = r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None
    try:
        s = txt[txt.index("{"): txt.rindex("}") + 1]
        return bool(_json.loads(s).get("correct"))
    except Exception:
        low = txt.lower()
        if '"correct": true' in low or '"correct":true' in low:
            return True
        if '"correct": false' in low or '"correct":false' in low:
            return False
        return None


async def _judge_batch(items: list[tuple[str, str, str]]) -> dict[str, Any]:
    import httpx

    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(timeout=90.0) as client:
        async def _w(it):
            async with sem:
                return await _judge_one(client, *it)
        verdicts = await asyncio.gather(*[_w(it) for it in items])
    graded = [v for v in verdicts if v is not None]
    correct = sum(1 for v in graded if v)
    return {
        "llm_judge_accuracy_pct": round(100 * correct / max(len(graded), 1), 1),
        "llm_judge_graded_n": len(graded),
        "llm_judge_errors": len(verdicts) - len(graded),
    }


async def _score_cell(rag: Any, ns: str, cases: list[Any], qcfg: dict[str, Any],
                      cases_for_ns: dict[str, Any], *,
                      judge: bool = False) -> dict[str, Any]:
    ans_n = ans_hit = abst = abst_ok = 0
    lat: list[float] = []
    nchunks: list[int] = []
    rk = _RankAcc()
    judge_items: list[tuple[str, str, str]] = []
    for case in cases:
        cns = _ns_for(case, cases_for_ns)
        for q in case.questions:
            res = await rag.query(q.text, namespace=cns, **qcfg)
            lat.append(float(res.latency_ms or 0.0))
            nchunks.append(len(res.chunks))
            ranked = [ch.content for ch in res.chunks]
            ctx = " ".join(ranked)
            if q.abstain:
                abst += 1
                if not _answer_hit(q.answer or "\x00", ctx):
                    abst_ok += 1
            else:
                ans_n += 1
                if _answer_hit(q.answer, ctx):
                    ans_hit += 1
                rk.add(_first_hit_rank(q.answer, ranked))
                if judge:
                    judge_items.append((q.text, str(q.answer), ctx))
    lat.sort()
    out = {
        "answerable": ans_n,
        "answer_span_recall_at_k_pct": round(100 * ans_hit / max(ans_n, 1), 1),
        **rk.out(),
        "abstention_questions": abst,
        "abstention_not_misled_pct": round(100 * abst_ok / max(abst, 1), 1),
        "p50_latency_ms": round(lat[len(lat) // 2], 1) if lat else 0.0,
        "avg_retrieved_chunks": round(sum(nchunks) / max(len(nchunks), 1), 2),
    }
    if judge and judge_items:
        out.update(await _judge_batch(judge_items))
    return out


def _ns_for(case: Any, mapping: dict[str, Any]) -> str:
    return mapping[case.name]


async def l0_probe(ingest_key: str, cases: list[Any], k: int, *,
                   judge: bool = False) -> dict[str, Any]:
    """Reference point: raw FTS/BM25 only (ts_rank over to_tsquery OR),
    same tsquery normalization pg-raggraph's `naive` uses. Not a native
    mode — direct SQL so the lexical baseline is honestly isolated."""
    from pg_raggraph import GraphRAG
    from pg_raggraph.retrieval import _to_or_tsquery

    cfg = _base_cfg(ingest_key)
    ans_n = ans_hit = abst = abst_ok = 0
    rk = _RankAcc()
    judge_items: list[tuple[str, str, str]] = []
    async with GraphRAG(_dsn_for(ingest_key), namespace="x", **cfg) as rag:
        for case in cases:
            ns = _ns(ingest_key, case.name)
            for q in case.questions:
                rows = await rag.db.fetch_all(
                    "SELECT COALESCE(c.embedded_content,c.content) AS content "
                    "FROM chunks c JOIN documents d ON d.id=c.document_id "
                    "WHERE d.namespace=%(ns)s "
                    "ORDER BY ts_rank(c.search_vector, "
                    "to_tsquery('english',%(tsq)s)) DESC LIMIT %(k)s",
                    {"ns": ns, "tsq": _to_or_tsquery(q.text), "k": k},
                )
                ranked = [r["content"] for r in rows]
                ctx = " ".join(ranked)
                if q.abstain:
                    abst += 1
                    if not _answer_hit(q.answer or "\x00", ctx):
                        abst_ok += 1
                else:
                    ans_n += 1
                    if _answer_hit(q.answer, ctx):
                        ans_hit += 1
                    rk.add(_first_hit_rank(q.answer, ranked))
                    if judge:
                        judge_items.append((q.text, str(q.answer), ctx))
    out = {
        "answerable": ans_n,
        "answer_span_recall_at_k_pct": round(100 * ans_hit / max(ans_n, 1), 1),
        **rk.out(),
        "abstention_questions": abst,
        "abstention_not_misled_pct": round(100 * abst_ok / max(abst, 1), 1),
        "p50_latency_ms": 0.0, "avg_retrieved_chunks": float(k),
    }
    if judge and judge_items:
        out.update(await _judge_batch(judge_items))
    return out


def _persist(cell: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = {"cells": []}
    if OUT.exists():
        data = json.loads(OUT.read_text())
    data.setdefault("cells", []).append(cell)
    data["updated"] = datetime.now(timezone.utc).isoformat()
    OUT.write_text(json.dumps(data, indent=2))


def _load_cases(dataset: str, n: int, mhr_docs: int) -> list[Any]:
    """Same Case shape across datasets (stele's bakeoff builders), so the
    rest of the harness is dataset-agnostic. `n`: locomo=#samples,
    mhr=#queries, lme=#questions."""
    if dataset == "locomo":
        return locomo_cases(n)
    if dataset == "mhr":
        return [multihoprag_case(mhr_docs, n)]
    if dataset == "lme":
        return longmemeval_cases(n)
    raise SystemExit(f"unknown dataset: {dataset}")


async def run_sweep(ingest_keys: list[str], samples: int, k: int,
                    only: list[str] | None = None, *,
                    dataset: str = "locomo", mhr_docs: int = 609,
                    judge: bool = False) -> None:
    from pg_raggraph import GraphRAG

    def _keep(label: str) -> bool:
        return not only or any(o in label for o in only)

    cases = _load_cases(dataset, samples, mhr_docs)
    qd = _qid_digest(cases)
    common = {
        "dataset": dataset,
        "samples": samples, "k": k, "qid_digest": qd,
        "n_cases": len(cases),
        "deterministic": True,
        "scorer": "benchmarks.external.harness._answer_hit (identical to bakeoff)",
        "llm_judge": JUDGE_MODEL if judge else None,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    for ik in ingest_keys:
        ns_map = {c.name: _ns(ik, c.name) for c in cases}
        # L0 reference
        if _keep("L0_fts_only"):
            r = await l0_probe(ik, cases, k, judge=judge)
            _persist({**common, "ingest_key": ik, "query_label": "L0_fts_only",
                      "level": "L0", "mode": "raw_ts_rank", "knobs": {}, **r})
            print(f"[{ik}] L0_fts_only -> {r['answer_span_recall_at_k_pct']}%")
        # L1..L4 + graph-primary contrast
        for label, level, knobs, qkw in _ladder():
            if not _keep(label):
                continue
            cfg = _base_cfg(ik)
            cfg.update(knobs)
            cfg["top_k"] = k
            t0 = time.time()
            async with GraphRAG(_dsn_for(ik), namespace="x", **cfg) as rag:
                r = await _score_cell(rag, "x", cases, qkw, ns_map,
                                      judge=judge)
            cell = {**common, "ingest_key": ik, "query_label": label,
                    "level": level, "mode": qkw.get("mode"),
                    "rerank": qkw.get("rerank", False), "knobs": knobs,
                    "wall_s": round(time.time() - t0, 2), **r}
            _persist(cell)
            print(f"[{ik}] {label} -> {r['answer_span_recall_at_k_pct']}% "
                  f"(p50 {r['p50_latency_ms']}ms)")


async def run_stage(ingest_keys: list[str], samples: int, *,
                    dataset: str = "locomo", mhr_docs: int = 609) -> None:
    cases = _load_cases(dataset, samples, mhr_docs)
    for ik in ingest_keys:
        for case in cases:
            res = await stage_one(ik, case)
            _persist({"phase": "stage", "dataset": dataset, **res,
                      "ts": datetime.now(timezone.utc).isoformat()})
            print(f"[stage {ik}] {case.name}: {res['status']} "
                  f"ents={res.get('entities','-')} "
                  f"rels={res.get('relationships','-')} "
                  f"wall={res.get('wall_s','-')}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["stage", "sweep"], required=True)
    ap.add_argument("--ingest", default="I1_none,I2_lede",
                    help="comma list of " + ",".join(INGEST_CONFIGS))
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--only", default="",
                    help="comma substrings of query_label to restrict the "
                         "sweep (narrow pass). Empty = full ladder.")
    ap.add_argument("--dataset", choices=["locomo", "mhr", "lme"],
                    default="locomo")
    ap.add_argument("--mhr-docs", type=int, default=609,
                    help="MultiHop-RAG corpus docs to ingest (full=609; the "
                         "graph needs the full corpus for cross-doc evidence)")
    ap.add_argument("--judge", action="store_true",
                    help="also score with LLM-as-judge (field-standard) "
                         f"via {JUDGE_MODEL} — alongside deterministic "
                         "answer-span. Slower; off by default.")
    a = ap.parse_args()
    keys = [x.strip() for x in a.ingest.split(",") if x.strip()]
    bad = [x for x in keys if x not in INGEST_CONFIGS]
    if bad:
        raise SystemExit(f"unknown ingest keys: {bad}")
    only = [x.strip() for x in a.only.split(",") if x.strip()] or None
    if a.phase == "stage":
        asyncio.run(run_stage(keys, a.samples, dataset=a.dataset,
                              mhr_docs=a.mhr_docs))
    else:
        asyncio.run(run_sweep(keys, a.samples, a.k, only,
                              dataset=a.dataset, mhr_docs=a.mhr_docs,
                              judge=a.judge))


if __name__ == "__main__":
    main()
