# ruff: noqa: E501,SIM115,SIM105,E702  -- benchmark helper.
"""New-pathway benchmark: answering from the MEMORY STORE, keyword vs vector recall.

The mega grid answers questions via document chunk-RAG (Stele.store + chunk
retrieval). The cq-memory work (v0.5.0, stele#39) opens a different pathway:
populate the `stele.memory` store with facts and answer by *recalling memories*.
This lane isolates the new capability — does fusing a pgvector semantic leg into
`memory.search_with_score` (opt-in `retrieval.memory_vector`) recall the right
fact better than the keyword-only (tsvector) path?

Same answerer + judge as the grid, so jscore is comparable. Two configs over the
same populated memories:
  - keyword : retrieval.memory_vector = False  (today's tsvector path)
  - vector  : retrieval.memory_vector = True   (RRF over tsvector + pgvector)

Reports retrieval MRR (did recall surface the gold-bearing memory) and judged
jscore (end-to-end answer correctness). Additive: writes to its own results dir.

Run: STELE_PG_DSN=... .venv/bin/python -m benchmarks.external.memory_recall_lane --per-corpus 40
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cross_corpus_matrix import _units
from benchmarks.external.sweep_matrix import _GEMMA, _QWEN, _answer, _rr
from stele.core.config import (
    BackendConfig,
    IndexingConfig,
    RetrievalConfig,
    StashConfig,
)
from stele.core.memory_record import AddRequest, MemoryScope
from stele.core.stash import Stele

_CONFIGS = [("keyword", False), ("vector", True)]
_RECALL_K = 10
_SEG_CAP = 150


def _segments(content: str, cap: int = _SEG_CAP) -> list[str]:
    """Split a document into granular memory-sized facts (1-2 sentences)."""
    raw = re.split(r"(?<=[.!?])\s+|\n+", content)
    segs: list[str] = []
    seen: set[str] = set()
    for s in raw:
        s = s.strip()
        key = s.lower()
        if 15 <= len(s) <= 400 and key not in seen:
            seen.add(key); segs.append(s)
        if len(segs) >= cap:
            break
    return segs


def _stele(dsn: str, *, vector: bool) -> Stele:
    return Stele(config=StashConfig(
        backend=BackendConfig(type="postgres", dsn=dsn),
        # No chunk index needed; we recall from the memory store. The memory
        # embedder is still synthesized from indexing.embed_model when vector=True.
        indexing=IndexingConfig(mode="skip"),
        retrieval=RetrievalConfig(default_mode="hybrid", memory_vector=vector),
    ))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-corpus", type=int, default=40)
    ap.add_argument("--corpora", nargs="+", default=["locomo"])
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cq-additive"))
    args = ap.parse_args()
    dsn = os.environ["STELE_PG_DSN"]

    spec = importlib.util.spec_from_file_location("rj", "benchmarks/external/rejudge_aw.py")
    assert spec and spec.loader
    rj = importlib.util.module_from_spec(spec); spec.loader.exec_module(rj)
    ans = OpenAICompatAnswerer(answer_model=_QWEN, judge_model=_GEMMA,
                               base_url="http://192.168.1.193:8000/v1", api_key="local",
                               judge_base_url="http://192.168.1.133:8000/v1", judge_api_key="local")
    judge = OpenAICompatAnswerer(answer_model=_GEMMA, judge_model=_GEMMA,
                                 base_url="http://192.168.1.133:8000/v1", api_key="local")

    rows: list[dict[str, Any]] = []
    for corpus in args.corpora:
        units = list(_units(corpus, args.per_corpus))
        for cfg_name, vector in _CONFIGS:
            st = _stele(dsn, vector=vector)
            ns = f"memrecall-{cfg_name}-{corpus}"
            try:
                st.purge_namespace(ns)
            except Exception:
                pass
            scope = MemoryScope(namespace=ns)
            t_pop = time.perf_counter()
            for _unit_id, content, _qas in units:
                ref = st.store(content, namespace=ns).reference
                segs = _segments(content)
                if segs:
                    st.memory.add_many([
                        AddRequest(text=s, kind="fact", source_refs=[ref], scope=scope)
                        for s in segs
                    ])
            pop_ms = (time.perf_counter() - t_pop) * 1000
            print(f"[{corpus}/{cfg_name}] populated in {pop_ms/1000:.1f}s", flush=True)

            done = 0
            for unit_id, _content, qas in units:
                for q, gold in qas:
                    tr = time.perf_counter()
                    hits = st.memory.search_with_score(q, scope, limit=_RECALL_K)
                    rms = (time.perf_counter() - tr) * 1000
                    texts = [h.record.text for h in hits]
                    mrr = _rr(texts, gold)
                    ctx = "\n".join(texts)
                    ta = time.perf_counter(); a = _answer(ans, ctx, q); ams = (time.perf_counter() - ta) * 1000
                    correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    rows.append({"corpus": corpus, "config": cfg_name, "unit": unit_id,
                                 "question": q, "gold": gold, "correct": correct,
                                 "mrr": round(mrr, 4), "retr_ms": round(rms, 1),
                                 "ans_ms": round(ams, 1), "hits": len(hits), "ctx_chars": len(ctx)})
                    done += 1
                    if done % 5 == 0:
                        print(f"  {corpus}/{cfg_name}: {done} Qs done", flush=True)
            st.close()
            print(f"[{corpus}/{cfg_name}] done", flush=True)

    agg: dict[str, dict[str, dict[str, float]]] = {}
    for corpus in args.corpora:
        agg[corpus] = {}
        for cfg_name, _ in _CONFIGS:
            vals = [r for r in rows if r["corpus"] == corpus and r["config"] == cfg_name]
            if not vals:
                continue
            k = len(vals)
            agg[corpus][cfg_name] = {
                "jscore": round(sum(v["correct"] for v in vals) / k, 3),
                "mrr": round(sum(v["mrr"] for v in vals) / k, 3),
                "retr_ms": round(sum(v["retr_ms"] for v in vals) / k, 1),
                "ans_ms": round(sum(v["ans_ms"] for v in vals) / k, 1),
                "n": k}

    print("\n=== MEMORY RECALL LANE (keyword vs vector) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for cfg_name in ("keyword", "vector"):
            if cfg_name in agg[corpus]:
                a = agg[corpus][cfg_name]
                print(f"  {cfg_name:8s} js={a['jscore']:.3f} mrr={a['mrr']:.3f} retr={a['retr_ms']:6.1f} ans={a['ans_ms']:7.1f} n={a['n']}")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"memory-recall-{stamp}.json"
    f.write_text(json.dumps({"config": "NEW PATHWAY: memory-store recall, keyword vs vector (stele#39)",
                             "agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()
