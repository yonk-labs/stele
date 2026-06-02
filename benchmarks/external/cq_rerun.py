# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""Additive n=40 re-run of the top mega-grid lanes, post cq-memory work (v0.4.0/0.5.0).

Purpose: confirm the sovereign-memory changes (tripartite insight, evidence/merge,
lifecycle kinds, optional pgvector memory recall) did NOT regress the document-RAG
path the mega grid measures. Those changes live in the `stele.memory` subsystem;
these lanes exercise `Stele.store` + chunk retrieval + packing, which never touch
memory. This run is a regression check, not a new result set.

Reuses sweep_matrix's store/retrieve/pack/score helpers verbatim so the recipe is
byte-identical to how the grid was produced. Writes to benchmarks/runs/cq-additive/
and leaves the MEGA-GRID results untouched (additive).

Run: STELE_PG_DSN=... .venv/bin/python -m benchmarks.external.cq_rerun --per-corpus 40
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cross_corpus_matrix import _units
from benchmarks.external.sweep_matrix import (
    _GEMMA,
    _QWEN,
    _answer,
    _clear,
    _pack,
    _retrieve,
    _rr,
    _store,
)

# The four top recipes from MEGA-GRID, with their n=40 grid baselines for reference:
#   A:sentence_aware+raw  — the shipped DEFAULT (regression anchor)  locomo .675 / covid .725 / hotpot .95
#   B:cascade_b+raw       — top retrieval recipe                     locomo .75  / covid .725 / hotpot .975
#   B:cascade_b+digest    — top retrieval + digest packing           locomo .675 / covid .725 / hotpot .975
#   raw_fetch             — whole-document ceiling                   locomo .8   / covid .725 / hotpot .95
_LANES: list[tuple[str, str, str, str, str]] = [
    ("A:sentence_aware+raw", "sentence_aware", "hybrid", "raw", "query"),
    ("B:cascade_b+raw", "sentence_aware", "cascade_b", "raw", "query"),
    ("B:cascade_b+digest", "sentence_aware", "cascade_b", "digest", "query"),
    ("raw_fetch", "sentence_aware", "raw_fetch", "raw", "none"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-corpus", type=int, default=40)
    ap.add_argument("--corpora", nargs="+", default=["locomo", "ragbench-hotpotqa", "ragbench-covidqa"])
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
        units = _units(corpus, args.per_corpus)
        store = _store(dsn, "sentence_aware")  # all four lanes use sentence_aware
        stores = {"sentence_aware": store}
        refs: dict[str, dict[str, str]] = {"sentence_aware": {}}
        _clear(store, f"cqrerun-sentence_aware-{corpus}")
        done = 0
        for unit_id, content, qas in units:
            refs["sentence_aware"][unit_id] = store.store(
                content, namespace=f"cqrerun-sentence_aware-{corpus}"
            ).reference
            for q, gold in qas:
                retr_cache: dict[tuple[str, str], tuple[list[str], float]] = {}
                rec = {"corpus": corpus, "unit": unit_id, "question": q, "gold": gold, "lanes": {}}
                for lane, ch, rt, pk, hn in _LANES:
                    if rt == "raw_fetch":
                        ctx, mrr, rms, pms = content, _rr([content], gold), 0.0, 0.0
                    else:
                        chunks, rms = _retrieve(stores, refs, unit_id, q, ch, rt, retr_cache)
                        mrr = _rr(chunks, gold)
                        tp = time.perf_counter(); ctx = _pack(pk, chunks, q, hn); pms = (time.perf_counter() - tp) * 1000
                    ta = time.perf_counter(); a = _answer(ans, ctx, q); ams = (time.perf_counter() - ta) * 1000
                    correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    rec["lanes"][lane] = {"correct": correct, "mrr": round(mrr, 4), "retr_ms": round(rms, 1),
                                          "pack_ms": round(pms, 1), "ans_ms": round(ams, 1), "ctx_chars": len(ctx)}
                rows.append(rec)
                done += 1
                if done % 5 == 0:
                    print(f"  {corpus}: {done} Qs done", flush=True)
        store.close()
        print(f"[{corpus}] done", flush=True)

    agg: dict[str, dict[str, dict[str, float]]] = {}
    for corpus in args.corpora:
        crows = [r for r in rows if r["corpus"] == corpus]
        agg[corpus] = {}
        for lane, *_ in _LANES:
            vals = [r["lanes"][lane] for r in crows if lane in r["lanes"]]
            if not vals:
                continue
            k = len(vals)
            agg[corpus][lane] = {
                "jscore": round(sum(v["correct"] for v in vals) / k, 3),
                "mrr": round(sum(v["mrr"] for v in vals) / k, 3),
                "retr_ms": round(sum(v["retr_ms"] for v in vals) / k, 1),
                "ans_ms": round(sum(v["ans_ms"] for v in vals) / k, 1),
                "ctx_chars": int(sum(v["ctx_chars"] for v in vals) / k),
                "n": k}

    print("\n=== CQ RE-RUN (jscore | mrr | retr_ms | ans_ms | ctx) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for lane in sorted(agg[corpus], key=lambda x: -agg[corpus][x]["jscore"]):
            a = agg[corpus][lane]
            print(f"  {lane:26s} js={a['jscore']:.3f} mrr={a['mrr']:.2f} retr={a['retr_ms']:6.1f} ans={a['ans_ms']:7.1f} ctx={a['ctx_chars']:6d} n={a['n']}")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"cq-rerun-{stamp}.json"
    f.write_text(json.dumps({"config": "additive n=40 regression re-run of top mega-grid lanes, post cq-memory (v0.4.0/0.5.0)",
                             "agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()
