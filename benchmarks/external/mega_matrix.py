# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""Mega instrumented matrix: jscore + MRR + latency, every lane x corpus (post-fix).

Same 15 stele lanes as full_matrix, but records per (lane, question):
  correct      jscore (gemma@133, verbatim Mem0 prompt, abstention=wrong)
  mrr          reciprocal rank of first retrieved chunk containing the gold answer
               (uniform proxy across corpora/systems; 0 if absent)
  retr_ms      retrieval latency (per architecture; shared across its packings)
  pack_ms      packing latency (per lane)
  ans_ms       answer-LLM latency (qwen@193)
  ctx_chars    packed context size (token proxy)

Everything is post-fix (promoted defaults + stopword/snippet/PII fixes). Competitor
(mem0/letta) lanes are scored by their own scripts and merged at write-up time.

Run:  STELE_PG_DSN=... OPENAI_API_KEY=local \
      .venv/bin/python -m benchmarks.external.mega_matrix --per-corpus 40
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
from benchmarks.external.cascade_packing_matrix import _pack
from benchmarks.external.cascade_shootout import _answer, _lanes
from benchmarks.external.cross_corpus_matrix import _units
from benchmarks.external.full_matrix import _clear, _default_store, _enrichment_store

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
_RETR = ["keyword", "cascade_a", "cascade_b", "hybrid"]
_PACK = ["raw", "digest", "facts"]


def _rr(chunks: list[str], gold: str) -> float:
    """Reciprocal rank of the first chunk containing the gold answer (0 if none)."""
    g = (gold or "").strip().lower()
    if not g:
        return 0.0
    for i, c in enumerate(chunks):
        if g in c.lower():
            return 1.0 / (i + 1)
    return 0.0


def _retrievals(st_def, ref_def, st_enr, ref_enr, q):
    """Return {arch: (chunks, retr_ms)} for all retrieval architectures."""
    out = {}
    t = time.perf_counter(); kw = [h.text for h in st_def.search(ref_def, q, limit=10, mode="keyword")]; out["keyword"] = (kw, (time.perf_counter() - t) * 1000)
    t = time.perf_counter(); casc = _lanes(st_def, ref_def, q); casc_ms = (time.perf_counter() - t) * 1000
    out["cascade_a"] = (casc["cascade_a"], casc_ms)
    out["cascade_b"] = (casc["cascade_b"], casc_ms)
    out["hybrid"] = (casc["rrf"], casc_ms)
    t = time.perf_counter(); enr = [h.text for h in st_enr.search(ref_enr, q, limit=10, mode="hybrid")]; out["enrichment"] = (enr, (time.perf_counter() - t) * 1000)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-corpus", type=int, default=40)
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

    lanes = [f"{r}+{p}" for r in _RETR for p in _PACK] + ["enrichment+raw", "enrichment+facts", "raw_fetch"]
    rows: list[dict[str, Any]] = []
    for corpus in args.corpora:
        units = _units(corpus, args.per_corpus)
        st_def, st_enr = _default_store(dsn), _enrichment_store(dsn)
        nd, ne = f"mega-def-{corpus}", f"mega-enr-{corpus}"
        _clear(st_def, nd); _clear(st_enr, ne)
        done = 0
        for unit_id, content, qas in units:
            ref_def = st_def.store(content, namespace=nd).reference
            ref_enr = st_enr.store(content, namespace=ne).reference
            for q, gold in qas:
                retr = _retrievals(st_def, ref_def, st_enr, ref_enr, q)
                lane_specs = {}
                for r in _RETR:
                    chunks, rms = retr[r]
                    for p in _PACK:
                        lane_specs[f"{r}+{p}"] = (chunks, p, _rr(chunks, gold), rms)
                enr_chunks, enr_ms = retr["enrichment"]
                lane_specs["enrichment+raw"] = (enr_chunks, "raw", _rr(enr_chunks, gold), enr_ms)
                lane_specs["enrichment+facts"] = (enr_chunks, "facts", _rr(enr_chunks, gold), enr_ms)
                lane_specs["raw_fetch"] = ([content], "raw_fetch", _rr([content], gold), 0.0)
                rec = {"corpus": corpus, "unit": unit_id, "question": q, "gold": gold, "lanes": {}}
                for ln, (chunks, pack, mrr, rms) in lane_specs.items():
                    tp = time.perf_counter()
                    ctx = content if pack == "raw_fetch" else _pack(pack, chunks, q)
                    pack_ms = (time.perf_counter() - tp) * 1000
                    ta = time.perf_counter(); a = _answer(ans, ctx, q); ans_ms = (time.perf_counter() - ta) * 1000
                    correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                    rec["lanes"][ln] = {"correct": correct, "mrr": round(mrr, 4),
                                        "retr_ms": round(rms, 1), "pack_ms": round(pack_ms, 1),
                                        "ans_ms": round(ans_ms, 1), "ctx_chars": len(ctx)}
                rows.append(rec)
                done += 1
                if done % 5 == 0:
                    print(f"  {corpus}: {done} Qs done", flush=True)
        st_def.close(); st_enr.close()
        print(f"[{corpus}] done ({done} Qs)", flush=True)

    # aggregate
    agg: dict[str, dict[str, dict[str, float]]] = {}
    for corpus in args.corpora:
        crows = [r for r in rows if r["corpus"] == corpus]
        agg[corpus] = {}
        for ln in lanes:
            vals = [r["lanes"][ln] for r in crows if ln in r["lanes"]]
            if not vals:
                continue
            k = len(vals)
            agg[corpus][ln] = {
                "jscore": round(sum(v["correct"] for v in vals) / k, 3),
                "mrr": round(sum(v["mrr"] for v in vals) / k, 3),
                "retr_ms": round(sum(v["retr_ms"] for v in vals) / k, 1),
                "ans_ms": round(sum(v["ans_ms"] for v in vals) / k, 1),
                "ctx_chars": int(sum(v["ctx_chars"] for v in vals) / k),
                "n": k,
            }

    print("\n=== MEGA MATRIX (jscore | mrr | retr_ms | ans_ms | ctx_chars) ===")
    for corpus in args.corpora:
        print(f"\n{corpus}:")
        for ln in sorted(agg[corpus], key=lambda x: -agg[corpus][x]["jscore"]):
            a = agg[corpus][ln]
            print(f"  {ln:18s} js={a['jscore']:.2f} mrr={a['mrr']:.2f} retr={a['retr_ms']:6.1f}ms ans={a['ans_ms']:7.1f}ms ctx={a['ctx_chars']:6d}")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    f = args.out / f"mega-matrix-{stamp}.json"
    f.write_text(json.dumps({"config": "post-fix promoted defaults / 15 lanes / jscore+mrr+latency",
                             "agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote {f}")


if __name__ == "__main__":
    main()
