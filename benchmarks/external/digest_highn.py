# ruff: noqa: E501,SIM115,E702  -- benchmark helper.
"""High-N digest lane — completes raw/digest/facts at n=250 (digest was missing from high_n_matrix).

hybrid retrieval (HNSW) + lede digest packing, n=250 stratified, with jscore + tokens + latency.
Pairs with high-n-matrix's hybrid_raw + hybrid_facts for a confident packing comparison.

Run: STELE_PG_DSN=... OPENAI_API_KEY=local .venv/bin/python -m benchmarks.external.digest_highn --n 250
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

from benchmarks.answer_workflow import OpenAICompatAnswerer
from benchmarks.external.cascade_packing_matrix import _pack as _pack_cp
from benchmarks.external.cascade_shootout import _answer
from benchmarks.external.high_n_matrix import _clear, _store, _units
from benchmarks.external.sweep_matrix import _rr

_QWEN = "Intel/Qwen3-Coder-Next-int4-AutoRound"
_GEMMA = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"


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

    agg, rows = {}, []
    for corpus in args.corpora:
        units = _units(corpus, args.n)
        st = _store(dsn, True)  # HNSW (matches high_n_matrix hybrid lanes)
        _clear(st, f"dig-{corpus}")
        ok = n = 0; toks = []; done = 0
        for uid, content, qas in units:
            ref = st.store(content, namespace=f"dig-{corpus}").reference
            for q, gold in qas:
                t = time.perf_counter()
                chunks = [h.text for h in st.search(ref, q, limit=10, mode="hybrid")]
                retr_ms = (time.perf_counter() - t) * 1000
                ctx = _pack_cp("digest", chunks, q)
                ta = time.perf_counter(); a = _answer(ans, ctx, q); ans_ms = (time.perf_counter() - ta) * 1000
                correct = bool(rj._jscore_correct(judge, question=q, expected=gold, answer=a))
                ok += correct; n += 1; toks.append(len(ctx)); done += 1
                rows.append({"corpus": corpus, "unit": uid, "q": q, "gold": gold, "correct": correct,
                             "mrr": round(_rr(chunks, gold), 4), "ctx_chars": len(ctx),
                             "retr_ms": round(retr_ms, 1), "ans_ms": round(ans_ms, 1)})
                if done % 10 == 0:
                    print(f"  {corpus}: {done} done ({ok}/{n})", flush=True)
        st.close()
        agg[corpus] = {"jscore": round(ok / n, 3), "tokens": int(sum(toks) / len(toks) / 4), "n": n}
        print(f"[digest:{corpus}] {ok}/{n} = {ok/n:.3f}  tokens~{agg[corpus]['tokens']}", flush=True)

    print("\n=== HIGH-N DIGEST (hybrid retrieval + lede digest, n=250) ===")
    for corpus, a in agg.items():
        print(f"  {corpus:20s} js={a['jscore']:.3f} tokens~{a['tokens']} n={a['n']}")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (args.out / f"digest-highn-{stamp}.json").write_text(json.dumps({"agg": agg, "rows": rows}, indent=2))
    print(f"\nwrote digest-highn-{stamp}.json")


if __name__ == "__main__":
    main()
