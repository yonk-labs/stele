# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""High-N stele matrix: key lanes + exact-vs-HNSW, n=250/corpus, stratified.

The 26-lane sweep was n=40 (2.6% of LoCoMo, capped 10/conv) — breadth, not confidence.
This runs the lanes that MATTER at n=250 drawn across ALL conversations (no per-conv cap),
plus the exact-vs-HNSW index comparison, with jscore + mrr + tokens + latency.

  raw_fetch              full doc (ceiling)
  keyword                old default floor
  hybrid_raw   (HNSW)    new default
  hybrid_raw   (exact)   hnsw=False — does exact lift small reference-filtered stores?
  hybrid_facts (HNSW)    digest+facts (temporal specialist)
  cascade_b    (HNSW)    sem->fts cascade

Run: STELE_PG_DSN=... OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.high_n_matrix --n 250
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import time
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external import loaders
from benchmarks.external.cascade_packing_matrix import _pack as _pack_cp
from benchmarks.external.cascade_shootout import _answer, _lanes
from benchmarks.external.locomo_chunker_shootout import _dialog
from benchmarks.external.sweep_matrix import _rr
from stele.core.config import BackendConfig, IndexingConfig, RetrievalConfig, StashConfig
from stele.core.stash import Stele

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
# (lane, index, retrieval, packing)
_LANES = [
    ("raw_fetch", "hnsw", "raw_fetch", "raw"),
    ("keyword", "hnsw", "keyword", "raw"),
    ("hybrid_raw_hnsw", "hnsw", "hybrid", "raw"),
    ("hybrid_raw_exact", "exact", "hybrid", "raw"),
    ("hybrid_facts_hnsw", "hnsw", "hybrid", "facts"),
    ("cascade_b_hnsw", "hnsw", "cascade_b", "raw"),
]


def _store(dsn: str, hnsw: bool) -> Stele:
    return Stele(config=StashConfig(
        backend=BackendConfig(type="postgres", dsn=dsn),
        indexing=IndexingConfig(mode="sync", provider="chunkshop", chunker="sentence_aware",
                                sentence_max_chars=1000, sentence_min_chars=300, neighbor_window=1, hnsw=hnsw),
        retrieval=RetrievalConfig(default_mode="hybrid")))


def _clear(st: Stele, ns: str) -> None:
    try:
        for h in st.list(namespace=ns, limit=100_000).items:
            st.delete(h.reference)
    except Exception:
        pass


def _retr(stores, refs, uid, q, index, rt, cache):
    key = f"{index}:{rt}"
    if key in cache:
        return cache[key]
    st, ref = stores[index], refs[index][uid]
    t = time.perf_counter()
    if rt == "hybrid":
        ch = [h.text for h in st.search(ref, q, limit=10, mode="hybrid")]
    elif rt == "keyword":
        ch = [h.text for h in st.search(ref, q, limit=10, mode="keyword")]
    else:
        ch = _lanes(st, ref, q)[rt]
    cache[key] = (ch, (time.perf_counter() - t) * 1000)
    return cache[key]


def _units(corpus: str, n: int) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Stratified: LoCoMo draws ~n/10 per conversation (no per-conv cap); ragbench full up to n."""
    out = []
    if corpus == "locomo":
        convs = loaders.load_locomo()
        per = math.ceil(n / len(convs))
        for c in convs:
            qas = [(qa["question"], str(qa.get("answer", ""))) for qa in c["qa"] if qa.get("category") != 5][:per]
            out.append((c["sample_id"], _dialog(c["conversation"]), qas))
    else:
        subset = corpus.split("-", 1)[1]
        for it in loaders.load_ragbench(subset, limit=n):
            docs = it.get("documents") or []
            out.append((str(it["id"]), "\n\n".join(docs if isinstance(docs, list) else [str(docs)]),
                        [(it["question"], str(it["response"]))]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--corpora", nargs="+", default=["locomo", "ragbench-hotpotqa", "ragbench-covidqa"])
    ap.add_argument("--out", type=Path, default=Path("benchmarks/runs/cross-corpus"))
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
        units = _units(corpus, args.n)
        stores = {"hnsw": _store(dsn, True), "exact": _store(dsn, False)}
        for k, st in stores.items():
            _clear(st, f"hn-{k}-{corpus}")
        refs: dict[str, dict[str, str]] = {"hnsw": {}, "exact": {}}
        done = 0
        for uid, content, qas in units:
            for k, st in stores.items():
                refs[k][uid] = st.store(content, namespace=f"hn-{k}-{corpus}").reference
            for q, gold in qas:
                cache: dict[str, tuple[list[str], float]] = {}
                rec = {"corpus": corpus, "unit": uid, "question": q, "gold": gold, "lanes": {}}
                for lane, index, rt, pk in _LANES:
                    if rt == "raw_fetch":
                        ctx, mrr, rms = content, _rr([content], gold), 0.0
                    else:
                        chunks, rms = _retr(stores, refs, uid, q, index, rt, cache)
                        mrr = _rr(chunks, gold)
                        ctx = _pack_cp(pk, chunks, q)
                    ta = time.perf_counter(); a = _answer(ans, ctx, q); ams = (time.perf_counter() - ta) * 1000
                    correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    rec["lanes"][lane] = {"correct": correct, "mrr": round(mrr, 4), "retr_ms": round(rms, 1),
                                          "ans_ms": round(ams, 1), "ctx_chars": len(ctx)}
                rows.append(rec)
                done += 1
                if done % 10 == 0:
                    print(f"  {corpus}: {done} Qs done", flush=True)
        for st in stores.values():
            st.close()
        print(f"[{corpus}] done ({done} Qs)", flush=True)

    # aggregate
    agg: dict[str, dict[str, Any]] = {}
    for corpus in args.corpora:
        crows = [r for r in rows if r["corpus"] == corpus]
        agg[corpus] = {}
        for lane, *_ in _LANES:
            vals = [r["lanes"][lane] for r in crows if lane in r["lanes"]]
            if not vals:
                continue
            k = len(vals)
            agg[corpus][lane] = {"jscore": round(sum(v["correct"] for v in vals) / k, 3),
                                 "mrr": round(sum(v["mrr"] for v in vals) / k, 3),
                                 "tokens": int(sum(v["ctx_chars"] for v in vals) / k / 4),
                                 "retr_ms": round(sum(v["retr_ms"] for v in vals) / k, 1),
                                 "ans_ms": round(sum(v["ans_ms"] for v in vals) / k, 1), "n": k}

    print(f"\n=== HIGH-N MATRIX (n={args.n}/corpus, stratified) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for lane in sorted(agg[corpus], key=lambda x: -agg[corpus][x]["jscore"]):
            a = agg[corpus][lane]
            print(f"  {lane:20s} js={a['jscore']:.3f} mrr={a['mrr']:.2f} tok={a['tokens']:6d} retr={a['retr_ms']:6.1f} ans={a['ans_ms']:7.1f} n={a['n']}")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"high-n-matrix-{stamp}.json"
    f.write_text(json.dumps({"config": f"high-n n={args.n} stratified / exact-vs-hnsw", "agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()
